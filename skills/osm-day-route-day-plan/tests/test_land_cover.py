import datetime
import math

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.land_cover import (
    LandCoverPlugin, cover_query, cover_shares, densify, parse_polygons, route_polyline, ELEMENT_CAP,
)

DATE = datetime.date(2026, 6, 21)


def _square(lon0, lat0, lon1, lat1):
    return [{"lat": lat0, "lon": lon0}, {"lat": lat0, "lon": lon1}, {"lat": lat1, "lon": lon1},
            {"lat": lat1, "lon": lon0}, {"lat": lat0, "lon": lon0}]


def _way(kind_tag, ring):
    return {"type": "way", "id": 1, "tags": kind_tag, "geometry": ring}


def test_query_is_an_around_query_on_the_polyline():
    ql = cover_query("51.45,-0.2,51.55,-0.05")
    assert "around:30,51.45,-0.2,51.55,-0.05" in ql and "wood|scrub|grassland|heath" in ql
    assert "forest|meadow|grass|farmland" in ql and f"out tags geom {ELEMENT_CAP}" in ql


def test_densify_samples_along_the_distance_not_per_vertex():
    points = densify([(-0.20, 51.45, None), (-0.05, 51.55, None)], step_m=100, max_points=300)
    assert 100 < len(points) <= 300                       # a 15 km two-point line
    # Check endpoints with float tolerance
    assert abs(points[0][0] - 51.45) < 1e-9 and abs(points[0][1] - (-0.20)) < 1e-9
    assert abs(points[-1][0] - 51.55) < 1e-9 and abs(points[-1][1] - (-0.05)) < 1e-9


def test_densify_with_many_vertices_does_not_give_one_per_vertex():
    # Create a route with 2000 vertices over ~69 km (1 degree longitude at lat 51.45)
    # Old densify would create ~2000 points
    # New densify should create ~690 points (69km / 100m step)
    coords = [(-0.20 + i * 0.0005, 51.45, None) for i in range(2001)]

    points = densify(coords, step_m=100, max_points=1000)

    # Should have far fewer than 2000 points (not one per vertex)
    assert len(points) < 800  # much less than 2001 vertices
    assert len(points) > 600   # but expect roughly 690 for 69km

    # Verify endpoints are correct
    assert abs(points[0][0] - 51.45) < 1e-9
    assert abs(points[0][1] - (-0.20)) < 1e-6
    assert abs(points[-1][0] - 51.45) < 1e-9


def test_polyline_is_short_enough_for_a_url():
    coords = [(-0.2 + i * 0.001, 51.45, None) for i in range(1000)]
    assert len(route_polyline(coords).split(",")) <= 2 * 100


def test_forest_wins_over_open_ground_and_shares_are_fractions():
    forest = _way({"natural": "wood"}, _square(0.0, 0.0, 1.0, 1.0))
    meadow = _way({"landuse": "meadow"}, _square(0.0, 0.0, 2.0, 1.0))
    polygons = parse_polygons({"elements": [forest, meadow]})
    samples = [(0.5, 0.5), (0.5, 1.5), (0.5, 3.0), (0.5, 0.9)]       # forest, open, none, forest
    assert cover_shares(polygons, samples) == {"forest": 0.5, "open": 0.25}


def test_a_relation_with_a_hole_does_not_cover_the_hole():
    outer = {"type": "way", "role": "outer", "geometry": _square(0.0, 0.0, 4.0, 4.0)}
    inner = {"type": "way", "role": "inner", "geometry": _square(1.0, 1.0, 3.0, 3.0)}
    relation = {"type": "relation", "id": 9, "tags": {"natural": "wood"}, "members": [outer, inner]}
    polygons = parse_polygons({"elements": [relation]})
    assert cover_shares(polygons, [(2.0, 2.0), (0.5, 0.5)]) == {"forest": 0.5, "open": 0.0}


def test_an_outer_ring_split_in_two_ways_is_stitched():
    ring = _square(0.0, 0.0, 2.0, 2.0)
    first = {"type": "way", "role": "outer", "geometry": ring[:3]}
    second = {"type": "way", "role": "outer", "geometry": ring[2:]}
    relation = {"type": "relation", "id": 9, "tags": {"landuse": "forest"}, "members": [first, second]}
    assert cover_shares(parse_polygons({"elements": [relation]}), [(1.0, 1.0)]) == {"forest": 1.0, "open": 0.0}


def test_malformed_geometry_is_ignored_without_a_crash():
    broken = [
        _way({"natural": "wood"}, _square(0, 0, 1, 1)[:3]),                                # not closed
        {"type": "relation", "tags": {"natural": "wood"}, "members": []},                  # no members
        {"type": "relation", "tags": {"natural": "wood"},
         "members": [{"type": "way", "role": "inner", "geometry": _square(0, 0, 1, 1)}]},  # inner only
        {"type": "node", "tags": {"natural": "wood"}, "lat": 1, "lon": 1},
        {"type": "way", "tags": {"natural": "beach"}, "geometry": _square(0, 0, 1, 1)},    # not a cover kind
    ]
    assert parse_polygons({"elements": broken}) == []


def _ctx(make_route, fixed_now, http):
    return build_context(make_route(), DATE, http=http, now=fixed_now)


def test_plugin_reports_the_share_and_caches_it(make_route, fixed_now):
    calls = []
    forest = _way({"natural": "wood"}, _square(-0.3, 51.4, 0.0, 51.6))

    def http(url):
        calls.append(url)
        return {"elements": [forest]}

    ctx = _ctx(make_route, fixed_now, http)
    section = LandCoverPlugin().run(ctx, {})
    assert section.omit and section.shared["known"] and section.shared["forest"] == 1.0
    assert section.shared["total"] == 1.0
    LandCoverPlugin().run(ctx, {})
    assert len(calls) == 1                                  # the second run is served from the cache


def test_a_beach_route_has_no_cover(make_route, fixed_now):
    section = LandCoverPlugin().run(_ctx(make_route, fixed_now, lambda url: {"elements": []}), {})
    assert section.shared["known"] is True and section.shared["total"] == 0.0


def test_an_overpass_failure_is_unknown_not_zero(make_route, fixed_now):
    def http(url):
        raise HttpError("503")

    section = LandCoverPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert section.shared["known"] is False and section.shared["error"]


def test_truncated_response_is_unknown_and_not_cached(make_route, fixed_now):
    calls = []
    forest = _way({"natural": "wood"}, _square(-0.3, 51.4, 0.0, 51.6))

    def http(url):
        calls.append(url)
        # Return ELEMENT_CAP polygons to trigger truncation detection
        return {"elements": [forest] * ELEMENT_CAP}

    ctx = _ctx(make_route, fixed_now, http)
    section = LandCoverPlugin().run(ctx, {})
    assert section.shared["known"] is False
    assert "truncated" in section.shared["error"]
    assert section.shared["total"] == 0.0

    # Second call should fetch again (not cached)
    section2 = LandCoverPlugin().run(ctx, {})
    assert len(calls) == 2
    assert section2.shared["known"] is False
