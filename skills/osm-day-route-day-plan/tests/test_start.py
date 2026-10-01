import pytest

from day_plan.start import recommend_start

H = 60


def test_no_duration_recommends_nothing():
    assert recommend_start(None, sunrise=300, sunset=1200).status == "no_duration"
    assert recommend_start(0).status == "no_duration"


def test_plain_summer_day_starts_at_seven():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281)
    assert rec.status == "ok" and rec.start_min == 7 * H
    assert (rec.earliest, rec.earliest_limit) == (283, "sunrise")
    assert (rec.latest, rec.latest_limit) == (1281 - 60 - 300, "sunset")


def test_the_seven_oclock_preference_is_dropped_when_the_route_would_not_fit():
    # sunset 17:00, 9 h route: latest = 17:00 - 1 h - 9 h = 07:00 is fine; 10 h route: latest = 06:00 < 07:00
    rec = recommend_start(10 * H, sunrise=5 * H, sunset=17 * H)
    assert rec.status == "ok" and rec.start_min == 5 * H and rec.latest == 6 * H


def test_first_arrival_and_start_point_opening_raise_the_earliest():
    rec = recommend_start(4 * H, sunrise=300, sunset=1200, start_open=8 * H, first_arrival=9 * H + 10)
    assert rec.start_min == 9 * H + 10 and rec.earliest_limit == "first_arrival"
    rec = recommend_start(4 * H, sunrise=300, sunset=1200, start_open=10 * H, first_arrival=9 * H)
    assert rec.start_min == 10 * H and rec.earliest_limit == "start_open"


def test_last_departure_and_end_point_closing_lower_the_latest():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=14 * H)
    assert rec.latest == 14 * H - 30 - 300 and rec.latest_limit == "last_departure" and rec.start_min == 7 * H
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, end_close=15 * H)
    assert rec.latest == 10 * H and rec.latest_limit == "end_close"


def test_a_departure_after_midnight_is_a_loose_limit():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=24 * H + 20)
    assert rec.latest_limit == "sunset"


def test_when_seven_is_too_late_the_earliest_feasible_start_is_taken():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=12 * H)
    assert rec.status == "ok" and rec.start_min == 283 and rec.latest == 390


def test_empty_window_names_both_limits_and_uses_the_daylight_start():
    rec = recommend_start(9 * H, sunrise=330, sunset=18 * H, first_arrival=9 * H + 10)
    assert rec.status == "empty_window"
    assert (rec.earliest_limit, rec.latest_limit) == ("first_arrival", "sunset")
    assert rec.start_min == 18 * H - 60 - 9 * H == 8 * H


def test_no_limits_at_all_uses_the_preference():
    rec = recommend_start(3 * H)
    assert rec.status == "ok" and rec.start_min == 7 * H and rec.earliest_limit is None and rec.latest is None


@pytest.mark.parametrize("duration", [30, 12 * H])
def test_start_is_never_negative_or_after_midnight(duration):
    rec = recommend_start(duration, sunrise=0, sunset=23 * H)
    assert 0 <= rec.start_min < 1440


import datetime
import json

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.light import LightPlugin
from day_plan.start import resolve_start, start_lines

JUNE = datetime.date(2026, 6, 21)


def _facts(route_dir, **transit):
    entry = {"markdown": "Bus 41.", "sources": ["https://www.crtm.es/horarios"], **transit}
    (route_dir / "facts.json").write_text(json.dumps({"all": {"transit": entry}}), encoding="utf-8")


def _ctx(make_route, fixed_now, weather_response, date=JUNE, **kwargs):
    http = kwargs.pop("http", lambda url: weather_response(date=date.isoformat()))
    route_dir = kwargs.pop("route_dir", None) or make_route(**{k: v for k, v in kwargs.items()
                                                               if k in ("duration_hours", "coords")})
    return route_dir, build_context(route_dir, date, http=http, now=fixed_now,
                                    start_time=kwargs.get("start_time"))


def test_without_facts_the_start_is_seven_oclock(make_route, fixed_now, weather_response):
    _, ctx = _ctx(make_route, fixed_now, weather_response)
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(7, 0) and ctx.start_source == "recommended"
    assert ctx.start_info.status == "ok" and ctx.start_info.missing == ["first_arrival", "last_departure"]


def test_a_start_given_by_the_user_wins_and_asks_nothing(make_route, fixed_now, weather_response):
    def http(url):
        raise AssertionError("the resolver must not touch the network when --start is given")

    _, ctx = _ctx(make_route, fixed_now, weather_response, http=http, start_time=datetime.time(9, 30))
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(9, 30) and ctx.start_source == "user"


def test_first_arrival_moves_the_start(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, first_arrival_local="09:10")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(9, 10) and ctx.start_info.earliest_limit == "first_arrival"


def test_a_last_departure_after_midnight_is_read_as_the_next_night(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, last_departure_local="00:20")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    assert ctx.start_info.latest_limit == "sunset" and ctx.start_time == datetime.time(7, 0)


def test_an_empty_window_gives_a_danger_warning(make_route, fixed_now, weather_response):
    route_dir = make_route(duration_hours=9.0)
    _facts(route_dir, first_arrival_local="16:00")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    lines, warnings = start_lines(ctx)
    assert ctx.start_info.status == "empty_window"
    assert [w.severity for w in warnings] == ["danger"] and "16:00" in warnings[0].text


def test_polar_night_gets_no_recommendation(make_route, fixed_now, weather_response):
    def http(url):
        raise AssertionError("no request expected")

    _, ctx = _ctx(make_route, fixed_now, weather_response, date=datetime.date(2026, 12, 21), http=http,
                  coords=((15.6, 78.2, 10.0), (15.7, 78.25, 20.0)))
    resolve_start(ctx)
    assert ctx.start_source == "none" and ctx.start_time is None


def test_a_weather_failure_still_gives_a_start(make_route, fixed_now, weather_response):
    def http(url):
        raise HttpError("boom")

    _, ctx = _ctx(make_route, fixed_now, weather_response, http=http)
    resolve_start(ctx)
    assert ctx.start_source == "recommended" and ctx.start_time is not None


def test_the_light_section_shows_the_recommendation(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, first_arrival_local="09:10", last_departure_local="23:30")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    section = LightPlugin().run(ctx, {"weather": {"utc_offset_seconds": 3600}})
    assert "Recommended start: **09:10**" in section.markdown
    assert "estimated finish 14:10" in section.markdown
    assert "Not recorded" not in section.markdown


def test_missing_transport_facts_are_said_when_there_are_access_points(make_route_with_points, fixed_now,
                                                                       weather_response):
    route_dir = make_route_with_points([("Cercedilla", "access", -3.75, 40.42, {"role": "start"})],
                                       duration_hours=4.0)
    ctx = build_context(route_dir, JUNE, http=lambda url: weather_response(utc_offset_seconds=7200), now=fixed_now)
    resolve_start(ctx)
    lines, _ = start_lines(ctx)
    assert any("Not recorded" in line for line in lines)
