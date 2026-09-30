import datetime

from day_plan.context import build_context
from day_plan.plugins.radiation import RadiationPlugin

DATE = datetime.date(2026, 7, 4)
CROSSING = ((29.0, 51.3, 150.0), (31.0, 51.3, 150.0))              # crosses the Chernobyl zone, both ends outside
BRYANSK = ((31.90, 52.54, 150.0), (31.95, 52.56, 150.0))
NEAR_CHERNOBYL = ((30.3851, 51.0634, 120.0), (30.3861, 51.0634, 120.0))    # about 2.2 km south of the zone
MADRID = ((-3.75, 40.42, 650.0), (-3.74, 40.43, 660.0))
SYDNEY = ((151.20, -33.86, 20.0), (151.21, -33.85, 25.0))
BEIJING = ((116.39, 39.90, 50.0), (116.41, 39.92, 50.0))
BAVARIAN_FOREST = ((13.35, 48.85, 700.0), (13.42, 48.88, 900.0))
NEAR_BAVARIAN_AREA = ((12.08, 49.075, 500.0), (12.081, 49.076, 500.0))     # about 1.5 km outside a Bavarian area
TULA = ((37.50, 54.00, 200.0), (37.55, 54.02, 210.0))
KYSHTYM = ((60.50, 55.70, 250.0), (60.62, 55.74, 255.0), (60.85, 55.80, 260.0))     # the reserve, Mayak and the trace


def run(make_route, fixed_now, coords, lang="en", folder="route", points=None, make_route_with_points=None):
    if points is not None:
        route_dir = make_route_with_points(points, coords=coords, folder=folder)
    else:
        route_dir = make_route(coords=coords, folder=folder)
    ctx = build_context(route_dir, DATE, lang=lang, http=lambda u: {}, now=fixed_now)
    return RadiationPlugin().run(ctx, {})


def test_a_route_crossing_a_closed_zone_gets_a_pinned_danger_and_the_four_advisories(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING)
    md = section.markdown
    assert "Chernobyl exclusion zone (Ukraine)** (danger zone): the route or one of its points is inside the zone." in md
    assert "- Do not pick mushrooms or berries." in md
    assert "Springs, streams and other natural water may be contaminated: do not drink from them or collect water." in md
    assert "Avoid dust and open fires on the soil" in md and "Wind and wildfire lift contaminated dust and smoke" in md
    assert "Consider changing the route (osm-day-route-planning)" in md
    danger = [w for w in section.warnings if w.severity == "danger" and "Chernobyl exclusion zone" in w.text]
    assert danger and danger[0].pinned and "Do not pick mushrooms or berries" in danger[0].text
    assert section.confidence == "tag-backed" and section.omit is False
    assert "https://www.iaea.org/sites/default/files/21/07/_t1_02_kashparov_ukraine.pdf" in section.sources


def test_the_neighbouring_reserve_is_reported_as_near_with_its_distance(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING)
    assert "Polesie State Radioecological Reserve (Belarus)** (danger zone): the route passes about 0.9 km from the zone." \
        in section.markdown
    assert any(w.severity == "caution" and "about 0.9 km from Polesie" in w.text for w in section.warnings)


def test_a_near_miss_is_a_caution_not_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_CHERNOBYL)
    assert [w.severity for w in section.warnings] == ["caution"] and section.warnings[0].pinned
    assert "passes about 2.2 km from the zone" in section.markdown
    assert "Consider changing the route" not in section.markdown          # only when a danger zone is entered


def test_an_affected_area_is_a_caution_inside_and_an_info_when_only_near(make_route, fixed_now):
    inside = run(make_route, fixed_now, BRYANSK)
    assert "(affected area): the route or one of its points is inside the zone" in inside.markdown
    assert [w.severity for w in inside.warnings] == ["caution"]
    assert "Only some settlements of each district are listed." in inside.markdown
    assert "Approximate outline:" in inside.markdown and "whole districts" in inside.markdown
    assert "Zone outlines from OpenStreetMap" in inside.markdown


def test_an_advisory_area_gets_an_info_line_and_only_the_mushroom_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, BAVARIAN_FOREST)
    md = section.markdown
    assert "(advisory area): the route or one of its points is inside the zone" in md
    assert "moderate consumption is considered harmless everywhere in Germany" in md
    assert "- Wild mushrooms and game from these areas can still carry caesium-137: eat them in moderation" in md
    assert "Springs, streams" not in md and "Do not pick mushrooms or berries." not in md
    assert [(w.severity, w.pinned) for w in section.warnings] == [("info", False)]
    assert "Consider changing the route" not in md and section.confidence == "tag-backed"
    assert "https://www.bfs.de/SharedDocs/Pressemitteilungen/BfS/DE/2024/013.html" in section.sources


def test_the_norwegian_mountain_municipalities_are_an_info_line_with_the_dsa_source(make_route, fixed_now):
    section = run(make_route, fixed_now, ((8.90, 61.24, 900.0), (8.93, 61.26, 950.0)), folder="no")
    assert "Norwegian mountain municipalities with the highest caesium in wild mushrooms** (advisory area)" in section.markdown
    assert "80 000 Bq of caesium a year" in section.markdown and [w.severity for w in section.warnings] == ["info"]
    assert any("dsa.no/publikasjoner/radioaktivitet-i-norsk-mat" in u for u in section.sources)
    assert section.confidence == "tag-backed"


