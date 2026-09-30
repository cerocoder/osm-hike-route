import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.transit import TransitPlugin

FIXTURES = Path(__file__).parent / "fixtures"
MADRID = json.loads((FIXTURES / "overpass_routes_madrid.json").read_text(encoding="utf-8"))
MOSCOW = json.loads((FIXTURES / "overpass_routes_moscow.json").read_text(encoding="utf-8"))
SAT = datetime.date(2026, 6, 27)
URL = "https://www.crtm.es/horarios"


class Web:
    """Answers Nominatim, Nager.Date and Overpass; `overpass` may be a dict or an exception."""
    def __init__(self, overpass=MADRID, country="es", holidays=()):
        self.overpass, self.country, self.holidays, self.calls = overpass, country, list(holidays), []

    def __call__(self, url):
        self.calls.append(url)
        if "nominatim" in url:
            return {"address": {"country_code": self.country}}
        if "date.nager.at" in url:
            return self.holidays
        if "overpass" in url:
            if isinstance(self.overpass, Exception):
                raise self.overpass
            return self.overpass
        raise AssertionError(url)


def _plugin_run(make_route_with_points, fixed_now, points, web=None, lang="en", start=None, duration=4.0,
                facts=None, date=SAT, light=None, folder="proute"):
    route_dir = make_route_with_points(points, duration_hours=duration, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, start_time=start, http=web or Web(), now=fixed_now)
    return TransitPlugin().run(ctx, {"light": light} if light else {})


LAGO = ("Lago", "access", -3.7275, 40.4247, {"role": "start", "opening_hours": "Mo-Su 06:00-01:30"})
ATOCHA = ("Atocha", "access", -3.6906, 40.4065, {"role": "end", "opening_hours": "Mo-Su 05:30-22:00"})


def test_no_access_points_is_a_no_data_section_that_still_says_what_day_it_is(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [])
    assert section.confidence == "no-data"
    assert "Date: Saturday 2026-06-27 — weekend" in section.markdown
    assert "The route archive has no access point." in section.markdown
    assert section.warnings == []


def test_hours_and_lines_come_from_osm_and_are_tag_backed(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO])
    md = section.markdown
    assert section.confidence == "tag-backed"
    assert "| Lago | start | 00:00–01:30, 06:00–01:30 (+1) |" in md
    assert md.count("| Lago | 41 | bus |") == 2 and "| Lago | 75 | bus |" in md
    assert "Atocha → Colonia del Manzanares" in md
    assert "No timetable or directions from the departure point are recorded" in md


def test_overpass_failure_degrades_to_a_note_and_keeps_the_hours(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=HttpError("504")))
    assert "OSM lists no lines for these access points" in section.markdown
    assert "| Lago | start | 00:00–01:30, 06:00–01:30 (+1) |" in section.markdown
    assert section.confidence == "tag-backed"           # the station hours are still OSM data


def test_access_point_without_any_osm_data_is_no_data(make_route_with_points, fixed_now):
    bare = ("Stop", "access", -3.7, 40.4, {})
    section = _plugin_run(make_route_with_points, fixed_now, [bare], web=Web(overpass={"elements": []}))
    assert section.confidence == "no-data"
    assert "| Stop | – | not in OSM |" in section.markdown


def test_interval_and_operating_hours_of_a_line_are_evaluated_for_the_date(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=MOSCOW))
    md = section.markdown
    assert "every 30 min" in md and "yes: 00:00–00:10, 05:30–00:10 (+1)" in md
    assert "every 10 min" in md and "not stated in OSM" in md


def test_a_line_that_does_not_run_on_the_date(make_route_with_points, fixed_now):
    data = {"elements": [{"tags": {"route": "bus", "ref": "7", "from": "A", "to": "B", "opening_hours": "Mo-Fr 06:00-22:00"}}]}
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=data))
    assert "| Lago | 7 | bus | A → B | – | no |" in section.markdown


def test_unreadable_hours_are_shown_verbatim_and_pipes_cannot_break_the_table(make_route_with_points, fixed_now):
    odd = ("Odd | stop", "access", -3.7, 40.4, {"opening_hours": 'Mo-Fr 09:00-18:00 "by | appointment"'})
    section = _plugin_run(make_route_with_points, fixed_now, [odd], web=Web(overpass={"elements": []}))
    row = next(l for l in section.markdown.splitlines() if l.startswith("| Odd"))
    assert row.count("|") == 4                       # 3 cells: no stray pipe from the name or the raw hours
    assert "not read:" in row


