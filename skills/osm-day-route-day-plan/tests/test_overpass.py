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
