import datetime

import pytest

import day_plan.plugins.weather as weather
from day_plan.context import build_context
from day_plan.plugins.weather import WeatherPlugin, average_rows, parse_hourly

NEW_VARS = ("relative_humidity_2m", "dew_point_2m", "freezing_level_height", "cape")


def _ctx(make_route, fixed_now, http, date=datetime.date(2026, 6, 21), folder="route"):
    return build_context(make_route(folder=folder), date, http=http, now=fixed_now)


def _response(weather_response, **extra):
    response = weather_response(**extra)
    response["hourly"]["relative_humidity_2m"] = [55] * 24
    response["hourly"]["dew_point_2m"] = [8.0] * 24
    response["hourly"]["freezing_level_height"] = [2500.0 + h for h in range(24)]
    response["hourly"]["cape"] = [h * 10.0 for h in range(24)]
    response["elevation"] = 640.0
    return response


def test_the_forecast_request_asks_for_humidity_dew_point_freezing_level_and_cape(make_route, fixed_now, weather_response):
    urls = []
    WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: urls.append(u) or _response(weather_response)), {})
    for name in NEW_VARS:
        assert name in urls[0]


def test_the_archive_request_leaves_out_what_the_archive_does_not_have(make_route, fixed_now, weather_response):
    urls = []
    ctx = _ctx(make_route, fixed_now, lambda u: urls.append(u) or _response(weather_response, date="2026-01-10"),
               date=datetime.date(2026, 1, 10))
    WeatherPlugin().run(ctx, {})
    assert "archive-api" in urls[0]
    assert "relative_humidity_2m" in urls[0] and "dew_point_2m" in urls[0]
    assert "freezing_level_height" not in urls[0] and "cape" not in urls[0]


def test_rows_carry_the_new_values_and_tolerate_their_absence(weather_response):
    rows = parse_hourly(_response(weather_response))
    assert (rows[12]["rh"], rows[12]["dew"], rows[12]["fzl"], rows[12]["cape"]) == (55, 8.0, 2512.0, 120.0)
    bare = parse_hourly(weather_response())
    assert bare[12]["rh"] is None and bare[12]["fzl"] is None and bare[12]["cape"] is None


def test_the_climatology_averages_the_new_values(weather_response):
    a = parse_hourly(_response(weather_response))
    b = parse_hourly(_response(weather_response))
    for row in b:
        row["fzl"] = (row["fzl"] or 0) + 100.0
        row["rh"] = 45
    mean = average_rows([a, b])
    assert mean[12]["fzl"] == pytest.approx(2562.0) and mean[12]["rh"] == pytest.approx(50.0)


def test_the_model_elevation_is_shared_for_the_mountain_plugin(make_route, fixed_now, weather_response):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: _response(weather_response)), {})
    assert section.shared["elevation_m"] == 640.0
    no_elevation = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda u: weather_response(), folder="second"), {})
    assert no_elevation.shared["elevation_m"] is None


def test_a_cache_entry_written_before_the_new_variables_is_not_reused(make_route, fixed_now, weather_response):
    calls = []
    ctx = _ctx(make_route, fixed_now, lambda u: calls.append(u) or _response(weather_response))
    lat, lon = ctx.centroid
    old_key = f"weather|forecast|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
    ctx.cache.put(old_key, {"rows": parse_hourly(weather_response()), "utc_offset_seconds": 3600})
    section = WeatherPlugin().run(ctx, {})
    assert len(calls) == 1                                  # the stale entry (no freezing level) was ignored
    assert section.shared["rows"][12]["fzl"] is not None


def test_changing_the_variable_set_changes_the_cache_key(make_route, fixed_now, weather_response, monkeypatch):
    calls = []
    ctx = _ctx(make_route, fixed_now, lambda u: calls.append(u) or _response(weather_response))
    WeatherPlugin().run(ctx, {})
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 1
    monkeypatch.setattr(weather, "FORECAST_VARS", weather.FORECAST_VARS + ("uv_index",))
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 2 and "uv_index" in calls[1]