def test_public_holiday_rule_without_holiday_data_is_flagged(make_route_with_points, fixed_now):
    stop = ("Ph", "access", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; Su,PH 11:00-21:00"})
    web = Web(overpass={"elements": []})
    web.country = ""        # the country cannot be determined -> holiday unknown
    section = _plugin_run(make_route_with_points, fixed_now, [stop], web=web)
    assert "(depends on the public-holiday rule)" in section.markdown


def test_return_point_closing_before_the_estimated_return_is_a_caution(make_route_with_points, fixed_now):
    import datetime as dt
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO, ATOCHA], start=dt.time(16, 0), duration=6.5)
    assert [w.severity for w in section.warnings] == ["caution"]
    assert "Atocha closes at 22:00, the estimated return is at 22:30" in section.warnings[0].text


def test_no_start_time_means_no_cross_check(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO, ATOCHA])
    assert section.warnings == []


def test_ambiguous_return_point_is_not_checked(make_route_with_points, fixed_now):
    import datetime as dt
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], start=dt.time(16, 0), duration=6.0,
                          web=Web(overpass={"elements": []}))
    assert section.warnings == []


FACT = {"markdown": "From Madrid: metro line 10 to Lago (about 25 min). Bus 41 back from Colonia every 20 min.",
        "sources": [URL, "https://www.metromadrid.es/"]}


def test_web_facts_are_shown_with_sources_and_make_the_section_web_sourced(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], facts={"2026-06-27": {"transit": FACT}})
    md = section.markdown
    assert section.confidence == "web-sourced"
    assert "**Timetables and directions (web-sourced, not verified in person)**" in md
    assert "metro line 10 to Lago" in md
    assert "Sources: [www.crtm.es](https://www.crtm.es/horarios), [www.metromadrid.es](https://www.metromadrid.es/)" in md
    assert "No timetable or directions" not in md
    assert section.sources == FACT["sources"]


def test_a_fact_without_sources_is_not_used(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO],
                          facts={"2026-06-27": {"transit": {"markdown": "unsourced claim"}}})
    assert "unsourced claim" not in section.markdown and section.confidence == "tag-backed"


@pytest.mark.parametrize("last,severity", [("21:10", "danger"), ("22:40", "caution"), ("23:30", None)])
def test_last_departure_versus_the_estimated_return(make_route_with_points, fixed_now, last, severity):
    import datetime as dt
    fact = dict(FACT, last_departure_local=last)
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], start=dt.time(16, 0), duration=6.5,   # returns 22:30
                          facts={"all": {"transit": fact}})
    got = [w.severity for w in section.warnings]
    assert got == ([severity] if severity else [])
    if severity == "danger":
        assert "last departure (21:10) is before the estimated return at 22:30" in section.warnings[0].text


def test_a_departure_after_midnight_counts_as_the_night_after_the_date(make_route_with_points, fixed_now):
    import datetime as dt
    fact = dict(FACT, last_departure_local="00:20")
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], start=dt.time(16, 0), duration=6.5,
                          facts={"all": {"transit": fact}})
    assert section.warnings == []               # 00:20 the next night is after 22:30


def test_warnings_from_facts_reach_the_section(make_route_with_points, fixed_now):
    fact = dict(FACT, warnings=[{"severity": "caution", "text": "Line 10 is closed for works on Saturdays."}])
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], facts={"all": {"transit": fact}})
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Line 10 is closed for works on Saturdays.")]


def test_russian_output(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], lang="ru", web=Web(overpass=MOSCOW))
    md = section.markdown
    assert "Дата: суббота 2026-06-27 — выходной" in md
    assert "**Точки заброски**" in md and "каждые 30 мин" in md and "автобус" in md


def test_sunrise_bounds_in_line_hours_use_the_light_plugin(make_route_with_points, fixed_now):
    data = {"elements": [{"tags": {"route": "bus", "ref": "N1", "opening_hours": "sunset-sunrise"}}]}
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=data),
                          light={"sunrise_local_min": 400, "sunset_local_min": 1300})
    assert "yes: 00:00–06:40, 21:40–06:40 (+1)" in section.markdown


class PartialWeb:
    """Web that fails Overpass for the first point's coordinates, succeeds for the second."""
    def __init__(self, first_lat, first_lon):
        self.first_lat = first_lat
        self.first_lon = first_lon
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if "nominatim" in url:
            return {"address": {"country_code": "es"}}
        if "date.nager.at" in url:
            return []
        if "overpass" in url:
            # Fail if the first point's latitude string appears in the URL
            if f"{self.first_lat:.4f}" in url:
                raise HttpError("504")
            return MADRID
        raise AssertionError(url)


def test_partial_overpass_failure_shows_rows_for_succeeded_points_and_notes_failure(make_route_with_points, fixed_now):
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    web = PartialWeb(first[3], first[2])
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], web=web)
    md = section.markdown
    # Rows for second point are present
    assert "| B | 41 | bus |" in md
    # Rows for first point are NOT present (no "| A | 41")
    assert "| A | 41" not in md
    # The partial warning is present
    assert "Lines for some access points could not be loaded" in md
    # The section is still tag-backed (has access point hours from OSM)
    assert section.confidence == "tag-backed"


