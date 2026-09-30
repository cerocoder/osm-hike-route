import pytest

from day_plan.snowmodel import (
    GLAZE_CODES, applies, depth_series, ice_levels, in_cold_season, simulate, temp_at, window_conditions,
)


def rows_of(n, **columns):
    """n hourly rows starting at local midnight; each keyword is a scalar (all hours) or a {hour_index: value} dict."""
    base = {"temp": 5.0, "dew": 0.0, "precip": 0.0, "rain": 0.0, "snowfall": 0.0, "snow_cm": 0.0, "cloud": 80, "code": 3}
    rows = []
    for i in range(n):
        row = {"hour": i % 24}
        for key, default in base.items():
            spec = columns.get(key, default)
            row[key] = spec.get(i, default) if isinstance(spec, dict) else spec
        rows.append(row)
    return rows


def night(hour):
    return hour is not None and (hour < 7 or hour >= 19)


def test_temperature_falls_with_height_and_is_unchanged_without_elevations():
    assert temp_at(0.0, 500.0, 1500.0) == pytest.approx(-6.5)
    assert temp_at(0.0, 1500.0, 500.0) == pytest.approx(6.5)
    assert temp_at(3.0, None, 500.0) == 3.0 and temp_at(3.0, 500.0, None) == 3.0 and temp_at(None, 1, 2) is None


def test_snow_accumulates_when_cold_melts_when_warm_and_never_goes_below_zero():
    cold = rows_of(10, temp=-5.0, snowfall=1.0)
    assert simulate(cold, 500.0, 500.0, 0, 9)[-1] == pytest.approx(10.0)
    thaw = rows_of(34, temp={**{i: -5.0 for i in range(10)}, **{i: 5.0 for i in range(10, 34)}},
                   snowfall={i: 1.0 for i in range(10)})
    depth = simulate(thaw, 500.0, 500.0, 0, 33)
    assert depth[9] == pytest.approx(10.0) and depth[-1] == pytest.approx(10.0 - 1.5 * 5.0)          # 7.5 cm a day at +5
    assert simulate(rows_of(120, temp=10.0, snowfall=0.0), 500.0, 500.0, 0, 119)[-1] == 0.0


def test_rain_that_is_snow_at_the_higher_level_accumulates_there_only():
    rows = rows_of(6, temp=3.0, rain=2.0, precip=2.0)
    low = simulate(rows, 500.0, 500.0, 0, 5)
    high = simulate(rows, 500.0, 1000.0, 0, 5)               # 3.25 degrees colder: -0.25 C
    assert low[-1] == 0.0 and high[-1] == pytest.approx(6 * 2.0)       # 1 cm of snow per mm of water, no melt below 0


def test_rain_on_snow_melts_it():
    rows = rows_of(2, temp=5.0, rain=10.0, snow_cm=0.0)
    assert simulate(rows, 500.0, 500.0, 0, 1)[-1] == 0.0
    deep = rows_of(12, temp={0: -5.0, 1: -5.0, **{i: 5.0 for i in range(2, 12)}}, snowfall={0: 20.0, 1: 20.0},
                   rain={i: 1.0 for i in range(2, 12)})
    assert simulate(deep, 500.0, 500.0, 0, 11)[-1] == pytest.approx(40.0 - 10 * (1.5 * 5.0 / 24 + 0.3))


def test_the_depth_at_the_model_level_is_the_model_depth():
    rows = rows_of(48, snow_cm=12.0, temp=-2.0, snowfall=0.1)
    assert depth_series(rows, 500.0, 500.0, 24, 47) == pytest.approx([12.0] * 24)


