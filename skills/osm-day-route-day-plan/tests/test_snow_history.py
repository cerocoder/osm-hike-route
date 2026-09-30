import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.snow_history import (
    FROST_WATCH_C, HISTORY_DAYS, SnowHistoryPlugin, day_range, history_url, parse_history,
)

TODAY = datetime.date(2026, 12, 18)            # fixed_now is 2026-06-20; the tests build their own clock below
DATE = datetime.date(2026, 12, 20)


def response(date, snow_m=0.3, temp=-5.0, elevation=250.0):
    start = date - datetime.timedelta(days=HISTORY_DAYS)
    times = [f"{start + datetime.timedelta(days=d):%Y-%m-%d}T{h:02d}:00" for d in range(HISTORY_DAYS + 1) for h in range(24)]
    n = len(times)
    return {"elevation": elevation, "hourly": {
        "time": times, "temperature_2m": [temp] * n, "dew_point_2m": [temp - 2] * n, "precipitation": [0.1] * n,
        "rain": [0.0] * n, "snowfall": [0.05] * n, "snow_depth": [snow_m] * n, "cloud_cover": [50] * n,
        "weather_code": [71] * n}}


def make_ctx(tmp_path, now, date=DATE, folder="route", coords=None):
    route_dir = tmp_path / folder
    route_dir.mkdir()
    coords = coords or [[60.6, 56.84, 250.0], [60.61, 56.85, 255.0]]
    line = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"name": "T", "mode": "walk"}}
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [line]}),
                                             encoding="utf-8")
    return route_dir


@pytest.fixture
def now():
    return datetime.datetime(2026, 12, 18, 12, 0, tzinfo=datetime.timezone.utc)


def run(tmp_path, now, http, weather=None, date=DATE, folder="route", coords=None):
    ctx = build_context(make_ctx(tmp_path, now, date, folder, coords), date, http=http, now=now)
    shared = {"weather": weather if weather is not None else {"source": "forecast", "rows": [{"temp": -5.0, "snow_m": 0.3}]}}
    return SnowHistoryPlugin().run(ctx, shared), ctx


def test_the_answer_is_parsed_with_depths_in_centimetres_and_the_date_located(now):
    rows = parse_history(response(DATE, snow_m=0.25))
    assert len(rows) == 24 * (HISTORY_DAYS + 1)
    assert rows[0]["date"] == "2026-12-06" and rows[0]["hour"] == 0 and rows[1]["hour"] == 1
    assert rows[0]["snow_cm"] == pytest.approx(25.0) and rows[0]["snowfall"] == 0.05 and rows[0]["code"] == 71
    assert day_range(rows, DATE) == (24 * HISTORY_DAYS, 24 * (HISTORY_DAYS + 1) - 1)
    assert day_range(rows, datetime.date(2030, 1, 1)) is None


def test_a_missing_variable_is_none_and_zero_depth_stays_zero():
    data = response(DATE, snow_m=0.0)
    del data["hourly"]["dew_point_2m"]
    data["hourly"]["snow_depth"][0] = None
    rows = parse_history(data)
    assert rows[0]["dew"] is None and rows[0]["snow_cm"] is None and rows[1]["snow_cm"] == 0.0


def test_the_url_asks_for_fourteen_days_and_the_needed_variables():
    url = history_url("https://api.open-meteo.com/v1/forecast", 56.84, 60.6, DATE)
    assert "start_date=2026-12-06&end_date=2026-12-20" in url and "latitude=56.8400" in url
    for name in ("temperature_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "snow_depth", "cloud_cover",
                 "weather_code"):
        assert name in url


def test_the_plugin_shares_the_rows_and_adds_nothing_to_the_plan(tmp_path, now):
    calls = []
    section, _ = run(tmp_path, now, lambda url: calls.append(url) or response(DATE))
    assert section.omit is True and section.markdown == "" and section.section_id == "hazards"
    data = section.shared
    assert len(data["rows"]) == 24 * 15 and data["elevation_m"] == 250.0 and data["error"] is None
    assert data["day_start"] == 24 * 14 and data["day_end"] == 24 * 15 - 1 and data["source"] == "forecast"
    assert len(calls) == 1 and "api.open-meteo.com" in calls[0]


def test_a_past_date_uses_the_archive(tmp_path, now):
    calls = []
    run(tmp_path, now, lambda url: calls.append(url) or response(datetime.date(2026, 1, 15)),
        weather={"source": "archive", "rows": [{"temp": -5.0, "snow_m": 0.3}]}, date=datetime.date(2026, 1, 15))
    assert "archive-api.open-meteo.com" in calls[0]


def test_the_answer_is_cached_and_the_cache_is_used(tmp_path, now):
    calls = []
    http = lambda url: calls.append(url) or response(DATE)  # noqa: E731
    first, ctx = run(tmp_path, now, http)
    second = SnowHistoryPlugin().run(ctx, {"weather": {"source": "forecast", "rows": [{"temp": -5.0}]}})
    assert len(calls) == 1 and second.shared["rows"] == first.shared["rows"] and second.shared["day_start"] == 24 * 14


def test_nothing_is_fetched_beyond_the_forecast_horizon(tmp_path, now):
    calls = []
    section, _ = run(tmp_path, now, lambda url: calls.append(url) or {}, weather={"source": "climate", "rows": []},
                     date=datetime.date(2027, 3, 1))
    assert calls == [] and section.shared["rows"] == [] and section.shared["source"] == "climate"


def test_nothing_is_fetched_in_summer_unless_the_weather_shows_snow_or_frost(tmp_path, now):
    summer = datetime.date(2026, 7, 10)
    calls = []
    http = lambda url: calls.append(url) or response(summer, snow_m=0.0, temp=15.0)  # noqa: E731
    warm = {"source": "forecast", "rows": [{"temp": 15.0, "snow_m": 0.0}]}
    section, _ = run(tmp_path, now, http, weather=warm, date=summer, folder="warm")
    assert calls == [] and section.shared["skipped"] is True and section.shared["rows"] == []
    frost = {"source": "forecast", "rows": [{"temp": FROST_WATCH_C, "snow_m": 0.0}]}
    run(tmp_path, now, http, weather=frost, date=summer, folder="frost")
    assert len(calls) == 1
    snow = {"source": "forecast", "rows": [{"temp": 15.0, "snow_m": 0.02}]}
    run(tmp_path, now, http, weather=snow, date=summer, folder="snow")
    assert len(calls) == 2
    high = [[60.6, 56.84, 2300.0], [60.61, 56.85, 2350.0]]
    run(tmp_path, now, http, weather=warm, date=summer, folder="high", coords=high)
    assert len(calls) == 3                                            # a route reaching 2 000 m is always watched


@pytest.mark.parametrize("failure", [HttpError("HTTP Error 503"), KeyError("hourly"), ValueError("bad")])
def test_a_failing_fetch_is_reported_and_never_raised_or_cached(tmp_path, now, failure):
    def http(url):
        raise failure
    section, ctx = run(tmp_path, now, http)
    assert section.omit is True and section.shared["rows"] == [] and section.shared["error"]
    calls = []
    SnowHistoryPlugin().run(ctx, {"weather": {"source": "forecast", "rows": [{"temp": -5.0}]}})
    assert ctx.cache.get_entry(f"snow_history|forecast|56.845|60.605|{DATE.isoformat()}") is None


def test_an_answer_without_the_plan_date_is_an_error(tmp_path, now):
    section, _ = run(tmp_path, now, lambda url: response(datetime.date(2026, 11, 1)))
    assert section.shared["rows"] == [] and "plan date" in section.shared["error"]