def test_partial_failure_note_absent_when_all_succeed(make_route_with_points, fixed_now):
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], web=Web())
    md = section.markdown
    # Both points have lines
    assert "| A | 41" in md and "| B | 41" in md
    # The partial warning is NOT present
    assert "Lines for some access points could not be loaded" not in md


def test_partial_failure_note_absent_when_all_fail(make_route_with_points, fixed_now):
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], web=Web(overpass=HttpError("504")))
    md = section.markdown
    # No lines rows
    assert "| A | 41" not in md and "| B | 41" not in md
    # The generic "OSM lists no lines" message is present
    assert "OSM lists no lines for these access points" in md
    # The partial warning is NOT present
    assert "Lines for some access points could not be loaded" not in md


def test_partial_overpass_failure_shows_russian_note(make_route_with_points, fixed_now):
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    web = PartialWeb(first[3], first[2])
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], web=web, lang="ru")
    md = section.markdown
    # The Russian partial warning is present
    assert "Маршруты для некоторых точек заброски не удалось загрузить" in md


def test_a_point_name_with_a_newline_gives_a_one_line_warning(make_route_with_points, fixed_now):
    import datetime as dt
    end = ("Atocha\n## Injected", "access", -3.6906, 40.4065, {"role": "end", "opening_hours": "Mo-Su 05:30-22:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [end], start=dt.time(16, 0), duration=6.5,
                          web=Web(overpass={"elements": []}))
    assert len(section.warnings) == 1 and "\n" not in section.warnings[0].text
    assert section.warnings[0].text.startswith("Atocha ## Injected closes at 22:00")


# ---- a closed access point warns ---------------------------------------------------------------

WORKDAYS = ("Terminal", "access", -3.7, 40.4, {"role": "end", "opening_hours": "Mo-Fr 06:00-18:00"})


def test_a_closed_return_point_is_a_caution_with_or_without_a_start_time(make_route_with_points, fixed_now):
    import datetime as dt
    for start in (None, dt.time(9, 0)):
        section = _plugin_run(make_route_with_points, fixed_now, [WORKDAYS], start=start,
                              web=Web(overpass={"elements": []}), folder=f"c{start is not None}")
        assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Terminal is closed on this date.")]


def test_a_closed_start_point_warns_too_and_an_open_point_does_not(make_route_with_points, fixed_now):
    start_point = ("Depot", "access", -3.7, 40.4, {"role": "start", "opening_hours": "Mo-Fr 06:00-18:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [start_point, ATOCHA], web=Web(overpass={"elements": []}))
    assert [w.text for w in section.warnings] == ["Depot is closed on this date."]


def test_an_uncertain_closure_does_not_warn(make_route_with_points, fixed_now):
    stop = ("Ph", "access", -3.7, 40.4, {"role": "end", "opening_hours": "Mo-Fr 09:00-18:00; PH 10:00-12:00"})
    web = Web(overpass={"elements": []})
    web.country = ""
    section = _plugin_run(make_route_with_points, fixed_now, [stop], web=web)     # Saturday, PH status unknown
    assert section.warnings == []


# ---- the lines table ---------------------------------------------------------------------------

def _lines(make_route_with_points, fixed_now, tags_list, lang="en", folder="proute"):
    data = {"elements": [{"tags": {"route": "bus", **tags}} for tags in tags_list]}
    return _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=data), lang=lang, folder=folder).markdown


def test_a_relation_without_ref_name_or_direction_shows_dashes(make_route_with_points, fixed_now):
    md = _lines(make_route_with_points, fixed_now, [{}])
    assert "| Lago | – | bus | – | – | not stated in OSM |" in md


def test_rows_identical_on_the_shown_columns_appear_once(make_route_with_points, fixed_now):
    md = _lines(make_route_with_points, fixed_now, [
        {"ref": "7", "from": "A", "to": "B", "name": "first", "operator": "X"},
        {"ref": "7", "from": "A", "to": "B", "name": "second", "operator": "Y"},
        {"ref": "8", "from": "A", "to": "B"}])
    assert md.count("| Lago | 7 | bus | A → B |") == 1 and md.count("| Lago | 8 | bus |") == 1


def test_at_most_25_rows_per_access_point_and_a_more_line(make_route_with_points, fixed_now):
    md = _lines(make_route_with_points, fixed_now, [{"ref": str(n)} for n in range(1, 41)])
    assert md.count("| Lago | ") == 1 + 25                # the access-point row and 25 lines
    assert "| Lago | 25 | bus |" in md and "| Lago | 26 | bus |" not in md
    assert "… and 15 more lines" in md
    assert "… и ещё 15" in _lines(make_route_with_points, fixed_now, [{"ref": str(n)} for n in range(1, 41)],
                                   lang="ru", folder="ru")
    assert "more lines" not in _lines(make_route_with_points, fixed_now, [{"ref": "1"}], folder="one")
