import json
from pathlib import Path

import pytest

from day_plan.http import HttpError
from day_plan.overpass import (
    MIRRORS, OverpassError, RouteInfo, format_interval, interval_minutes, parse_routes, routes_near,
    routes_query, run,
)

FIXTURES = Path(__file__).parent / "fixtures"
MADRID = json.loads((FIXTURES / "overpass_routes_madrid.json").read_text(encoding="utf-8"))
MOSCOW = json.loads((FIXTURES / "overpass_routes_moscow.json").read_text(encoding="utf-8"))
GOOD = {"elements": [{"tags": {"route": "bus", "ref": "1"}}]}


class Web:
    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def __call__(self, url):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_first_mirror_that_answers_wins():
    web = Web(HttpError("HTTP Error 429"), GOOD)
    assert run(web, "QL", sleep=lambda s: None) == GOOD
    assert web.urls[0].startswith(MIRRORS[0] + "?data=") and web.urls[1].startswith(MIRRORS[1])


def test_html_error_pages_and_runtime_errors_are_skipped():
    web = Web(HttpError("Expecting value"), {"remark": "runtime error: Query timed out", "elements": []}, {"unexpected": 1}, GOOD)
    assert run(web, "QL", mirrors=MIRRORS + ("https://x/api",), sleep=lambda s: None) == GOOD


def test_all_mirrors_are_retried_once_after_a_pause_then_it_gives_up():
    naps = []
    web = Web(*[HttpError("504")] * 6)
    with pytest.raises(OverpassError, match="504"):
        run(web, "QL", sleep=naps.append, backoff=3.0)
    assert len(web.urls) == 6 and naps == [3.0]


def test_query_text_is_url_encoded():
    web = Web(GOOD)
    run(web, 'node["a"="b"];', sleep=lambda s: None)
    assert '%22' in web.urls[0] and ' ' not in web.urls[0]


def test_routes_query_mentions_the_point_and_the_route_types():
    ql = routes_query(40.4247, -3.7275)
    assert "node(around:80,40.42470,-3.72750)" in ql and "subway" in ql and "out tags" in ql


def test_parse_real_madrid_bus_relations():
    routes = parse_routes(MADRID)
    assert [(r.mode, r.ref) for r in routes] == [("bus", "41"), ("bus", "41"), ("bus", "75"), ("bus", "75")]
    assert routes[0].from_ or routes[0].name
    assert all(r.interval == "" and r.opening_hours == "" for r in routes)     # OSM has no schedule here


def test_parse_real_moscow_relations_with_interval_and_hours():
    routes = parse_routes(MOSCOW)
    train = [r for r in routes if r.mode == "train"]
    assert train and train[0].interval == "30" and train[0].opening_hours == "Mo-Su 05:30-00:10"
    assert [r.mode for r in routes] == sorted((r.mode for r in routes),
                                              key=("bus", "train").index)         # sorted by mode order


def test_duplicates_and_foreign_route_types_are_dropped():
    data = {"elements": [{"tags": {"route": "bus", "ref": "9", "name": "A"}}, {"tags": {"route": "bus", "ref": "9", "name": "A"}},
                         {"tags": {"route": "hiking", "ref": "GR"}}, {"tags": {"route": "bus", "ref": "10", "name": "B"}},
                         {"tags": {"route": "bus", "ref": "2", "name": "C"}}, {}]}
    assert [(r.ref) for r in parse_routes(data)] == ["2", "9", "10"]      # natural order: 2 < 9 < 10


def test_routes_near_caches_for_a_week(make_route, fixed_now):
    from day_plan.context import build_context
    import datetime
    web = Web(MADRID)
    ctx = build_context(make_route(), datetime.date(2026, 6, 27), http=web, now=fixed_now)
    first = routes_near(ctx, 40.4247, -3.7275)
    second = routes_near(ctx, 40.4247, -3.7275)
    assert len(web.urls) == 1 and first == second and isinstance(first[0], RouteInfo)


@pytest.mark.parametrize("raw,minutes", [("10", 10), ("00:10", 10), ("00:10:00", 10), ("1:30", 90), ("0", None),
                                         ("10-15", None), ("", None), ("often", None)])
def test_interval_minutes(raw, minutes):
    assert interval_minutes(raw) == minutes


def test_format_interval_is_localized_and_falls_back_to_the_raw_text():
    assert format_interval("30", "en") == "every 30 min"
    assert format_interval("30", "ru") == "каждые 30 мин"
    assert format_interval("10-15", "en") == "10-15"
    assert format_interval("", "en") == "–"


@pytest.mark.parametrize("raw", ["²", "①", None, "٣"])
def test_interval_minutes_ignores_unicode_digits(raw):
    assert interval_minutes(raw) is None


def test_the_server_gives_up_before_the_http_client_does():
    assert "[timeout:9]" in routes_query(40.4, -3.7)


def test_an_empty_answer_is_cached_for_a_day_and_a_non_empty_one_for_a_week(make_route, fixed_now):
    import datetime
    from day_plan.cache import JsonCache
    from day_plan.context import build_context
    clock = [1_000_000.0]
    for name, data, ttl in (("empty", {"elements": []}, 86400), ("full", MADRID, 7 * 86400)):
        route_dir = make_route(folder=name)
        web = Web(data, data)
        ctx = build_context(route_dir, datetime.date(2026, 6, 27), http=web, now=fixed_now,
                            cache=JsonCache(route_dir / "c.json", now=lambda: clock[0]))
        start = clock[0]
        routes_near(ctx, 40.4247, -3.7275)
        clock[0] = start + ttl - 60
        routes_near(ctx, 40.4247, -3.7275)
        assert len(web.urls) == 1, name                 # still cached just before the limit
        clock[0] = start + ttl + 60
        routes_near(ctx, 40.4247, -3.7275)
        assert len(web.urls) == 2, name                 # expired just after it


