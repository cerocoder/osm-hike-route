import datetime
import json

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import OsmFeature
from day_plan.plugins.cell_coverage import CellCoveragePlugin, nperf_url
from day_plan.plugins.people_hazards import PeopleHazardsPlugin

DATE = datetime.date(2026, 7, 4)
FACT = {"markdown": "The border zone here needs a permit from the border service.",
        "sources": ["https://example.org/permits"],
        "warnings": [{"severity": "caution", "text": "Permit needed near the border."}]}


def people(make_route, fixed_now, facts=None, lang="en"):
    route_dir = make_route()
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, DATE, lang=lang, http=lambda u: {}, now=fixed_now)
    return PeopleHazardsPlugin().run(ctx, {})


def test_without_a_recorded_fact_the_people_part_is_left_out_not_listed_as_missing(make_route, fixed_now):
    section = people(make_route, fixed_now)
    assert section.omit is True and section.markdown == "" and section.warnings == []


def test_a_recorded_fact_is_shown_with_its_sources_and_warnings(make_route, fixed_now):
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": FACT}})
    assert "The border zone here needs a permit from the border service." in section.markdown
    assert "Access and safety notes (from web sources, not verified in person)" in section.markdown
    assert "Sources: [example.org](https://example.org/permits)" in section.markdown
    assert section.confidence == "web-sourced" and section.sources == ["https://example.org/permits"]
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Permit needed near the border.")]


def test_a_fact_without_a_source_is_ignored(make_route, fixed_now):
    bad = {"markdown": "Locals are aggressive.", "sources": []}
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": bad}})
    assert section.omit is True


def test_the_russian_title_of_the_fact(make_route, fixed_now):
    section = people(make_route, fixed_now, facts={"all": {"people_hazards": FACT}}, lang="ru")
    assert "Доступ и безопасность (по веб-источникам, лично не проверено)" in section.markdown


def coverage(make_route, fixed_now, features=None, error=None, samples=True, lang="en", country=None, folder="route"):
    def http(url):
        if country and "nominatim" in url:
            return {"address": {"country_code": country}}
        return {}
    ctx = build_context(make_route(folder=folder), DATE, lang=lang, http=http, now=fixed_now)
    osm = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords] if samples else None,
           "error": error}
    return CellCoveragePlugin().run(ctx, {"osm_features": osm}), ctx


def mast(dlat):
    return OsmFeature("mast", 51.45 + dlat, -0.20, "", "")


def test_masts_near_the_route_are_counted_with_the_nearest_distance(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.009), mast(0.02), mast(0.5)])
    md = section.markdown
    assert "Mobile masts recorded in OpenStreetMap within 5 km of the route: **2** (nearest about 1.0 km)." in md
    assert section.confidence == "tag-backed" and section.warnings == []
    assert section.section_id == "cell_coverage" and section.omit is False


def test_the_caveat_the_advice_and_the_map_links_are_always_there(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.0)])
    md = section.markdown
    assert "a missing mast does not mean there is no signal" in md and "Coverage is not measured here." in md
    assert "Download offline maps and the GPX track" in md and "112" in md
    assert "[nPerf](https://www.nperf.com/en/map)" in md and "[OpenCellID](https://opencellid.org/)" in md


def test_no_mast_recorded_is_only_an_info_warning(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.5)])
    assert "No mobile masts are recorded in OpenStreetMap within 5 km of the route." in section.markdown
    assert [w.severity for w in section.warnings] == ["info"]
    assert "signal may be weak or absent" in section.warnings[0].text


def test_when_openstreetmap_is_unavailable_the_section_is_no_data_but_keeps_the_links(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, error="Overpass 504")
    assert section.confidence == "no-data" and section.warnings == []
    assert "Mast data from OpenStreetMap could not be loaded (Overpass 504)." in section.markdown
    assert "nPerf" in section.markdown and "112" in section.markdown


def test_a_missing_osm_plugin_is_handled(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, samples=False)
    assert section.confidence == "no-data" and "could not be loaded (no data)" in section.markdown


def test_the_nperf_link_is_country_specific_when_the_country_is_known(make_route, fixed_now):
    section, ctx = coverage(make_route, fixed_now, features=[mast(0.0)], country="ru")
    assert "[nPerf](https://www.nperf.com/en/map/RU/-/-/signal)" in section.markdown
    assert nperf_url(ctx) == "https://www.nperf.com/en/map/RU/-/-/signal"


def test_a_failing_country_lookup_falls_back_to_the_global_map(make_route, fixed_now):
    def broken(url):
        raise HttpError("503")
    ctx = build_context(make_route(), DATE, http=broken, now=fixed_now)
    assert nperf_url(ctx) == "https://www.nperf.com/en/map"


def test_russian_text(make_route, fixed_now):
    section, _ = coverage(make_route, fixed_now, features=[mast(0.5)], lang="ru")
    assert "В OpenStreetMap нет вышек сотовой связи в радиусе 5 км от маршрута." in section.markdown
    assert "112 — номер экстренных служб" in section.markdown and "Покрытие здесь не измеряется." in section.markdown