def test_a_higher_level_holds_more_snow_than_the_model_and_a_lower_one_less_but_never_below_zero():
    # model level +1.5 C (no accumulation there), the level 1000 m higher is -5 C (the model's snowfall sticks)
    rows = rows_of(14 * 24, temp=1.5, snowfall=0.3, snow_cm=5.0)
    high = depth_series(rows, 500.0, 1500.0, 13 * 24, 14 * 24 - 1)
    assert high[-1] > 5.0 + 10.0
    # the model is cold and snowy but reports no snow; a level 1500 m lower is warm: the correction must not go negative
    snowy = rows_of(14 * 24, temp=-5.0, snowfall=1.0, snow_cm=0.0)
    low = depth_series(snowy, 500.0, -1000.0, 13 * 24, 14 * 24 - 1)
    assert low == [0.0] * 24


def test_the_model_depth_is_kept_when_there_is_no_history_before_the_date():
    rows = rows_of(24, snow_cm=7.0, temp=-3.0)
    assert depth_series(rows, 500.0, 500.0, 0, 23) == [7.0] * 24


def test_freezing_rain_glazes_everything_for_six_hours():
    rows = rows_of(48, temp=-1.0, code={30: 66})
    depth = [0.0] * 24
    cleared, uncleared = ice_levels(rows, 500.0, 500.0, depth, 24, 47, night)
    assert 66 in GLAZE_CODES
    assert cleared[5] == "none" and cleared[6] == "high" and cleared[12] == "high" and cleared[13] == "none"
    assert uncleared[6] == "high" and uncleared[13] == "none"


def test_refreezing_after_wet_weather_is_high_on_cleared_and_moderate_on_uncleared_surfaces():
    rows = rows_of(48, temp={**{i: 3.0 for i in range(0, 30)}, **{i: -2.0 for i in range(30, 48)}},
                   precip={i: 1.0 for i in range(20, 30)})
    cleared, uncleared = ice_levels(rows, 500.0, 500.0, [0.0] * 24, 24, 47, night)
    k = 30 - 24
    assert cleared[k] == "high" and uncleared[k] == "moderate"
    assert cleared[23] == "none"              # 12+ hours after the thaw and the rain: the window of memory is over


def test_frost_after_a_dry_warm_spell_without_snow_is_not_a_refreeze():
    rows = rows_of(48, temp={**{i: 3.0 for i in range(0, 30)}, **{i: -2.0 for i in range(30, 48)}}, cloud=90)
    cleared, uncleared = ice_levels(rows, 500.0, 500.0, [0.0] * 24, 24, 47, night)
    assert set(cleared) == {"none"} and set(uncleared) == {"none"}


def test_a_refreeze_with_snow_on_the_ground_counts_even_without_fresh_rain():
    rows = rows_of(48, temp={**{i: 3.0 for i in range(0, 30)}, **{i: -2.0 for i in range(30, 48)}}, cloud=90)
    cleared, uncleared = ice_levels(rows, 500.0, 500.0, [4.0] * 24, 24, 47, night)
    assert cleared[6] == "high" and uncleared[6] == "moderate"


def test_black_ice_needs_frost_a_small_dew_point_spread_a_clear_sky_and_the_night():
    rows = rows_of(48, temp=-1.0, dew=-1.5, cloud=10)
    cleared, uncleared = ice_levels(rows, 500.0, 500.0, [0.0] * 24, 24, 47, night)
    assert cleared[2] == "moderate" and uncleared[2] == "none"            # 02:00
    assert cleared[12] == "none"                                          # noon: not dark
    cloudy = ice_levels(rows_of(48, temp=-1.0, dew=-1.5, cloud=80), 500.0, 500.0, [0.0] * 24, 24, 47, night)[0]
    dry = ice_levels(rows_of(48, temp=-1.0, dew=-9.0, cloud=10), 500.0, 500.0, [0.0] * 24, 24, 47, night)[0]
    warm = ice_levels(rows_of(48, temp=2.0, dew=1.5, cloud=10), 500.0, 500.0, [0.0] * 24, 24, 47, night)[0]
    assert set(cloudy) == set(dry) == set(warm) == {"none"}


