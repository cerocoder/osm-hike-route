import math

import pytest

from day_plan.geo import (
    bboxes_close, clip_segments, point_in_ring, point_segment_distance, polygon_distance, polyline_distance, project,
    segment_segment_distance, segments_distance, segments_intersect, to_segments,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]


def test_project_gives_kilometres_and_shrinks_longitude_with_latitude():
    x, y = project(11.0, 60.0, 60.0, 10.0)
    assert x == pytest.approx(111.195 * 0.5, rel=1e-3) and y == 0.0
    assert project(10.0, 61.0, 60.0, 10.0) == pytest.approx((0.0, 111.195))


def test_project_wraps_at_the_antimeridian():
    x, _ = project(-179.5, 0.0, 0.0, 179.5)
    assert x == pytest.approx(111.195, rel=1e-3)


def test_point_in_ring_inside_outside_and_concave():
    assert point_in_ring(5, 5, SQUARE) and not point_in_ring(11, 5, SQUARE) and not point_in_ring(5, -1, SQUARE)
    u_shape = [(0, 0), (9, 0), (9, 9), (6, 9), (6, 3), (3, 3), (3, 9), (0, 9), (0, 0)]
    assert point_in_ring(1, 5, u_shape) and point_in_ring(8, 5, u_shape) and not point_in_ring(4.5, 6, u_shape)


def test_segments_intersect_crossing_disjoint_and_parallel():
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert not segments_intersect((0, 0), (1, 0), (2, 0), (3, 0))
    assert not segments_intersect((0, 0), (10, 0), (0, 1), (10, 1))


def test_segment_distances():
    assert point_segment_distance(5, 3, 0, 0, 10, 0) == 3.0
    assert point_segment_distance(-4, 3, 0, 0, 10, 0) == 5.0                  # beyond the end: distance to the endpoint
    assert segment_segment_distance((0, 0), (10, 0), (0, 4), (10, 4)) == 4.0
    assert segment_segment_distance((0, 0), (10, 10), (0, 10), (10, 0)) == 0.0


def test_a_single_segment_crossing_a_polygon_with_both_ends_outside_touches_it():
    assert polygon_distance([(-5.0, 5.0), (15.0, 5.0)], SQUARE) == 0.0


def test_a_route_beside_a_polygon_gets_the_distance_to_its_edge_and_a_cap_gives_infinity():
    assert polygon_distance([(13.0, 2.0), (13.0, 8.0)], SQUARE) == pytest.approx(3.0)
    assert polygon_distance([(13.0, 2.0), (13.0, 8.0)], SQUARE, cap=2.0) == math.inf


def test_a_route_entirely_inside_a_polygon_is_zero():
    assert polygon_distance([(2.0, 2.0), (3.0, 3.0)], SQUARE) == 0.0


def test_polyline_distance_with_a_single_point_and_a_cap():
    assert polyline_distance([(0.0, 5.0)], [(3.0, 0.0), (3.0, 10.0)]) == pytest.approx(3.0)
    assert polyline_distance([(0.0, 5.0)], [(30.0, 0.0), (30.0, 10.0)], cap=5.0) == math.inf


def test_clip_segments_keeps_only_segments_near_the_box():
    segments = to_segments([(0, 0), (1, 0), (50, 0), (51, 0)])
    kept = clip_segments(segments, (0.0, -1.0, 2.0, 1.0), margin=1.0)
    assert kept == [((0, 0), (1, 0)), ((1, 0), (50, 0))]                       # the last one is 48 km away


def test_bboxes_close_uses_a_margin_in_km():
    a, b = (0.0, 0.0, 1.0, 1.0), (1.02, 0.0, 2.0, 1.0)
    assert bboxes_close(a, b, 3.0) and not bboxes_close(a, b, 0.5)
    assert not bboxes_close(a, (5.0, 5.0, 6.0, 6.0), 10.0)


def test_segments_distance_of_two_crossing_sets_is_zero():
    assert segments_distance(to_segments([(0, 0), (10, 10)]), to_segments([(0, 10), (10, 0)])) == 0.0
