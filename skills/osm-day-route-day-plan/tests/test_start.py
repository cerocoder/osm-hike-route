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
