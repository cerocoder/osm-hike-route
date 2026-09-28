import re
from unittest.mock import patch

import pytest
import route_graph
from route_graph import (
    build_graph, fetch_area_data, filter_excluded_ways, tag_grades,
    _edge_cost, weighted_shortest_path, DEFAULT_ROUTABLE_HIGHWAY,
)


def _two_node_way(node_a=1, node_b=2, tags=None):
    return [{
        "nodes": [node_a, node_b],
        "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}],
        "tags": tags or {},
    }]


def test_two_way_segment_is_traversable_in_both_directions_by_default():
    graph, _ = build_graph(_two_node_way())

    neighbors_of_1 = [edge[0] for edge in graph[1]]
    neighbors_of_2 = [edge[0] for edge in graph[2]]

    assert 2 in neighbors_of_1
    assert 1 in neighbors_of_2


def test_oneway_segment_is_forward_only_when_respect_oneway_true():
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 not in [edge[0] for edge in graph.get(2, [])]


def test_oneway_ignored_when_respect_oneway_false():
    """walk mode: oneway restrictions never apply, even if the tag is present."""
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=False)

    assert 1 in [edge[0] for edge in graph.get(2, [])]


def test_oneway_bicycle_no_reopens_reverse_direction():
    way = _two_node_way(tags={"oneway": "yes", "oneway:bicycle": "no"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 in [edge[0] for edge in graph.get(2, [])]


def test_two_way_segment_is_traversable_in_both_directions_for_bike_mode():
    """Review Focus #5, bike-mode half: an untagged segment must stay
    bidirectional under respect_oneway=True too — only an explicit
    oneway=yes tag should restrict direction."""
    graph, _ = build_graph(_two_node_way(), respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 in [edge[0] for edge in graph.get(2, [])]


def _way_with_tags(tags, way_id=1):
    return {
        "id": way_id,
        "nodes": [1, 2],
        "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}],
        "tags": tags,
    }


def test_filter_excluded_ways_drops_hard_excluded_tag_for_bike():
    ways = [_way_with_tags({"highway": "path"}), _way_with_tags({"highway": "steps"}, way_id=2)]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 hard_exclude_tags={"highway": ["steps"]})

    assert [w["id"] for w in kept] == [1]


def test_filter_excluded_ways_drops_trunk_without_cycle_infra_for_bike():
    ways = [
        _way_with_tags({"highway": "trunk"}, way_id=1),
        _way_with_tags({"highway": "trunk", "cycleway": "track"}, way_id=2),
    ]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 exclude_highway_without_infra=["trunk"])

    assert [w["id"] for w in kept] == [2]


def test_filter_excluded_ways_keeps_everything_for_walk_with_no_rules():
    ways = [_way_with_tags({"highway": "trunk"}), _way_with_tags({"highway": "steps"}, way_id=2)]

    kept = filter_excluded_ways(ways, restricted_polygons=[])

    assert len(kept) == 2


def test_tag_grades_computes_signed_percent_grade():
    graph = {1: [[2, 100.0, {}]], 2: [[1, 100.0, {}]]}
    node_coords = {1: (55.0, 37.0), 2: (55.001, 37.0)}
    elevations = {1: 200.0, 2: 210.0}  # +10m over a 100m edge => +10%

    tag_grades(graph, node_coords, elevations)

    assert graph[1][0][2]["grade_pct"] == pytest.approx(10.0)
    assert graph[2][0][2]["grade_pct"] == pytest.approx(-10.0)


def test_edge_cost_penalizes_uphill_more_than_downhill_above_threshold():
    preferences = {"avoid_steep_gradient": 2.0, "gradient_threshold_pct": 8}

    uphill_cost = _edge_cost(100.0, {"grade_pct": 15.0}, preferences)
    downhill_cost = _edge_cost(100.0, {"grade_pct": -15.0}, preferences)
    flat_cost = _edge_cost(100.0, {"grade_pct": 2.0}, preferences)

    assert uphill_cost > flat_cost
    assert flat_cost <= downhill_cost < uphill_cost


def test_weighted_shortest_path_prefers_gentler_route_when_steep_is_penalized():
    # Two parallel paths from 1 to 3: a short steep one (1->2->3) and a
    # longer flat one (1->4->3).
    graph = {
        1: [[2, 50.0, {"grade_pct": 20.0}], [4, 60.0, {"grade_pct": 0.0}]],
        2: [[3, 50.0, {"grade_pct": 20.0}]],
        4: [[3, 60.0, {"grade_pct": 0.0}]],
        3: [],
    }
    preferences = {"avoid_steep_gradient": 5.0, "gradient_threshold_pct": 8}

    path, cost = weighted_shortest_path(graph, 1, 3, preferences)

    assert path == [1, 4, 3]


def _capture_ql(captured):
    def _fake_query_overpass(ql, *args, **kwargs):
        captured.append(ql)
        return {"elements": []}
    return _fake_query_overpass


def _walkable_clause_values(ql: str) -> set:
    """Extract the highway tag-value set from the FIRST way["highway"~"..."]
    clause (the .walkable set) in a fetch_area_data query string. Scoping to
    this specific clause (rather than substring-searching the whole query)
    avoids false positives from the fixed .highways avoidance clause, which
    always contains motorway|trunk|primary|secondary regardless of what
    fetch_area_data was actually asked to fetch as walkable."""
    match = re.search(r'way\["highway"~"([^"]+)"\]', ql)
    assert match, f"no walkable highway clause found in query: {ql!r}"
    return set(match.group(1).split("|"))


def test_fetch_area_data_no_args_uses_walk_default_tags_in_query():
    captured = []
    with patch.object(route_graph, "query_overpass", side_effect=_capture_ql(captured)):
        fetch_area_data(55.0, 37.0)

    # Set-equal to the old hardcoded default, not byte-identical: the new
    # implementation sorts the tag values alphabetically before joining,
    # so the substring order differs from the old literal
    # "path|footway|track|residential|living_street", but Overpass matches
    # on the same regex alternation regardless of order.
    assert _walkable_clause_values(captured[0]) == set(DEFAULT_ROUTABLE_HIGHWAY)


def test_fetch_area_data_preset_args_included_in_query():
    captured = []
    with patch.object(route_graph, "query_overpass", side_effect=_capture_ql(captured)):
        fetch_area_data(
            55.0, 37.0,
            routable_highway=["path", "cycleway", "secondary"],
            hard_exclude_highway=["steps"],
            exclude_highway_without_infra=["trunk", "primary"],
        )

    assert _walkable_clause_values(captured[0]) == {
        "path", "cycleway", "secondary", "steps", "trunk", "primary",
    }


def test_fetch_area_data_buckets_secondary_as_walkable_when_routable():
    ways = [{"type": "way", "id": 1, "tags": {"highway": "secondary"}}]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(55.0, 37.0, routable_highway=["path", "secondary"])

    assert [w["id"] for w in buckets["walkable"]] == [1]
    assert buckets["highways"] == []


def test_fetch_area_data_buckets_secondary_as_highway_under_walk_defaults():
    ways = [{"type": "way", "id": 1, "tags": {"highway": "secondary"}}]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(55.0, 37.0)

    assert buckets["walkable"] == []
    assert [w["id"] for w in buckets["highways"]] == [1]


def test_fetch_area_data_reaches_walkable_bucket_for_hard_exclude_and_infra_candidates():
    ways = [
        {"type": "way", "id": 1, "tags": {"highway": "steps"}},
        {"type": "way", "id": 2, "tags": {"highway": "trunk"}},
    ]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(
            55.0, 37.0,
            hard_exclude_highway=["steps"],
            exclude_highway_without_infra=["trunk"],
        )

    # Not asserting buckets["highways"] here: trunk overlaps the fixed
    # AVOIDANCE_HIGHWAY set too, and whether a trunk way used for bike's
    # infra-exclusion check should ALSO still land in the highways
    # avoidance-buffer bucket is a separate design question the task spec
    # doesn't settle (see task-21-report.md Concerns) — this test only
    # proves the way reaches filter_excluded_ways instead of being
    # silently dropped by the fetch itself.
    walkable_ids = [w["id"] for w in buckets["walkable"]]
    assert 1 in walkable_ids
    assert 2 in walkable_ids