def test_being_near_an_advisory_area_says_nothing_but_tells_the_truth(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_BAVARIAN_AREA, folder="near")
    assert section.warnings == []
    assert section.markdown.startswith(
        "- No danger zone or affected area of the radiation registry lies within 3 km of the route or its points.")
    assert "so no entry does not mean the land is clean" in section.markdown and "safe" not in section.markdown.lower()
    assert "No zone of the radiation registry" not in section.markdown


def test_the_advisory_wording_is_translated(make_route, fixed_now):
    section = run(make_route, fixed_now, NEAR_BAVARIAN_AREA, lang="ru", folder="nearru")
    assert section.markdown.startswith("- Ни опасная зона, ни затронутая территория реестра радиации не лежат в радиусе 3 км")


def test_a_route_inside_an_advisory_area_alone_gets_no_full_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, ((13.0, 48.9, 500.0), (13.4, 48.9, 500.0)), folder="mixed")
    assert "(advisory area)" in section.markdown       # the Bavarian Forest
    assert "Wild mushrooms and game from these areas" in section.markdown and "Springs, streams" not in section.markdown


def test_a_small_near_miss_reads_in_tenths_of_a_kilometre(make_route, fixed_now):
    section = run(make_route, fixed_now, ((30.3851, 51.0805, 120.0), (30.3861, 51.0805, 120.0)), folder="tenth")
    near = [w.text for w in section.warnings if "about" in w.text]
    assert len(near) == 1 and near[0].startswith("The route passes about 0.3 km from ")
    assert "about 0 km" not in near[0]


def test_central_russian_districts_are_a_caution_with_the_decree_as_source(make_route, fixed_now):
    section = run(make_route, fixed_now, TULA)
    assert "Tula, Kaluga and Orel districts with Chernobyl-contaminated settlements** (affected area)" in section.markdown
    assert "decree No. 1074 of 2015" in section.markdown and [w.severity for w in section.warnings] == ["caution"]
    assert "http://government.ru/docs/all/103736/" in section.sources and "Only some settlements of each district" in section.markdown


def test_a_route_with_no_hit_says_no_entry_not_safe(make_route, fixed_now):
    section = run(make_route, fixed_now, MADRID)
    assert section.omit is False and section.warnings == [] and section.confidence == "derived"
    assert section.markdown.startswith("- No zone of the radiation registry lies within 3 km of the route or its points.")
    assert "so no entry does not mean the land is clean" in section.markdown and "safe" not in section.markdown.lower()


def test_a_route_far_outside_the_registry_area_gets_no_radiation_part(make_route, fixed_now):
    for coords, folder in ((SYDNEY, "syd"), (BEIJING, "bei")):
        section = run(make_route, fixed_now, coords, folder=folder)
        assert section.omit is True and section.markdown == "" and section.warnings == []


def test_a_point_off_the_track_inside_a_zone_counts(make_route, make_route_with_points, fixed_now):
    section = run(make_route, fixed_now, ((40.0, 55.0, 150.0), (40.1, 55.0, 150.0)), folder="p",
                  points=[("Spring", "spring", 30.099, 51.389, {})], make_route_with_points=make_route_with_points)
    assert "Chernobyl exclusion zone" in section.markdown and section.warnings[0].severity == "danger"


def test_the_east_urals_trace_is_an_approximate_caution_and_the_reserve_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, KYSHTYM)
    assert "East Ural State Nature Reserve (core of the East Urals Radioactive Trace)** (danger zone)" in section.markdown
    assert "East Urals Radioactive Trace (fallout of 1957, approximate outline)** (affected area)" in section.markdown
    assert "Approximate outline: Centre line through Bagaryak" in section.markdown
    assert any(w.text == "The route crosses East Urals Radioactive Trace (fallout of 1957, approximate outline). "
               "Do not pick mushrooms or berries and do not drink from springs or streams."
               for w in section.warnings)
    assert all("contamination:" not in w.text for w in section.warnings)


def test_russian_text_uses_the_russian_names_and_advice(make_route, fixed_now):
    section = run(make_route, fixed_now, CROSSING, lang="ru")
    assert "Чернобыльская зона отчуждения (Украина)** (опасная зона)" in section.markdown
    assert "Не собирайте грибы и ягоды." in section.markdown
    assert "Родники, ручьи и другая природная вода могут быть заражены" in section.markdown
    assert section.warnings[0].text.startswith("Маршрут входит в зону: Чернобыльская зона отчуждения (Украина) — заражённая земля.")
    assert section.markdown.count("Источники:") == 1 and "Centre" not in section.markdown and "Outline" not in section.markdown


def test_radiation_needs_no_network_and_no_other_plugin(make_route, fixed_now):
    calls = []
    route_dir = make_route(coords=CROSSING)
    ctx = build_context(route_dir, DATE, http=lambda u: calls.append(u) or {}, now=fixed_now)
    section = RadiationPlugin().run(ctx, {})
    assert calls == [] and RadiationPlugin.depends_on == () and section.warnings
