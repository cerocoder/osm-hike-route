import datetime

import pytest

from day_plan.sun import sun_times


def _hm(minutes):
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def test_london_summer_solstice_matches_published_times():
    s = sun_times(datetime.date(2026, 6, 21), 51.5074, -0.1278)
    assert s.kind == "normal"
    assert s.sunrise_utc_min == pytest.approx(3 * 60 + 43, abs=3)   # 04:43 BST
    assert s.sunset_utc_min == pytest.approx(20 * 60 + 21, abs=3)   # 21:21 BST


def test_london_winter_solstice_matches_published_times():
    s = sun_times(datetime.date(2026, 12, 21), 51.5074, -0.1278)
    assert s.sunrise_utc_min == pytest.approx(8 * 60 + 4, abs=3)
    assert s.sunset_utc_min == pytest.approx(15 * 60 + 53, abs=3)


def test_equator_equinox_day_is_about_twelve_hours_seven_minutes():
    s = sun_times(datetime.date(2026, 3, 20), 0.0, 0.0)
    assert s.sunset_utc_min - s.sunrise_utc_min == pytest.approx(12 * 60 + 7, abs=4)


def test_polar_day_and_night_above_the_arctic_circle():
    assert sun_times(datetime.date(2026, 6, 21), 69.65, 18.96).kind == "polar_day"
    assert sun_times(datetime.date(2026, 12, 21), 69.65, 18.96).kind == "polar_night"


def test_far_east_sunrise_is_on_the_previous_utc_day():
    # Kamchatka, UTC+12: local morning is the previous UTC evening.
    s = sun_times(datetime.date(2026, 6, 21), 53.0, 158.65)
    assert s.sunrise_utc_min < 0
    assert s.sunset_utc_min > 0


def test_southern_hemisphere_has_short_june_days():
    s = sun_times(datetime.date(2026, 6, 21), -33.87, 151.21)  # Sydney
    assert 9 * 60 + 30 < (s.sunset_utc_min - s.sunrise_utc_min) < 10 * 60 + 30
