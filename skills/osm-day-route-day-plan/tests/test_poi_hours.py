import datetime
import json

from day_plan.context import build_context
from day_plan.plugins.poi_hours import PoiHoursPlugin

SAT = datetime.date(2026, 6, 27)
SUN = datetime.date(2026, 6, 28)
MON = datetime.date(2026, 6, 29)


class Web:
    def __call__(self, url):
        if "nominatim" in url:
            return {"address": {"country_code": "es"}}
        if "date.nager.at" in url:
            return [{"date": "2026-06-29", "localName": "Fiesta", "name": "Fiesta", "global": True}]
        raise AssertionError(url)


MUSEUM = ("Museo", "sight", -3.74, 40.43, {"opening_hours": "Tu-Su 10:00-18:00", "note": "Free on Sundays"})
CAVE = ("Cueva", "cave", -3.73, 40.44, {"opening_hours": "Mo-Fr 09:00-14:00"})
SPRING = ("Fuente", "spring", -3.72, 40.45, {})
VIEW = ("Mirador", "viewpoint", -3.71, 40.46, {"note": "Best at sunset"})


def _run(make_route_with_points, fixed_now, points, date=SAT, facts=None, lang="en", light=None, folder="proute"):
    route_dir = make_route_with_points(points, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=Web(), now=fixed_now)
    return PoiHoursPlugin().run(ctx, {"light": light} if light else {})


def test_hours_status_and_notes_on_the_date(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM, CAVE, SPRING, VIEW], date=SAT)
    md = section.markdown
    assert section.confidence == "tag-backed" and section.section_id == "pois"
    assert "| Museo | sight | 10:00–18:00 | Free on Sundays |" in md
    assert "| Cueva | cave | closed |  |" in md
    assert "| Mirador | viewpoint | not in OSM | Best at sunset |" in md
    assert "No opening hours in OSM for: Fuente, Mirador." in md


def test_a_closed_point_is_a_caution_and_an_open_one_is_not(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM, CAVE], date=SAT)
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Cueva is closed on this date.")]
    monday = _run(make_route_with_points, fixed_now, [MUSEUM], date=MON, folder="monday")   # Monday: the museum is closed
    assert [w.text for w in monday.warnings] == ["Museo is closed on this date."]


def test_holiday_rules_use_the_calendar(make_route_with_points, fixed_now):
    shop = ("Tienda", "sight", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; Su,PH off"})
    on_holiday = _run(make_route_with_points, fixed_now, [shop], date=MON)      # 2026-06-29 is listed as a holiday
    assert "| Tienda | sight | closed |" in on_holiday.markdown
    assert [w.severity for w in on_holiday.warnings] == ["caution"]


def test_a_closure_that_depends_on_an_unknown_holiday_is_not_a_closed_warning(make_route_with_points, fixed_now):
    class NoCountry(Web):
        def __call__(self, url):
            if "nominatim" in url:
                return {"error": "no country"}
            return super().__call__(url)

    shop = ("Tienda", "sight", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; PH off"})
    ctx = build_context(make_route_with_points([shop]), SAT, http=NoCountry(), now=fixed_now)
    section = PoiHoursPlugin().run(ctx, {})
    assert "09:00–21:00 (depends on the public-holiday rule)" in section.markdown
    assert section.warnings == []


def test_no_points_of_interest(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [("Lago", "access", -3.7, 40.4, {})])
    assert section.confidence == "no-data" and "no points of interest" in section.markdown


def test_points_without_hours_or_notes_are_only_listed_by_name(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [SPRING])
    assert section.confidence == "no-data"
    assert "No opening hours in OSM for: Fuente." in section.markdown and "|" not in section.markdown


def test_web_facts_add_special_features_and_warnings(make_route_with_points, fixed_now):
    fact = {"markdown": "The museum closes early on 27 June for a private event.", "sources": ["https://museo.example/agenda"],
            "warnings": [{"severity": "caution", "text": "Museo closes at 14:00 on 27 June."}]}
    section = _run(make_route_with_points, fixed_now, [MUSEUM], facts={"2026-06-27": {"poi_hours": fact}})
    assert section.confidence == "web-sourced"
    assert "closes early on 27 June" in section.markdown and "Sources: [museo.example](https://museo.example/agenda)" in section.markdown
    assert [w.text for w in section.warnings] == ["Museo closes at 14:00 on 27 June."]


def test_a_fact_without_sources_is_ignored(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM], facts={"all": {"poi_hours": {"markdown": "rumour"}}})
    assert "rumour" not in section.markdown


def test_long_notes_are_truncated_and_pipes_are_neutralised(make_route_with_points, fixed_now):
    point = ("Museo", "sight", -3.7, 40.4, {"opening_hours": "Mo-Su 10:00-18:00", "note": "a|b " + "x" * 300})
    row = next(l for l in _run(make_route_with_points, fixed_now, [point]).markdown.splitlines() if l.startswith("| Museo"))
    assert row.count("|") == 5 and row.endswith("… |") and "a/b" in row


def test_sun_bounds_use_the_light_data(make_route_with_points, fixed_now):
    park = ("Parque", "sight", -3.7, 40.4, {"opening_hours": "sunrise-sunset"})
    section = _run(make_route_with_points, fixed_now, [park], light={"sunrise_local_min": 400, "sunset_local_min": 1300})
    assert "| Parque | sight | 06:40–21:40 |" in section.markdown


def test_russian_headers(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM], lang="ru")
    assert section.markdown.splitlines()[0].startswith("| Точка | Вид | Часы работы в эту дату (OSM) | Примечание |")


def test_a_point_name_with_a_newline_gives_a_one_line_warning(make_route_with_points, fixed_now):
    cave = ("Cueva\n## Injected", "cave", -3.73, 40.44, {"opening_hours": "Mo-Fr 09:00-14:00"})
    section = _run(make_route_with_points, fixed_now, [cave], date=SAT)
    assert [w.text for w in section.warnings] == ["Cueva ## Injected is closed on this date."]
