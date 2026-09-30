import datetime
import json
from pathlib import Path

import pytest

from day_plan.opening_hours import (
    OpeningResult, evaluate, format_intervals, latest_close, open_at,
)

SAT = datetime.date(2026, 6, 27)   # a Saturday
SUN = datetime.date(2026, 6, 28)
MON = datetime.date(2026, 6, 29)
WED = datetime.date(2026, 7, 1)
HERE = Path(__file__).parent


def hm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def test_simple_weekday_rules_and_later_rule_wins():
    spec = "Mo-Fr 09:00-18:00; Sa 10:00-14:00; Su off"
    assert evaluate(spec, WED).intervals == [(hm("09:00"), hm("18:00"))]
    assert evaluate(spec, SAT).intervals == [(hm("10:00"), hm("14:00"))]
    assert evaluate(spec, SUN).status == "closed"
    override = evaluate("Mo-Fr 09:00-18:00; We off", WED)
    assert override.status == "closed"


def test_several_time_ranges_in_one_rule():
    result = evaluate("Mo-Th 08:00-14:00,15:00-17:00; Fr 08:00-15:00", WED)
    assert result.intervals == [(hm("08:00"), hm("14:00")), (hm("15:00"), hm("17:00"))]
    assert format_intervals(result.intervals) == "08:00–14:00, 15:00–17:00"


def test_comma_before_a_new_weekday_selector_starts_a_new_rule():
    spec = "Su-Th 12:30-24:00, Fr,Sa 12:30-00:30"      # real Madrid string
    assert evaluate(spec, WED).intervals == [(hm("12:30"), 1440)]
    sat = evaluate(spec, SAT)                            # Friday's late close spills into Saturday morning
    assert sat.intervals == [(0, hm("00:30")), (hm("12:30"), 1440 + hm("00:30"))]
    assert format_intervals(sat.intervals) == "00:00–00:30, 12:30–00:30 (+1)"


def test_wrapping_weekday_range_and_single_digit_hours():
    assert evaluate("Su-Th 12:00-24:00", SUN).status == "open_hours"
    assert evaluate("Su-Th 12:00-24:00", SAT).status == "closed"
    assert evaluate("8:00-2:30", WED).intervals == [(0, hm("02:30")), (hm("08:00"), 1440 + hm("02:30"))]


def test_midnight_and_24_00_endings():
    assert evaluate("10:00-00:00", WED).intervals == [(hm("10:00"), 1440)]
    assert format_intervals(evaluate("12:30-24:00", WED).intervals) == "12:30–24:00"
    assert evaluate("Mo-Su 10:00-05:00", WED).intervals == [(0, hm("05:00")), (hm("10:00"), 1440 + hm("05:00"))]


def test_24_7_is_open_all_day():
    result = evaluate("24/7", SAT)
    assert result.status == "open_all_day" and result.intervals == [(0, 1440)]
    assert evaluate("Mo-Su 00:00-24:00", SAT).status == "open_all_day"


def test_open_ended_time_runs_to_midnight():
    result = evaluate("Mo-Su 12:30-15:30,19:30+", SAT)
    assert result.intervals == [(hm("12:30"), hm("15:30")), (hm("19:30"), 1440)]


def test_public_holiday_rules():
    spec = "Mo-Sa 09:30-21:30; Su,PH 11:00-21:00"
    assert evaluate(spec, WED, holiday=False).intervals == [(hm("09:30"), hm("21:30"))]
    holiday = evaluate(spec, WED, holiday=True)
    assert holiday.intervals == [(hm("11:00"), hm("21:00"))] and not holiday.uncertain
    unknown = evaluate(spec, WED, holiday=None)
    assert unknown.intervals == [(hm("09:30"), hm("21:30"))] and unknown.uncertain
    assert evaluate("Mo-Fr 09:00-18:00; PH off", WED, holiday=True).status == "closed"
    assert evaluate("Mo-Su,PH 08:00-23:00", SAT, holiday=False).status == "open_hours"


