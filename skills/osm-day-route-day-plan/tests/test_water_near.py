import datetime
import urllib.parse

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.water_near import (
    Anchor, POINT_MAX, WaterNearPlugin, parse_water, place_bodies, rect_distance_m, water_query,
)
from day_plan.overpass import MIRRORS
from day_plan.plugins.land_cover import cover_query, route_polyline

DATE = datetime.date(2026, 6, 21)


def _el(tags, bounds=None, lat=None, lon=None, type_="way"):
    element = {"type": type_, "id": 1, "tags": tags}
    if bounds:
        s, w, n, e = bounds
        element["bounds"] = {"minlat": s, "minlon": w, "maxlat": n, "maxlon": e}
        element["center"] = {"lat": (s + n) / 2, "lon": (w + e) / 2}
    if lat is not None:
        element["lat"], element["lon"] = lat, lon
    return element


def test_query_has_a_clause_for_the_track_and_for_each_point():
    points = [Anchor("poi", "Viewpoint", 40.43, -3.74), Anchor("start", "Cercedilla", 40.42, -3.75)]
    ql = water_query("40.42,-3.75,40.43,-3.74", points)
    assert "around:500,40.42,-3.75,40.43,-3.74" in ql
    assert "around:500,40.43000,-3.74000" in ql and "around:500,40.42000,-3.75000" in ql
    assert "coastline" in ql and "swimming_area" in ql and "river|canal" in ql and "out tags bb center" in ql
    assert "[timeout:9]" in ql


def _long_track():
    return [(-3.75 + i * 0.0001, 40.40 + i * 0.0001 + (i % 7) * 0.00003, 0) for i in range(1000)]


def _longest_url(ql):
    return max(m + "?data=" + urllib.parse.quote(ql) for m in MIRRORS)


def test_water_query_url_stays_short_enough_for_every_mirror():
    poly = route_polyline(_long_track())
    anchors = [Anchor("poi", "P", 40.40123 + i * 0.01, -3.74123 - i * 0.01) for i in range(POINT_MAX)]
    ql = water_query(poly, anchors)
    assert len(_longest_url(ql)) < 8000
    assert ql.count(poly) == 1


def test_cover_query_url_stays_short_enough_for_every_mirror():
    ql = cover_query(route_polyline(_long_track()))
    assert len(_longest_url(ql)) < 8000
    assert "[timeout:9]" in ql


def test_parse_ignores_matches_of_the_key_regex_that_are_not_water():
    data = {"elements": [_el({"leisure": "water"}, (1, 1, 2, 2)), _el({"natural": "river"}, (1, 1, 2, 2)),
                         _el({"waterway": "water"}, (1, 1, 2, 2)), _el({"leisure": "bathing_place"}, lat=1, lon=1)]}
    bodies, coast, spots = parse_water(data)
    assert bodies == [] and coast == [] and len(spots) == 1


def test_rect_distance_is_zero_inside_and_grows_outside():
    bbox = (40.0, -4.0, 40.1, -3.9)
    assert rect_distance_m(40.05, -3.95, bbox) == 0.0
    assert 8000 < rect_distance_m(40.05, -3.8, bbox) < 9000


def test_parse_classifies_kinds_and_sizes():
    data = {"elements": [
        _el({"natural": "water", "name": "Big lake"}, bounds=(40.0, -4.0, 40.1, -3.9)),
        _el({"natural": "water", "water": "pond"}, bounds=(40.0, -4.0, 40.001, -3.999)),
        _el({"waterway": "river", "name": "Rio Guadarrama"}, bounds=(40.0, -4.0, 40.02, -3.98)),
        _el({"waterway": "canal"}, bounds=(40.0, -4.0, 40.0, -3.99)),
        _el({"natural": "coastline"}, bounds=(36.0, -5.0, 36.1, -4.9)),
        _el({"leisure": "swimming_area", "name": "Playa"}, lat=36.05, lon=-4.95, type_="node"),
        _el({"natural": "water", "water": "reservoir", "name": "Embalse"}, bounds=(40.2, -4.0, 40.3, -3.9)),
    ]}
    bodies, coast, spots = parse_water(data)
    kinds = {b.name or b.kind: b.kind for b in bodies}
    assert kinds["Big lake"] == "lake" and kinds["pond"] == "pond" and kinds["Rio Guadarrama"] == "river"
    assert kinds["canal"] == "canal" and kinds["Embalse"] == "lake"
    assert len(coast) == 1 and spots == [("Playa", 36.05, -4.95)]
    big = next(b for b in bodies if b.name == "Big lake")
    assert 12 < big.size_km < 16                    # the bbox diagonal of 0.1 x 0.1 degrees


