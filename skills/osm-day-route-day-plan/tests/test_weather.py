import datetime

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.weather import (
    WeatherPlugin, average_rows, choose_source, daytime_rows, parse_hourly, render_table, utc_offset_for,
    warnings_for,
)

TODAY = datetime.date(2026, 6, 20)


def _ctx(make_route, fixed_now, http, date=datetime.date(2026, 6, 21), lang="en"):
    return build_context(make_route(), date, lang=lang, http=http, now=fixed_now)


def test_choose_source_boundaries():
    assert choose_source(TODAY + datetime.timedelta(days=15), TODAY) == "forecast"
    assert choose_source(TODAY + datetime.timedelta(days=16), TODAY) == "climate"
    assert choose_source(TODAY - datetime.timedelta(days=92), TODAY) == "forecast"
    assert choose_source(TODAY - datetime.timedelta(days=93), TODAY) == "archive"


def test_parse_hourly_maps_variables_and_tolerates_missing_ones(weather_response):
    response = weather_response()
    del response["hourly"]["visibility"]
    rows = parse_hourly(response)
    assert len(rows) == 24
    assert rows[5]["hour"] == 5
    assert rows[5]["temp"] == 18.0
    assert rows[5]["vis_m"] is None
    assert rows[5]["wdir"] == 270


