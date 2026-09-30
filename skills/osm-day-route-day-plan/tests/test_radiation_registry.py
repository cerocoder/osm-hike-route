import copy

import pytest

from day_plan.radiation import (
    find_hits, in_scope, load_registry, validate_registry, validate_zone, zone_bbox,
)

REGISTRY = load_registry()
ZONES = {z["id"]: z for z in REGISTRY["zones"]}

# where each zone must lie (min_lon, min_lat, max_lon, max_lat): catches swapped lon/lat and stray vertices
EXPECTED_BBOX = {
    "ural-eurt-core": (60.6, 55.6, 61.2, 56.1),
    "ural-eurt-trace": (60.0, 55.3, 64.5, 58.4),
    "ural-techa-river": (60.6, 55.3, 63.4, 56.5),
    "ural-mayak-site": (60.7, 55.6, 61.1, 55.9),
    "ural-karachay": (60.6, 55.5, 61.0, 55.8),
    "ua-chernobyl-exclusion-zone": (29.0, 50.9, 30.8, 51.7),
    "by-polesie-reserve": (29.0, 51.0, 30.8, 52.1),
    "ru-bryansk-contaminated-districts": (31.0, 51.9, 32.8, 53.4),
    "kz-semipalatinsk-test-site": (76.8, 49.0, 79.4, 51.2),
    "ru-central-chernobyl-districts": (33.5, 52.9, 38.0, 54.4),
    "de-bavaria-wild-food-areas": (10.9, 47.3, 14.0, 49.4),
    "ru-yenisei-mcc-floodplain": (93.0, 56.0, 94.0, 57.2),
    "no-wild-mushroom-municipalities": (8.6, 61.0, 14.7, 65.95),
}


def test_the_shipped_registry_is_valid():
    assert validate_registry(REGISTRY) == []


def test_every_zone_has_at_least_one_source_and_a_primary_one_for_the_strong_claims():
    for zone in REGISTRY["zones"]:
        assert zone["sources"], zone["id"]
        assert all(s["url"].startswith(("https://", "http://government.ru/")) for s in zone["sources"]), zone["id"]
    assert all(any(s["kind"] == "primary" for s in z["sources"]) for z in REGISTRY["zones"])


def test_the_registry_covers_the_researched_areas_and_nothing_is_invented():
    assert set(ZONES) == set(EXPECTED_BBOX)


@pytest.mark.parametrize("zone_id", sorted(EXPECTED_BBOX))
def test_each_zone_lies_where_it_should(zone_id):
    min_lon, min_lat, max_lon, max_lat = zone_bbox(ZONES[zone_id])
    e_min_lon, e_min_lat, e_max_lon, e_max_lat = EXPECTED_BBOX[zone_id]
    assert e_min_lon <= min_lon and max_lon <= e_max_lon and e_min_lat <= min_lat and max_lat <= e_max_lat


def test_approximate_zones_say_how_their_shape_was_made():
    approximate = [z for z in REGISTRY["zones"] if z["approximate"]]
    assert {z["id"] for z in approximate} == {
        "ural-eurt-trace", "ural-techa-river", "ural-mayak-site", "ural-karachay", "ru-bryansk-contaminated-districts",
        "ru-central-chernobyl-districts", "de-bavaria-wild-food-areas", "ru-yenisei-mcc-floodplain",
        "no-wild-mushroom-municipalities"}
    assert all(len(z["geometry_note"]["en"]) > 40 and len(z["geometry_note"]["ru"]) > 40 for z in approximate)


def test_severity_and_advice_are_consistent():
    for zone in REGISTRY["zones"]:
        assert zone["severity"] in ("danger", "caution", "info") and zone["advice"] in ("full", "mushrooms")
        if zone["severity"] == "info":
            assert zone["advice"] == "mushrooms"
        if zone["severity"] == "danger":
            assert zone["advice"] == "full"


def test_every_zone_has_a_short_event_and_bilingual_texts():
    for zone in REGISTRY["zones"]:
        for key in ("name", "contamination", "status", "event"):
            assert zone[key]["en"] and zone[key]["ru"], (zone["id"], key)
        assert "Outline from OpenStreetMap" not in zone["event"]["en"]