def test_parse_keeps_the_swimming_tags_and_merges_named_pieces():
    data = {"elements": [
        _el({"natural": "water", "name": "Lago", "swimming": "no"}, bounds=(40.0, -4.0, 40.1, -3.9)),
        _el({"natural": "water", "name": "Lago"}, bounds=(40.0, -4.0, 40.01, -3.99)),
    ]}
    bodies, _, _ = parse_water(data)
    assert len(bodies) == 1 and bodies[0].tags["swimming"] == "no" and bodies[0].size_km > 10


def test_place_names_what_the_water_is_near():
    lake = parse_water({"elements": [_el({"natural": "water", "name": "Lago"}, bounds=(40.0, -4.0, 40.01, -3.99))]})[0]
    anchors = [Anchor("track", "", 41.0, -3.0), Anchor("poi", "Mirador", 40.0105, -3.985)]
    placed = place_bodies(lake, anchors)
    assert placed[0].near_kind == "poi" and placed[0].near_name == "Mirador" and placed[0].distance_m < 500


def _ctx(make_route_with_points, fixed_now, http, points=()):
    return build_context(make_route_with_points(list(points)), DATE, http=http, now=fixed_now)


def test_plugin_finds_the_sea_and_the_lakes_and_caches(make_route_with_points, fixed_now):
    calls = []

    def http(url):
        calls.append(url)
        return {"elements": [
            _el({"natural": "coastline"}, bounds=(40.41, -3.76, 40.44, -3.73)),
            _el({"natural": "water", "name": "Lago"}, bounds=(40.425, -3.745, 40.427, -3.743)),
        ]}

    ctx = _ctx(make_route_with_points, fixed_now, http,
               [("Mirador", "viewpoint", -3.742, 40.428, {}), ("Cercedilla", "access", -3.75, 40.42, {"role": "start"})])
    section = WaterNearPlugin().run(ctx, {})
    assert section.omit and section.shared["error"] is None
    assert section.shared["sea"]["near_kind"] in ("track", "start", "poi", "access")
    assert [b.name for b in section.shared["bodies"]] == ["Lago"]
    # Check that the point of interest is in the query (URL-encoded as part of the around clause)
    assert "around:500,40.42800,-3.74200" in urllib.parse.unquote(calls[0])
    WaterNearPlugin().run(ctx, {})
    assert len(calls) == 1


def test_nothing_nearby_is_an_empty_result_not_an_error(make_route_with_points, fixed_now):
    section = WaterNearPlugin().run(_ctx(make_route_with_points, fixed_now, lambda u: {"elements": []}), {})
    assert section.shared == {"bodies": [], "sea": None, "swim_spots": [], "error": None, "truncated": False}


def test_overpass_failure_is_reported(make_route_with_points, fixed_now):
    def http(url):
        raise HttpError("503")

    section = WaterNearPlugin().run(_ctx(make_route_with_points, fixed_now, http), {})
    assert section.shared["error"] and section.shared["bodies"] == [] and section.confidence == "no-data"
    assert section.shared["truncated"] is False


def test_truncated_response_is_not_cached(make_route_with_points, fixed_now):
    from day_plan.plugins.water_near import ELEMENT_CAP
    calls = []

    def http(url):
        calls.append(url)
        # Return ELEMENT_CAP ponds to trigger truncation detection
        return {"elements": [_el({"natural": "water", "water": "pond"}, bounds=(40.425, -3.745, 40.427, -3.743))] * ELEMENT_CAP}

    ctx = _ctx(make_route_with_points, fixed_now, http,
               [("Mirador", "viewpoint", -3.742, 40.428, {}), ("Cercedilla", "access", -3.75, 40.42, {"role": "start"})])
    section = WaterNearPlugin().run(ctx, {})
    assert section.shared["truncated"] is True
    assert section.shared["error"] is None
    assert len(section.shared["bodies"]) > 0  # Data is still returned

    # Second call should fetch again (not cached because truncated)
    WaterNearPlugin().run(ctx, {})
    assert len(calls) == 2