# ---- the mirrors a run has found dead are not asked first again; the reasons are reported --------------------------------

from day_plan.overpass import MirrorHealth


class Recorder:
    def __init__(self):
        self.events = []

    def note(self, key, **params):
        self.events.append(("note", key, params))

    def warn(self, key, **params):
        self.events.append(("warn", key, params))


def test_a_failed_mirror_is_asked_last_by_the_next_call_and_the_last_good_one_first():
    health = MirrorHealth()
    web = Web(HttpError("timed out"), GOOD, GOOD)
    run(web, "A", sleep=lambda s: None, health=health)                   # mirror 0 fails, mirror 1 answers
    run(web, "B", sleep=lambda s: None, health=health)                   # starts with mirror 1
    assert [u.split("?")[0] for u in web.urls] == [MIRRORS[0], MIRRORS[1], MIRRORS[1]]


def test_without_health_the_order_is_unchanged():
    web = Web(HttpError("x"), GOOD, HttpError("x"), GOOD)
    run(web, "A", sleep=lambda s: None)
    run(web, "B", sleep=lambda s: None)
    assert [u.split("?")[0] for u in web.urls] == [MIRRORS[0], MIRRORS[1], MIRRORS[0], MIRRORS[1]]


def test_health_ordering_rules():
    health = MirrorHealth()
    assert health.ordered(MIRRORS) == list(MIRRORS)
    health.failed(MIRRORS[0])
    assert health.ordered(MIRRORS) == [MIRRORS[1], MIRRORS[2], MIRRORS[0]]
    health.worked(MIRRORS[2])
    assert health.ordered(MIRRORS) == [MIRRORS[2], MIRRORS[1], MIRRORS[0]]
    health.failed(MIRRORS[2])                                              # the favourite dies: back to the order
    assert health.ordered(MIRRORS) == [MIRRORS[1], MIRRORS[0], MIRRORS[2]]
    health.worked(MIRRORS[0])                                              # a recovered mirror leaves the failed set
    assert health.ordered(MIRRORS) == [MIRRORS[0], MIRRORS[1], MIRRORS[2]]


def test_all_mirrors_dead_behaves_as_before_with_health_and_progress():
    naps, recorder = [], Recorder()
    web = Web(*[HttpError("504")] * 6)
    with pytest.raises(OverpassError, match="504"):
        run(web, "QL", sleep=naps.append, backoff=3.0, health=MirrorHealth(), progress=recorder)
    assert len(web.urls) == 6 and naps == [3.0]
    warns = [e for e in recorder.events if e[0] == "warn"]
    assert len(warns) == 6 and warns[0][1] == "overpass_failed" and warns[0][2]["endpoint"] == "overpass-api.de"
    assert ("note", "overpass_attempt", {"endpoint": "overpass-api.de", "n": 2, "m": 2}) in recorder.events


def test_every_kind_of_skipped_mirror_is_reported():
    recorder = Recorder()
    web = Web(HttpError("timed out"), {"remark": "runtime error: Query timed out", "elements": []}, {"unexpected": 1}, GOOD)
    run(web, "QL", mirrors=MIRRORS + ("https://x/api",), sleep=lambda s: None, progress=recorder)
    assert [(e[1], e[2]["endpoint"], e[2]["reason"][:20]) for e in recorder.events] == [
        ("overpass_failed", "overpass-api.de", "timed out"),
        ("overpass_failed", "overpass.kumi.systems", "runtime error: Query"),
        ("overpass_failed", "overpass.private.coffee", "unexpected response")]


def test_routes_near_uses_the_shared_health_of_the_run(make_route, fixed_now):
    import datetime
    from day_plan.context import build_context
    route_dir = make_route()
    web = Web(HttpError("timed out"), MADRID, MADRID)
    ctx = build_context(route_dir, datetime.date(2026, 6, 27), http=web, now=fixed_now)
    routes_near(ctx, 40.4247, -3.7275)
    routes_near(ctx, 40.5, -3.8)
    assert [u.split("?")[0] for u in web.urls] == [MIRRORS[0], MIRRORS[1], MIRRORS[1]]


def test_run_plugins_hands_its_progress_to_the_plugins_through_the_context(make_route, fixed_now):
    import datetime
    from day_plan.base import SectionPlugin
    from day_plan.context import build_context
    from day_plan.service import run_plugins

    seen = []

    class Probe(SectionPlugin):
        plugin_id, section_id = "light", "light"

        def run(self, ctx, shared):
            seen.append(ctx.progress)
            from day_plan.base import Section
            return Section("light", "x", "derived")

    import io
    from day_plan.progress import Progress
    marker = Progress(stream=io.StringIO())
    ctx = build_context(make_route(), datetime.date(2026, 6, 27), http=lambda u: {}, now=fixed_now)
    run_plugins(ctx, [Probe()], progress=marker)
    assert seen == [marker]