KNOWN_INSIDE = {
    "Techa upper reach": ((60.7448, 55.7639), "ural-techa-river"),
    "Chernobyl NPP": ((30.099, 51.389), "ua-chernobyl-exclusion-zone"),
    "Polesie reserve": ((30.03, 51.55), "by-polesie-reserve"),
    "Novozybkov": ((31.93, 52.54), "ru-bryansk-contaminated-districts"),
    "Kamensk-Uralsky": ((61.93, 56.41), "ural-eurt-trace"),
    "Bogdanovich": ((62.05, 56.78), "ural-eurt-trace"),
    "Degelen": ((78.106, 49.805), "kz-semipalatinsk-test-site"),
    "Shchekino": ((37.52, 54.0), "ru-central-chernobyl-districts"),
    "Zhizdra": ((34.73, 53.75), "ru-central-chernobyl-districts"),
    "Belev": ((36.14, 53.81), "ru-central-chernobyl-districts"),
    "Bolkhov": ((36.0, 53.44), "ru-central-chernobyl-districts"),
    "Grafenau (Bavarian Forest)": ((13.40, 48.86), "de-bavaria-wild-food-areas"),
    "Berchtesgaden": ((13.0, 47.63), "de-bavaria-wild-food-areas"),
    "Mittenwald": ((11.26, 47.44), "de-bavaria-wild-food-areas"),
    "Yenisei at the combine": ((93.5264, 56.3085), "ru-yenisei-mcc-floodplain"),
    "Beitostølen (Øystre Slidre)": ((8.91, 61.25), "no-wild-mushroom-municipalities"),
    "Lierne": ((13.6, 64.46), "no-wild-mushroom-municipalities"),
    "Hattfjelldal": ((13.99, 65.6), "no-wild-mushroom-municipalities"),
    "Karachay": ((60.7997, 55.6783), "ural-karachay"),
    "Mayak": ((60.9, 55.7333), "ural-mayak-site"),
}
KNOWN_CLEAN = {"Kyiv": (30.52, 50.45), "Moscow": (37.62, 55.75), "Madrid": (-3.70, 40.42),
               "Ekaterinburg": (60.60, 56.84), "Chelyabinsk": (61.40, 55.16), "Minsk": (27.56, 53.90),
               "Argayash (south of Mayak)": (60.87, 55.49), "Shadrinsk (east of the trace)": (63.63, 56.09),
               "Kyshtym (upwind, west of Mayak)": (60.56, 55.71), "Kaluga city": (36.26, 54.51),
               "Oslo": (10.75, 59.91), "Trondheim": (10.40, 63.43), "Stockholm": (18.07, 59.33), "Munich": (11.58, 48.14), "Hamburg": (9.99, 53.55), "Krasnoyarsk city": (92.87, 56.01)}


@pytest.mark.parametrize("name", sorted(KNOWN_INSIDE))
def test_known_places_inside_the_zones_are_hits(name):
    (lon, lat), zone_id = KNOWN_INSIDE[name]
    hits = {h.zone["id"]: h for h in find_hits(REGISTRY, [(lon, lat), (lon + 0.0001, lat)], [])}
    assert zone_id in hits and hits[zone_id].inside


@pytest.mark.parametrize("name", sorted(KNOWN_CLEAN))
def test_known_clean_places_miss_every_zone(name):
    lon, lat = KNOWN_CLEAN[name]
    assert find_hits(REGISTRY, [(lon, lat), (lon + 0.0001, lat)], []) == []


def test_a_segment_crossing_a_zone_with_both_ends_outside_is_a_hit():
    hits = find_hits(REGISTRY, [(29.0, 51.3), (31.0, 51.3)], [])
    assert hits[0].zone["id"] == "ua-chernobyl-exclusion-zone" and hits[0].inside


def test_a_point_off_the_track_counts_and_a_near_miss_reports_the_distance():
    hits = find_hits(REGISTRY, [(40.0, 55.0), (40.1, 55.0)], [(30.099, 51.389)])
    assert [h.zone["id"] for h in hits] == ["ua-chernobyl-exclusion-zone"] and hits[0].inside
    south_lon, south_lat = 30.3851, 51.0834                                       # the zone's southernmost vertex
    assert find_hits(REGISTRY, [(south_lon, south_lat - 0.05), (south_lon + 0.001, south_lat - 0.05)], []) == []
    near = find_hits(REGISTRY, [(south_lon, south_lat - 0.02), (south_lon + 0.001, south_lat - 0.02)], [])
    assert near and not near[0].inside and near[0].distance_km == pytest.approx(2.22, abs=0.05)


def test_the_techa_buffer_follows_the_river_not_its_bounding_box():
    techa = ZONES["ural-techa-river"]["geometry"]["lines"][0][20]
    assert [h.zone["id"] for h in find_hits(REGISTRY, [tuple(techa), (techa[0] + 0.0001, techa[1])], [])
            if h.zone["id"] == "ural-techa-river"]
    lon, lat = techa
    far = find_hits(REGISTRY, [(lon, lat + 0.5), (lon + 0.0001, lat + 0.5)], [], margin_km=3.0)
    assert "ural-techa-river" not in [h.zone["id"] for h in far]


def _hit(pts, zone_id):
    return [h for h in find_hits(REGISTRY, pts, []) if h.zone["id"] == zone_id]