def test_forecast_request_uses_forecast_api_with_ms_and_single_date(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        return weather_response()

    section = WeatherPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert len(urls) == 1
    assert urls[0].startswith("https://api.open-meteo.com/v1/forecast?")
    assert "wind_speed_unit=ms" in urls[0]
    assert "start_date=2026-06-21&end_date=2026-06-21" in urls[0]
    assert "timezone=auto" in urls[0]
    assert section.confidence == "derived"
    assert section.shared["source"] == "forecast"
    assert section.shared["utc_offset_seconds"] == 3600


def test_old_date_uses_archive_api(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        return weather_response(date="2026-01-10")

    ctx = _ctx(make_route, fixed_now, http, date=datetime.date(2026, 1, 10))
    # today is 2026-06-20, so 2026-01-10 is 161 days back -> archive
    section = WeatherPlugin().run(ctx, {})
    assert urls[0].startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "precipitation_probability" not in urls[0]
    assert "Historical archive" in section.markdown or "historical archive" in section.markdown


def test_far_future_uses_climatology_of_five_previous_years(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        year = url.split("start_date=")[1][:4]
        return weather_response(date=f"{year}-08-15", temperature_2m=float(int(year) - 2000))

    ctx = _ctx(make_route, fixed_now, http, date=datetime.date(2026, 8, 15))
    section = WeatherPlugin().run(ctx, {})
    assert len(urls) == 5
    assert all("archive-api" in u for u in urls)
    assert sorted(u.split("start_date=")[1][:4] for u in urls) == ["2021", "2022", "2023", "2024", "2025"]
    assert section.shared["source"] == "climate"
    assert "not a forecast" in section.markdown
    assert any("climatology" in w.text for w in section.warnings)
    assert section.shared["rows"][12]["temp"] == pytest.approx(23.0)  # mean of 21..25


def test_climatology_of_feb_29_uses_feb_28_in_non_leap_years(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        year = url.split("start_date=")[1][:4]
        return weather_response(date=f"{year}-02-28")

    ctx = build_context(make_route(), datetime.date(2028, 2, 29), http=http,
                        now=datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    WeatherPlugin().run(ctx, {})
    assert all("2-28" in u for u in urls if "start_date=2025" in u or "start_date=2022" in u)


def test_forecast_is_cached_for_three_hours(make_route, fixed_now, weather_response):
    calls = []

    def http(url):
        calls.append(url)
        return weather_response()

    ctx = _ctx(make_route, fixed_now, http)
    WeatherPlugin().run(ctx, {})
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 1


def test_http_failure_gives_no_data_section_not_an_exception(make_route, fixed_now):
    def http(url):
        raise HttpError("timeout")

    section = WeatherPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert section.confidence == "no-data"
    assert "timeout" in section.markdown
    assert section.shared == {}


def test_malformed_response_gives_no_data_section(make_route, fixed_now):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda url: {"unexpected": True}), {})
    assert section.confidence == "no-data"


def test_daytime_rows_follow_sunrise_and_sunset(weather_response):
    rows = parse_hourly(weather_response())
    day = daytime_rows(rows, datetime.date(2026, 6, 21), 51.5, -0.13, 3600)
    hours = [r["hour"] for r in day]
    assert hours[0] == 4 and hours[-1] == 21   # sunrise 04:43, sunset 21:21 local


def test_daytime_rows_polar_night_shows_a_midday_window(weather_response):
    rows = parse_hourly(weather_response(date="2026-12-21"))
    day = daytime_rows(rows, datetime.date(2026, 12, 21), 69.65, 18.96, 3600)
    assert [r["hour"] for r in day] == list(range(9, 16))


def test_table_has_wind_direction_from_gusts_and_snow(weather_response):
    rows = parse_hourly(weather_response(wind_direction_10m=270, snow_depth=0.12, wind_speed_10m=4.2))
    table = render_table(rows[10:11], "en")
    assert "4.2 W (270°)" in table
    assert "| 12 |" in table          # snow depth 0.12 m -> 12 cm
    assert table.splitlines()[0].startswith("| Time |")


def test_table_shows_dash_for_missing_values(weather_response):
    response = weather_response()
    response["hourly"]["visibility"] = [None] * 24
    rows = parse_hourly(response)
    assert "–" in render_table(rows[10:11], "en")


def test_precipitation_probability_is_shown_in_parentheses(weather_response):
    rows = parse_hourly(weather_response(precipitation=1.5, precipitation_probability=80))
    assert "1.5 (80)" in render_table(rows[10:11], "en")


def test_thunderstorm_is_danger(weather_response):
    rows = parse_hourly(weather_response(weather_code={14: 95}))
    warnings = warnings_for(rows, "en", "forecast")
    assert ("danger", True) in [(w.severity, "Thunderstorms" in w.text) for w in warnings]


def test_fog_by_code_or_by_visibility(weather_response):
    by_code = warnings_for(parse_hourly(weather_response(weather_code={7: 45})), "en", "forecast")
    by_vis = warnings_for(parse_hourly(weather_response(visibility={7: 400.0})), "en", "forecast")
    assert any("Fog" in w.text for w in by_code)
    assert any("Fog" in w.text for w in by_vis)


def test_gust_severity_levels(weather_response):
    caution = warnings_for(parse_hourly(weather_response(wind_gusts_10m={12: 12.0})), "en", "forecast")
    danger = warnings_for(parse_hourly(weather_response(wind_gusts_10m={12: 20.0})), "en", "forecast")
    assert [w.severity for w in caution if "Gusts" in w.text] == ["caution"]
    assert [w.severity for w in danger if "Gusts" in w.text] == ["danger"]


def test_cold_and_heat(weather_response):
    cold = warnings_for(parse_hourly(weather_response(apparent_temperature=-27.0)), "en", "forecast")
    heat = warnings_for(parse_hourly(weather_response(apparent_temperature={14: 33.0})), "en", "forecast")
    assert any(w.severity == "danger" and "hypothermia" in w.text for w in cold)
    assert any(w.severity == "caution" and "water" in w.text for w in heat)


def test_snow_cover_is_reported_from_snow_depth(weather_response):
    warnings = warnings_for(parse_hourly(weather_response(snow_depth=0.2)), "en", "forecast")
    assert any("Snow cover of about 20 cm" in w.text for w in warnings)


def test_calm_clear_day_has_no_warnings(weather_response):
    assert warnings_for(parse_hourly(weather_response()), "en", "forecast") == []


def test_average_rows_uses_circular_mean_for_wind_direction(weather_response):
    a = parse_hourly(weather_response(wind_direction_10m=350))
    b = parse_hourly(weather_response(wind_direction_10m=10))
    mean = average_rows([a, b])
    assert mean[0]["wdir"] == pytest.approx(0.0, abs=0.5) or mean[0]["wdir"] == pytest.approx(360.0, abs=0.5)


def test_russian_table_headers_and_source_note(make_route, fixed_now, weather_response):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda url: weather_response(), lang="ru"), {})
    assert section.markdown.splitlines()[0].startswith("| Время |")
    assert "Open-Meteo" in section.markdown


def test_utc_offset_comes_from_the_zone_name_for_the_requested_date(weather_response):
    # Open-Meteo reports the offset of the moment of the request; a January
    # date in London must be UTC+0 even if the response says +3600.
    january = weather_response(date="2024-01-10", utc_offset_seconds=3600, timezone="Europe/London")
    june = weather_response(date="2024-06-21", utc_offset_seconds=0, timezone="Europe/London")
    assert utc_offset_for(january, datetime.date(2024, 1, 10)) == 0
    assert utc_offset_for(june, datetime.date(2024, 6, 21)) == 3600


def test_utc_offset_falls_back_to_the_reported_value(weather_response):
    assert utc_offset_for(weather_response(utc_offset_seconds=7200), datetime.date(2026, 6, 21)) == 7200
    bad_zone = weather_response(utc_offset_seconds=7200, timezone="Not/AZone")
    assert utc_offset_for(bad_zone, datetime.date(2026, 6, 21)) == 7200


def test_wind_speed_without_direction_still_renders(weather_response):
    response = weather_response()
    response["hourly"]["wind_direction_10m"] = [None] * 24
    assert "| 3.0 |" in render_table(parse_hourly(response)[10:11], "en")


def test_dst_day_with_twenty_three_hourly_rows_does_not_crash(make_route, fixed_now, weather_response):
    response = weather_response(date="2026-03-29")
    for series in response["hourly"].values():
        if isinstance(series, list):
            del series[3]   # spring-forward day: the local 03:00 hour does not exist
    section = WeatherPlugin().run(
        _ctx(make_route, fixed_now, lambda url: response, date=datetime.date(2026, 3, 29)), {})
    assert section.confidence == "derived"
    assert len(section.shared["rows"]) == 23