def test_ice_is_judged_at_the_temperature_of_the_level():
    rows = rows_of(48, temp=1.0, dew=-0.5, cloud=10)                      # +1 C at the model level: no frost there
    at_model = ice_levels(rows, 500.0, 500.0, [0.0] * 24, 24, 47, night)[0]
    higher = ice_levels(rows, 500.0, 1000.0, [0.0] * 24, 24, 47, night)[0]     # -2.25 C at 500 m higher
    assert set(at_model) == {"none"} and higher[2] == "moderate"


def test_window_conditions_take_the_worst_values_in_the_window():
    rows = rows_of(48, temp={**{i: 3.0 for i in range(0, 30)}, **{i: -2.0 for i in range(30, 48)}},
                   precip={i: 1.0 for i in range(20, 30)}, snow_cm={i: (3.0 if i >= 24 else 0.0) for i in range(48)})
    snow, ice_unc, ice_clr, slush = window_conditions(rows, 500.0, 500.0, 24, 47, [2, 3, 4, 5, 6, 7, 8], night)
    assert snow == pytest.approx(3.0) and ice_clr == "high" and ice_unc == "moderate"
    assert slush is True                       # the thaw still lasts in hours 2-5 while 3 cm of snow lie
    _, _, _, slush = window_conditions(rows, 500.0, 500.0, 24, 47, [8, 9, 10], night)
    assert slush is False                      # frost in hours 8-10
    _, _, _, slush = window_conditions(rows_of(48, temp=2.0, snow_cm=4.0), 500.0, 500.0, 24, 47, [10, 11], night)
    assert slush is True
    assert window_conditions(rows, 500.0, 500.0, 24, 47, [], night) == (0.0, "none", "none", False)


def test_the_assessment_applies_to_lying_snow_recent_snowfall_or_frost_and_not_to_a_warm_bare_day():
    warm = rows_of(15 * 24, temp=15.0)
    last = 15 * 24 - 1
    day = 14 * 24
    window = list(range(8, 18))
    assert applies(warm, 500.0, [500.0], day, last, window) is False
    snowy = rows_of(15 * 24, temp=8.0, snow_cm=2.0)
    assert applies(snowy, 500.0, [500.0], day, last, window) is True
    fell = rows_of(15 * 24, temp={**{i: 8.0 for i in range(15 * 24)}, **{day - 40: -2.0}}, snowfall={day - 40: 1.0})
    assert applies(fell, 500.0, [500.0], day, last, window) is True
    frosty_night = rows_of(15 * 24, temp={**{i: 10.0 for i in range(15 * 24)}, **{day - 3: 1.5}})
    assert applies(frosty_night, 500.0, [500.0], day, last, window) is True
    old_snowfall = rows_of(15 * 24, temp=10.0, snowfall={day - 100: 2.0})
    assert applies(old_snowfall, 500.0, [500.0], day, last, window) is False      # more than 72 hours ago and it is warm
    assert applies(warm, 500.0, [500.0], day, last, []) is False


def test_a_higher_leg_can_make_the_assessment_apply_where_the_valley_would_not():
    rows = rows_of(15 * 24, temp=7.0)
    day, last, window = 14 * 24, 15 * 24 - 1, list(range(8, 18))
    assert applies(rows, 500.0, [500.0], day, last, window) is False
    assert applies(rows, 500.0, [500.0, 1500.0], day, last, window) is True       # 0.5 C at 1500 m


@pytest.mark.parametrize("month, lat, top, expected", [
    (7, 56.0, 300.0, False), (10, 56.0, 300.0, True), (1, 56.0, 300.0, True), (4, 56.0, 300.0, True),
    (5, 56.0, 300.0, False), (9, 56.0, 300.0, False), (7, 43.0, 2300.0, True), (7, -33.0, 300.0, True),
    (1, -33.0, 300.0, False), (4, -33.0, 300.0, True), (11, -33.0, 300.0, False),
])
def test_cold_season(month, lat, top, expected):
    assert in_cold_season(month, lat, top) is expected