def test_a_long_segment_crossing_the_mayak_circle_with_both_ends_far_outside_is_a_hit():
    west, east = (60.6, 55.7333), (61.2, 55.7333)                # about 19 km either side of the 6 km circle
    assert _hit([west, west], "ural-mayak-site") == [] and _hit([east, east], "ural-mayak-site") == []
    hits = _hit([west, east], "ural-mayak-site")
    assert len(hits) == 1 and hits[0].inside and hits[0].distance_km == 0


def test_a_long_segment_crossing_the_techa_line_between_two_far_ends_is_a_hit():
    lon, lat = ZONES["ural-techa-river"]["geometry"]["lines"][0][20]      # a river vertex
    south, north = (lon, lat - 0.1), (lon, lat + 0.1)                     # about 11 km either side, beyond buffer and margin
    assert _hit([south, south], "ural-techa-river") == [] and _hit([north, north], "ural-techa-river") == []
    hits = _hit([south, north], "ural-techa-river")
    assert len(hits) == 1 and hits[0].inside and hits[0].distance_km == 0


def test_the_corridor_of_the_trace_does_not_reach_upwind_of_the_release_point():
    trace = [h for h in find_hits(REGISTRY, [(60.62, 55.70), (60.6201, 55.70)], []) if h.zone["id"] == "ural-eurt-trace"]
    assert trace == []                                    # Kyshtym-side land west of Mayak: the plume went north-east
    downwind = find_hits(REGISTRY, [(61.2, 56.0), (61.2001, 56.0)], [])
    assert "ural-eurt-trace" in [h.zone["id"] for h in downwind]


def test_the_trace_spans_about_three_hundred_kilometres_from_mayak():
    min_lon, min_lat, max_lon, max_lat = zone_bbox(ZONES["ural-eurt-trace"])
    far = (max_lon, max_lat)
    assert 250.0 <= km_from_mayak(far) <= 330.0


def km_from_mayak(point):
    import math
    lon, lat = point
    return math.hypot((lon - 60.9) * 111.195 * math.cos(math.radians(56.5)), (lat - 55.7333) * 111.195)


def test_in_scope():
    for lat, lon in ((56.84, 60.6), (40.4, -3.7), (64.0, 100.0), (43.1, 131.9), (62.0, 129.7), (41.0, 29.0)):
        assert in_scope(REGISTRY, lat, lon), (lat, lon)
    for lat, lon in ((-33.9, 151.2), (40.7, -74.0), (39.9, 116.4), (47.9, 106.9), (35.7, 139.7), (37.6, 127.0),
                     (30.0, 31.2)):
        assert not in_scope(REGISTRY, lat, lon), (lat, lon)


def test_validation_catches_broken_entries():
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["geometry"]["rings"][0][-1] = [0.0, 0.0]
    assert any("closed" in p for p in validate_zone(zone))
    bad_scope = copy.deepcopy(REGISTRY)
    bad_scope["scope"] = {"lon": [0, 1], "lat": [0, 1]}
    assert any("scope needs boxes" in p for p in validate_registry(bad_scope))
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["sources"] = []
    assert any("source" in p for p in validate_zone(zone))
    zone = copy.deepcopy(ZONES["ua-chernobyl-exclusion-zone"])
    zone["sources"][0]["url"] = "ftp://example.org/x"
    zone["severity"] = "fatal"
    zone["name"]["ru"] = ""
    problems = validate_zone(zone)
    assert any("bad source" in p for p in problems) and any("severity" in p for p in problems) \
        and any("name needs" in p for p in problems)
    no_advice = copy.deepcopy(ZONES["ural-karachay"])
    del no_advice["advice"]
    assert any("advice must be" in p for p in validate_zone(no_advice))
    circle = copy.deepcopy(ZONES["ural-karachay"])
    circle["geometry"]["center"] = [55.6783, 900.0]
    circle["approximate"] = True
    circle.pop("geometry_note")
    problems = validate_zone(circle)
    assert any("circle" in p for p in problems) and any("geometry_note" in p for p in problems)
    note = copy.deepcopy(ZONES["ural-karachay"])
    note["geometry_note"] = "English only"
    del note["event"]
    problems = validate_zone(note)
    assert any("geometry_note needs" in p for p in problems) and any("event needs" in p for p in problems)
    line = copy.deepcopy(ZONES["ural-techa-river"])
    line["geometry"]["half_width_km"] = 0
    assert any("half_width" in p for p in validate_zone(line))
    broken = copy.deepcopy(REGISTRY)
    broken["zones"].append(copy.deepcopy(broken["zones"][0]))
    assert any("duplicate" in p for p in validate_registry(broken))


def test_the_norwegian_zone_names_the_right_russian_mushroom():
    ru = ZONES["no-wild-mushroom-municipalities"]["status"]["ru"]
    assert "колпаке кольчатом" in ru and "кольцевик" not in ru