def test_month_ranges():
    spec = "Jun-Aug Mo-Su 10:00-20:00; Sep-May Mo-Su 10:00-17:00"
    assert evaluate(spec, WED).intervals == [(hm("10:00"), hm("20:00"))]
    assert evaluate(spec, datetime.date(2026, 12, 2)).intervals == [(hm("10:00"), hm("17:00"))]
    assert evaluate("Dec-Feb Mo-Su 09:00-15:00", datetime.date(2026, 1, 10)).status == "open_hours"   # wraps the year
    assert evaluate("Dec-Feb Mo-Su 09:00-15:00", WED).status == "closed"


def test_sunrise_and_sunset_bounds_need_the_light_data():
    sun = {"sunrise": hm("06:00"), "sunset": hm("21:00")}
    assert evaluate("sunrise-sunset", WED, sun=sun).intervals == [(hm("06:00"), hm("21:00"))]
    assert evaluate("Mo-Su 09:00-sunset", WED, sun=sun).intervals == [(hm("09:00"), hm("21:00"))]
    missing = evaluate("sunrise-sunset", WED)
    assert missing.status == "unknown" and "sunrise" in missing.note


@pytest.mark.parametrize("spec", [
    "Mo-Fr 09:00-18:00 \"by appointment\"", "Mo-Fr 09:00-21:00; Su[1] 10:00-15:00", "Mo-Fr 09:00-18:00; SH off",
    "Jan 01,06 off; Mo-Su 10:00-22:00", "Mo-Fr 19:00-27:00", "open \"By appointment only\"", "Mo-Fr 09:00-18:00 || open",
    "week 1-53 Mo 09:00-12:00", "Mo-Su 09:00", "Mo-Fr", "", "   ", "Mo-Fr 09:00-(sunrise+01:00)",
])
def test_unsupported_syntax_is_unknown_never_a_guess(spec):
    result = evaluate(spec, WED)
    assert result.status == "unknown" and result.intervals == [] and result.note


def test_a_list_of_closures_only_is_unknown_not_closed():
    assert evaluate("PH off", WED, holiday=True).status == "unknown"
    assert evaluate("off", WED).status == "closed"


def test_open_at_and_latest_close():
    result = evaluate("Mo-Su 09:00-18:00", WED)
    assert open_at(result, hm("12:00")) and not open_at(result, hm("18:00")) and not open_at(result, hm("08:59"))
    assert latest_close(result) == hm("18:00")
    assert latest_close(evaluate("Su off", SUN)) is None


def test_real_world_strings_never_raise_and_are_sane():
    strings = json.loads((HERE / "fixtures" / "opening_hours_real.json").read_text(encoding="utf-8"))
    assert len(strings) > 400          # Madrid, Yekaterinburg and Moscow, as fetched from Overpass
    sun = {"sunrise": hm("06:00"), "sunset": hm("21:00")}
    unknown = 0
    for spec in strings:
        for day in (SAT, SUN, WED):
            for holiday in (True, False, None):
                result = evaluate(spec, day, holiday, sun)
                assert isinstance(result, OpeningResult), spec
                assert result.status in ("open_hours", "open_all_day", "closed", "unknown"), spec
                for s, e in result.intervals:
                    assert 0 <= s < e <= 2880, (spec, result.intervals)
                if result.status == "unknown":
                    assert result.note, spec
        if evaluate(spec, WED, False, sun).status == "unknown":
            unknown += 1
    assert unknown / len(strings) < 0.06, f"{unknown} of {len(strings)} real strings are unsupported"


FRI = datetime.date(2026, 7, 3)


