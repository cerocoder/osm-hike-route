import datetime

import pytest

from day_plan.fire_index import (
    NESTEROV_DAYS, daily_from_hourly, fwi_class, history_range, kpo_class, nesterov_index,
)


@pytest.mark.parametrize("fwi,cls", [(0.0, "very_low"), (5.19, "very_low"), (5.2, "low"), (11.19, "low"), (11.2, "moderate"),
                                     (21.29, "moderate"), (21.3, "high"), (37.99, "high"), (38.0, "very_high"),
                                     (49.99, "very_high"), (50.0, "extreme"), (120.0, "extreme")])
def test_fwi_classes_follow_the_effis_thresholds(fwi, cls):
    assert fwi_class(fwi) == cls


@pytest.mark.parametrize("value,cls", [(0, 1), (300, 1), (300.5, 2), (1000, 2), (1001, 3), (4000, 3), (4001, 4), (10000, 4),
                                       (10001, 5), (50000, 5)])
def test_kpo_classes_follow_order_287(value, cls):
    assert kpo_class(value) == cls


def _day(date, t, dew, precip=0.0):
    return {"date": date, "t": t, "dew": dew, "precip": precip}


def test_the_index_accumulates_t_times_the_dew_point_deficit_on_dry_days():
    days = [_day("d1", 20.0, 10.0), _day("d2", 25.0, 15.0)]
    assert nesterov_index(days) == pytest.approx(20 * 10 + 25 * 10)


def test_more_than_three_millimetres_of_rain_resets_the_index_and_three_does_not():
    dry = [_day("d1", 20.0, 10.0), _day("d2", 20.0, 10.0)]
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.1)]) == 0.0
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.0)]) == pytest.approx(600.0)
    assert nesterov_index(dry + [_day("d3", 20.0, 10.0, precip=3.5), _day("d4", 10.0, 5.0)]) == pytest.approx(50.0)


def test_frost_days_add_nothing_and_a_dew_point_above_the_temperature_adds_nothing():
    assert nesterov_index([_day("d1", -3.0, -5.0), _day("d2", 0.0, -1.0)]) == 0.0
    assert nesterov_index([_day("d1", 10.0, 12.0)]) == 0.0


def _hourly(days, t=15.0, dew=5.0, rain_per_day=0.0):
    times, temp, dp, rain = [], [], [], []
    for d in days:
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            temp.append(t if h == 12 else t - 5)
            dp.append(dew if h == 12 else dew - 3)
            rain.append(rain_per_day / 24)
    return {"hourly": {"time": times, "temperature_2m": temp, "dew_point_2m": dp, "precipitation": rain}}


def test_daily_values_use_noon_and_the_whole_day_of_rain():
    days = daily_from_hourly(_hourly(["2026-09-01", "2026-09-02"], t=15.0, dew=5.0, rain_per_day=2.4))
    assert [d["date"] for d in days] == ["2026-09-01", "2026-09-02"]
    assert days[0]["t"] == 15.0 and days[0]["dew"] == 5.0 and days[0]["precip"] == pytest.approx(2.4)


def test_days_without_a_noon_value_or_with_missing_series_are_skipped():
    response = _hourly(["2026-09-01"])
    response["hourly"]["temperature_2m"][12] = None
    assert daily_from_hourly(response) == []
    bare = {"hourly": {"time": ["2026-09-01T12:00"]}}
    assert daily_from_hourly(bare) == []


def test_history_range_is_thirty_days_back():
    start, end = history_range(datetime.date(2026, 10, 3))
    assert (start, end) == (datetime.date(2026, 9, 3), datetime.date(2026, 10, 3)) and NESTEROV_DAYS == 30
