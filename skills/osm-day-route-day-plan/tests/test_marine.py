import datetime
import math

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.marine import fetch_marine_day, find_sea_day, mean_sst, sea_temperature, tide_extrema

DATE = datetime.date(2026, 6, 21)


def _day(sst=21.0, level=None):
    level = level if level is not None else [round(1.5 * math.sin(2 * math.pi * (h - 3) / 12.42), 3) for h in range(24)]
    return {"hourly": {"time": [f"2026-06-21T{h:02d}:00" for h in range(24)],
                       "sea_surface_temperature": [sst] * 24, "sea_level_height_msl": level}}


def _ctx(make_route, fixed_now, http):
    return build_context(make_route(), DATE, http=http, now=fixed_now)


def test_tide_extrema_finds_highs_and_lows_with_sub_hour_times():
    levels = [1.5 * math.sin(2 * math.pi * (h - 3) / 12.42) for h in range(24)]
    events = tide_extrema(levels)
    kinds = [e[0] for e in events]
    assert kinds[:2] == ["high", "low"] and abs(events[0][1] - (3 + 12.42 / 4)) < 0.3
    assert abs(events[0][2] - 1.5) < 0.05 and abs(events[1][2] + 1.5) < 0.05


def test_tide_extrema_ignores_gaps_and_flat_series():
    assert tide_extrema([0.0] * 24) == []
    assert tide_extrema([None, 1.0, None, 2.0]) == []


def test_fetch_is_cached_and_reads_the_marine_api(make_route, fixed_now):
    urls = []

    def http(url):
        urls.append(url)
        return _day()

    ctx = _ctx(make_route, fixed_now, http)
    day = fetch_marine_day(ctx, 43.5, -3.5, DATE)
    fetch_marine_day(ctx, 43.5, -3.5, DATE)
    assert len(urls) == 1 and urls[0].startswith("https://marine-api.open-meteo.com/v1/marine?")
    assert "sea_surface_temperature,sea_level_height_msl" in urls[0] and "start_date=2026-06-21" in urls[0]
    assert mean_sst(day) == 21.0


def test_a_land_cell_falls_back_to_a_neighbouring_grid_point(make_route, fixed_now):
    seen = []

    def http(url):
        seen.append(url)
        return _day(sst=None) if len(seen) == 1 else _day(sst=19.5)

    found = find_sea_day(_ctx(make_route, fixed_now, http), 43.5, -3.5, DATE)
    assert found is not None and mean_sst(found[0]) == 19.5 and len(seen) == 2


def test_a_service_error_gives_nothing_without_hammering(make_route, fixed_now):
    seen = []

    def http(url):
        seen.append(url)
        raise HttpError("400")

    assert find_sea_day(_ctx(make_route, fixed_now, http), 43.5, -3.5, DATE) is None and len(seen) == 1


def test_beyond_the_horizon_the_temperature_is_a_climatology(make_route, fixed_now):
    def http(url):
        if "2026-06-21" in url:
            raise HttpError("400")
        return _day(sst=20.0)

    result = sea_temperature(_ctx(make_route, fixed_now, http), 43.5, -3.5)
    assert result["kind"] == "climatology" and result["temp"] == 20.0 and result["day"] is None


def test_everything_failing_is_none(make_route, fixed_now):
    def http(url):
        raise HttpError("500")

    assert sea_temperature(_ctx(make_route, fixed_now, http), 43.5, -3.5) is None