def test_comma_rules_add_to_earlier_rules_on_the_same_day():
    spec = "Mo-Sa 09:00-12:00, We 15:00-18:00"           # the OSM spec example
    assert evaluate(spec, WED).intervals == [(hm("09:00"), hm("12:00")), (hm("15:00"), hm("18:00"))]
    assert evaluate(spec, MON).intervals == [(hm("09:00"), hm("12:00"))]
    assert evaluate("Mo-Fr 08:00-12:00, We 14:00-18:00", WED).intervals == [
        (hm("08:00"), hm("12:00")), (hm("14:00"), hm("18:00"))]
    real = "Mo-Su 12:00-24:00, Fr,Sa 00:00-02:00"        # real string from the fixture
    assert real in json.loads((HERE / "fixtures" / "opening_hours_real.json").read_text(encoding="utf-8"))
    assert evaluate(real, FRI).intervals == [(0, hm("02:00")), (hm("12:00"), 1440)]
    assert evaluate(real, WED).intervals == [(hm("12:00"), 1440)]


def test_an_additive_rule_with_off_still_closes_and_semicolon_still_overrides():
    assert evaluate("Mo-Fr 09:00-18:00, We off", WED).status == "closed"
    assert evaluate("Mo-Fr 09:00-18:00, We off", MON).intervals == [(hm("09:00"), hm("18:00"))]
    assert evaluate("Mo-Sa 09:00-12:00; We 15:00-18:00", WED).intervals == [(hm("15:00"), hm("18:00"))]


REAL_PINS = [
    # (string, day, holiday, expected status, expected intervals) -- each checked by hand against the OSM meaning
    ("Mo-Fr 07:30-18:00", WED, None, "open_hours", [(450, 1080)]),
    ("Mo-Fr 07:30-18:00", SAT, None, "closed", []),
    ("Mo-Fr 08:00-22:00,Sa 09:00-22:00,Su,PH 10:00-16:00", SAT, None, "open_hours", [(540, 1320)]),
    ("Mo-Fr 08:00-22:00,Sa 09:00-22:00,Su,PH 10:00-16:00", SUN, False, "open_hours", [(600, 960)]),
    ("Mo-Fr 08:00-22:00,Sa 09:00-22:00,Su,PH 10:00-16:00", WED, True, "open_hours", [(480, 1320)]),   # the PH rule adds 10-16, inside 08-22
    ("Fr-Sa 12:00-02:00; Mo-Th,Su 12:00-24:00", SAT, None, "open_hours", [(0, 120), (720, 1560)]),
    ("Fr-Sa 12:00-02:00; Mo-Th,Su 12:00-24:00", WED, None, "open_hours", [(720, 1440)]),
    ("Mo-Su 10:00-05:00", WED, None, "open_hours", [(0, 300), (600, 1740)]),
    ("Mo-Su 00:00-06:00,09:00-24:00", SAT, None, "open_hours", [(0, 360), (540, 1440)]),
    ("Mo-Fr 08:30-14:00; PH off", WED, True, "closed", []),
    ("Mo-Fr 08:30-14:00; PH off", WED, False, "open_hours", [(510, 840)]),
    ("Apr-Sep Mo-Su,PH 10:00-20:00; Oct-Mar Mo-Su,PH 10:00-18:00", WED, False, "open_hours", [(600, 1200)]),
    ("Apr-Sep Mo-Su,PH 10:00-20:00; Oct-Mar Mo-Su,PH 10:00-18:00", datetime.date(2026, 12, 2), False, "open_hours", [(600, 1080)]),
    ("24/7", SAT, None, "open_all_day", [(0, 1440)]),
    ("Mo,We,Fr 08:30-14:00; Tu,Th 16:30-18:30", WED, None, "open_hours", [(510, 840)]),
    ("Mo,We,Fr 08:30-14:00; Tu,Th 16:30-18:30", SAT, None, "closed", []),
    ("Su, We-Th 23:00-05:30; Fr-Sa 23:00-06:00", SAT, None, "open_hours", [(0, 360), (1380, 1800)]),
]


@pytest.mark.parametrize("spec,day,holiday,status,intervals", REAL_PINS)
def test_real_strings_pinned_to_hand_checked_intervals(spec, day, holiday, status, intervals):
    strings = json.loads((HERE / "fixtures" / "opening_hours_real.json").read_text(encoding="utf-8"))
    assert spec in strings
    result = evaluate(spec, day, holiday)
    assert (result.status, result.intervals) == (status, intervals)
