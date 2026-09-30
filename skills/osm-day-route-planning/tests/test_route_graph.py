import re
from unittest.mock import patch

import pytest
import route_graph
from route_graph import (
    build_graph, build_restricted_polygons, fetch_area_data, filter_excluded_ways,
    tag_grades, _edge_cost, weighted_shortest_path, DEFAULT_ROUTABLE_HIGHWAY,
)
from waypoints import is_point_restricted


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


def test_filter_excluded_ways_drops_trunk_with_cycleway_no_for_bike():
    """cycleway=no/none/separate mean 'no usable infra on this way' — must be
    excluded exactly like a trunk with no cycleway tag at all."""
    ways = [
        _way_with_tags({"highway": "trunk"}, way_id=1),
        _way_with_tags({"highway": "trunk", "cycleway": "no"}, way_id=2),
        _way_with_tags({"highway": "trunk", "cycleway": "none"}, way_id=3),
        _way_with_tags({"highway": "primary", "cycleway": "separate"}, way_id=4),
        _way_with_tags({"highway": "trunk", "cycleway:right": "no"}, way_id=5),
    ]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 exclude_highway_without_infra=["trunk", "primary"])

    assert kept == []


def test_filter_excluded_ways_keeps_trunk_with_positive_cycleway_value():
    ways = [_way_with_tags({"highway": "trunk", "cycleway": "track"}, way_id=1)]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 exclude_highway_without_infra=["trunk"])

    assert [w["id"] for w in kept] == [1]


def test_filter_excluded_ways_keeps_trunk_with_positive_cycleway_side_subkey():
    ways = [
        _way_with_tags({"highway": "trunk", "cycleway:right": "lane"}, way_id=1),
        _way_with_tags({"highway": "trunk", "cycleway:left": "no",
                        "cycleway:both": "lane"}, way_id=2),
    ]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 exclude_highway_without_infra=["trunk"])

    assert [w["id"] for w in kept] == [1, 2]


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


def test_fetch_area_data_buckets_routable_secondary_as_both_walkable_and_highway():
    """Walkable and highway-avoidance membership are independent: a routable
    secondary (bike-sport) must still feed tag_edges's near_highway buffer,
    or avoid_near_highway silently stops reacting to it."""
    ways = [{"type": "way", "id": 1, "tags": {"highway": "secondary"}}]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(55.0, 37.0, routable_highway=["path", "secondary"])

    assert [w["id"] for w in buckets["walkable"]] == [1]
    assert [w["id"] for w in buckets["highways"]] == [1]


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

    # The way must reach filter_excluded_ways (walkable) instead of being
    # silently dropped by the fetch itself — AND the trunk must also stay in
    # the highways avoidance bucket, so nearby paths still get the
    # near_highway penalty even though the trunk itself is later
    # hard-excluded from the routable graph.
    walkable_ids = [w["id"] for w in buckets["walkable"]]
    assert 1 in walkable_ids
    assert 2 in walkable_ids
    assert [w["id"] for w in buckets["highways"]] == [2]


# --- build_restricted_polygons: relations, ring stitching, closure -------

def _pts(*coords):
    return [{"lat": lat, "lon": lon} for lat, lon in coords]


# A square around (55.001, 37.0) — the midpoint _way_with_tags's 2-point
# geometry resolves to in filter_excluded_ways (geom[len // 2] == geom[1]).
_SW, _SE, _NE, _NW = (55.0005, 36.9995), (55.0005, 37.0005), (55.0015, 37.0005), (55.0015, 36.9995)
_INSIDE = (55.001, 37.0)
_OUTSIDE = (55.01, 37.01)


def _relation(members, tags=None):
    return {"type": "relation", "id": 900, "tags": tags or {"landuse": "military"},
            "members": members}


def _member(coords, role="outer", ref=1):
    return {"type": "way", "ref": ref, "role": role, "geometry": _pts(*coords)}


def test_relation_with_two_outer_members_is_stitched_into_one_polygon():
    # Two halves of the perimeter sharing endpoints; the second one is given
    # in reverse direction so the stitcher's reversal branch has to run.
    relation = _relation([
        _member([_SW, _SE, _NE], ref=1),
        _member([_SW, _NW, _NE], ref=2),  # reversed w.r.t. ring direction
    ])

    polygons = build_restricted_polygons([relation], [])

    assert len(polygons) == 1
    assert len(polygons[0]) == 4
    assert set(polygons[0]) == {_SW, _SE, _NE, _NW}
    assert is_point_restricted(*_INSIDE, polygons) is True
    assert is_point_restricted(*_OUTSIDE, polygons) is False


def test_relation_split_into_four_shuffled_segments_is_stitched():
    # No single member can form a polygon on its own — only correct
    # end-to-end stitching (with mixed directions, out of order) closes it.
    relation = _relation([
        _member([_NE, _NW], ref=3),
        _member([_SE, _SW], ref=1),   # reversed
        _member([_NW, _SW], ref=4),
        _member([_NE, _SE], ref=2),   # reversed
    ])

    polygons = build_restricted_polygons([relation], [])

    assert len(polygons) == 1
    assert set(polygons[0]) == {_SW, _SE, _NE, _NW}
    assert is_point_restricted(*_INSIDE, polygons) is True


def test_relation_restricted_area_excludes_walkable_way_inside_it():
    relation = _relation([
        _member([_SW, _SE, _NE], ref=1),
        _member([_NE, _NW, _SW], ref=2),
    ])
    polygons = build_restricted_polygons([relation], [])
    inside_way = _way_with_tags({"highway": "path"}, way_id=1)  # midpoint == _INSIDE
    outside_way = {"id": 2, "nodes": [3, 4], "tags": {"highway": "path"},
                   "geometry": _pts(_OUTSIDE, (_OUTSIDE[0] + 0.001, _OUTSIDE[1]))}

    kept = filter_excluded_ways([inside_way, outside_way], polygons)

    assert [w["id"] for w in kept] == [2]


def test_relation_single_closed_outer_member_and_inner_member_ignored():
    relation = _relation([
        _member([_SW, _SE, _NE, _NW, _SW], ref=1),
        # inner ring (a hole) — not part of the hard-exclusion outline
        _member([(55.0009, 36.9999), (55.0009, 37.0001), (55.0011, 37.0001),
                 (55.0011, 36.9999), (55.0009, 36.9999)], role="inner", ref=2),
    ])

    polygons = build_restricted_polygons([relation], [])

    assert len(polygons) == 1
    assert set(polygons[0]) == {_SW, _SE, _NE, _NW}


def test_relation_members_with_empty_or_missing_role_count_as_outer():
    """Older simple multipolygons often leave the outer ring's role blank
    ("" in Overpass output) — treat that like "outer", not as ignorable."""
    no_role_member = {"type": "way", "ref": 2, "geometry": _pts(_SW, _NW, _NE)}
    relation = _relation([
        _member([_SW, _SE, _NE], role="", ref=1),
        no_role_member,
    ])

    polygons = build_restricted_polygons([relation], [])

    assert len(polygons) == 1
    assert is_point_restricted(*_INSIDE, polygons) is True


def test_relation_with_unclosed_outer_members_produces_no_polygon():
    # Incomplete/malformed relation: three sides only, never closes.
    relation = _relation([
        _member([_SW, _SE], ref=1),
        _member([_SE, _NE], ref=2),
        _member([_NE, _NW], ref=3),
    ])

    polygons = build_restricted_polygons([relation], [])

    assert polygons == []


def test_relation_with_no_members_or_geometry_does_not_raise():
    polygons = build_restricted_polygons(
        [_relation([]), {"type": "relation", "id": 1, "tags": {}},
         _relation([{"type": "way", "ref": 1, "role": "outer"}])],
        [],
    )

    assert polygons == []


def test_open_access_private_way_is_not_treated_as_polygon():
    # e.g. a private driveway: a linear way, not an area — must not become
    # a (spurious triangle-ish) hard-exclusion polygon.
    driveway = {"type": "way", "id": 5, "tags": {"highway": "service", "access": "private"},
                "geometry": _pts(_SW, _SE, _NE)}

    polygons = build_restricted_polygons([driveway], [])

    assert polygons == []


def test_closed_access_private_way_is_still_a_polygon():
    area = {"type": "way", "id": 6, "tags": {"access": "private"},
            "geometry": _pts(_SW, _SE, _NE, _NW, _SW)}

    polygons = build_restricted_polygons([area], [])

    assert len(polygons) == 1
    assert is_point_restricted(*_INSIDE, polygons) is True


def test_barrier_ways_only_closed_rings_become_polygons():
    closed_fence = {"type": "way", "id": 7, "tags": {"barrier": "fence"},
                    "geometry": _pts(_SW, _SE, _NE, _NW, _SW)}
    open_fence = {"type": "way", "id": 8, "tags": {"barrier": "fence"},
                  "geometry": _pts(_SW, _SE, _NE)}

    polygons = build_restricted_polygons([], [closed_fence, open_fence])

    assert len(polygons) == 1


# --- fetch_area_data bucketing: explicit mode override on restricted ways -

_BIKE_DESIGNATED = {"type": "way", "id": 1, "tags": {"highway": "cycleway", "access": "no",
                                                     "bicycle": "designated"}}
_FOOT_YES = {"type": "way", "id": 2, "tags": {"highway": "path", "access": "private",
                                              "foot": "yes"}}
_OVERRIDE_ROUTABLE = ["path", "cycleway"]


def _bucket_with_mode(elements, mode):
    with patch.object(route_graph, "query_overpass", return_value={"elements": elements}):
        return fetch_area_data(55.0, 37.0, routable_highway=_OVERRIDE_ROUTABLE, mode=mode)


def test_fetch_area_data_bicycle_designated_exempt_only_for_bike_mode():
    buckets = _bucket_with_mode([_BIKE_DESIGNATED], mode="bike")

    assert buckets["restricted"] == []
    assert [w["id"] for w in buckets["walkable"]] == [1]


@pytest.mark.parametrize("mode", ["walk", None])
def test_fetch_area_data_bicycle_designated_still_restricted_for_walk_or_no_mode(mode):
    buckets = _bucket_with_mode([_BIKE_DESIGNATED], mode=mode)

    assert [w["id"] for w in buckets["restricted"]] == [1]
    assert buckets["walkable"] == []


def test_fetch_area_data_foot_yes_exempt_only_for_walk_mode():
    buckets = _bucket_with_mode([_FOOT_YES], mode="walk")

    assert buckets["restricted"] == []
    assert [w["id"] for w in buckets["walkable"]] == [2]


@pytest.mark.parametrize("mode", ["bike", None])
def test_fetch_area_data_foot_yes_still_restricted_for_bike_or_no_mode(mode):
    buckets = _bucket_with_mode([_FOOT_YES], mode=mode)

    assert [w["id"] for w in buckets["restricted"]] == [2]
    assert buckets["walkable"] == []


def test_fetch_area_data_restricted_area_with_foot_yes_stays_restricted_without_mode():
    """Default (mode=None, an old caller) is the strict pre-override
    behaviour: no exemption for any element, area or way."""
    reserve = {"type": "relation", "id": 3,
               "tags": {"leisure": "nature_reserve", "foot": "yes"}, "members": []}
    with patch.object(route_graph, "query_overpass", return_value={"elements": [reserve]}):
        buckets = fetch_area_data(55.0, 37.0)

    assert [w["id"] for w in buckets["restricted"]] == [3]


def test_fetch_area_data_plain_access_private_is_still_restricted():
    ways = [
        {"type": "way", "id": 1, "tags": {"highway": "path", "access": "private"}},
        {"type": "way", "id": 2, "tags": {"highway": "path", "access": "no",
                                          "bicycle": "no"}},
    ]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(55.0, 37.0)

    assert [w["id"] for w in buckets["restricted"]] == [1, 2]
    assert buckets["walkable"] == []


def test_fetch_area_data_non_highway_features_bucket_unchanged():
    ways = [
        {"type": "way", "id": 1, "tags": {"natural": "water"}},
        {"type": "way", "id": 2, "tags": {"landuse": "forest"}},
        {"type": "way", "id": 3, "tags": {"landuse": "meadow"}},
    ]
    with patch.object(route_graph, "query_overpass", return_value={"elements": ways}):
        buckets = fetch_area_data(55.0, 37.0)

    assert [w["id"] for w in buckets["water"]] == [1]
    assert [w["id"] for w in buckets["forest"]] == [2]
    assert [w["id"] for w in buckets["fields"]] == [3]
    assert buckets["walkable"] == [] and buckets["highways"] == []


def test_highway_avoidance_reaches_path_next_to_routable_secondary():
    """End-to-end for the bug: a path running alongside a (bike-sport
    routable) secondary gets near_highway=True from tag_edges."""
    # Mid node included: tag_edges measures distance to line vertices only.
    secondary = {"type": "way", "id": 10, "nodes": [10, 12, 11], "tags": {"highway": "secondary"},
                 "geometry": _pts((55.0, 37.0), (55.0005, 37.0), (55.001, 37.0))}
    path = {"type": "way", "id": 20, "nodes": [20, 21], "tags": {"highway": "path"},
            "geometry": _pts((55.0, 37.0002), (55.001, 37.0002))}  # ~13 m away
    with patch.object(route_graph, "query_overpass",
                      return_value={"elements": [secondary, path]}):
        data = fetch_area_data(55.0, 37.0, routable_highway=["path", "secondary"])
    graph, coords = build_graph([path])

    route_graph.tag_edges(graph, coords, data["highways"], data["water"],
                          data["forest"], data["fields"])

    assert graph[20][0][2]["near_highway"] is True


# ---- way tags kept for the archive (winter passability) -----------------------------------------------------------

def _three_way_chain():
    """Nodes 1-2-3-4 on three ways: a gravel track (1-2, 2-3) and an asphalt residential street (3-4)."""
    return [
        {"id": 100, "nodes": [1, 2, 3],
         "geometry": [{"lat": 55.000, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}, {"lat": 55.002, "lon": 37.0}],
         "tags": {"highway": "track", "surface": "gravel", "tracktype": "grade2", "name": "ignored", "lit": "yes"}},
        {"id": 200, "nodes": [3, 4],
         "geometry": [{"lat": 55.002, "lon": 37.0}, {"lat": 55.003, "lon": 37.0}],
         "tags": {"highway": "residential", "surface": "asphalt", "winter_service": "yes"}},
    ]


def test_edges_keep_a_compact_description_of_their_way():
    graph, _ = build_graph(_three_way_chain())

    edge = next(e for e in graph[1] if e[0] == 2)
    assert edge[2]["way"] == {"way_id": 100, "highway": "track", "surface": "gravel", "tracktype": "grade2"}
    edge = next(e for e in graph[4] if e[0] == 3)
    assert edge[2]["way"] == {"way_id": 200, "highway": "residential", "surface": "asphalt", "winter_service": "yes"}


def test_forward_and_reverse_edges_do_not_share_their_tag_dict():
    graph, coords = build_graph(_three_way_chain())
    forward = next(e for e in graph[1] if e[0] == 2)
    reverse = next(e for e in graph[2] if e[0] == 1)

    forward[2]["grade_pct"] = 5.0

    assert "grade_pct" not in reverse[2]


def test_tag_edges_keeps_the_way_description():
    graph, coords = build_graph(_three_way_chain())

    route_graph.tag_edges(graph, coords, [], [], [], [])

    edge = next(e for e in graph[2] if e[0] == 3)
    assert edge[2]["way"]["way_id"] == 100
    assert edge[2]["near_highway"] is False and edge[2]["landcover"] is None


def test_path_way_segments_merge_consecutive_edges_of_one_way():
    graph, _ = build_graph(_three_way_chain())

    segments = route_graph.path_way_segments(graph, [1, 2, 3, 4])

    assert segments == [
        {"from": 0, "to": 2, "way_id": 100, "highway": "track", "surface": "gravel", "tracktype": "grade2"},
        {"from": 2, "to": 3, "way_id": 200, "highway": "residential", "surface": "asphalt", "winter_service": "yes"},
    ]


def test_path_way_segments_cover_the_path_in_reverse_and_for_one_edge():
    graph, _ = build_graph(_three_way_chain())

    reverse = route_graph.path_way_segments(graph, [4, 3, 2, 1])
    assert [(s["from"], s["to"], s["way_id"]) for s in reverse] == [(0, 1, 200), (1, 3, 100)]
    single = route_graph.path_way_segments(graph, [1, 2])
    assert [(s["from"], s["to"]) for s in single] == [(0, 1)]
    assert route_graph.path_way_segments(graph, [1]) == []


def test_path_way_segments_use_the_shortest_of_parallel_edges_and_reject_a_broken_path():
    graph, _ = build_graph(_three_way_chain())
    graph[1].append([2, 5.0, {"way": {"way_id": 999, "highway": "path"}}])       # a much shorter parallel edge

    assert route_graph.path_way_segments(graph, [1, 2])[0]["way_id"] == 999
    with pytest.raises(ValueError, match="not connected"):
        route_graph.path_way_segments(graph, [1, 4])


def test_ways_without_tags_still_give_a_segment_with_only_the_id():
    graph, _ = build_graph([{"id": 7, "nodes": [1, 2],
                             "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}], "tags": {}}])

    assert route_graph.path_way_segments(graph, [1, 2]) == [{"from": 0, "to": 1, "way_id": 7}]


def test_path_geometry_returns_coordinates_and_segments_from_the_same_path():
    graph, coords = build_graph(_three_way_chain())

    path_coords, segments = route_graph.path_geometry(graph, [1, 2, 3, 4], coords, {1: 100.0, 2: 101.0, 4: 103.0})

    assert path_coords == [(37.0, 55.0, 100.0), (37.0, 55.001, 101.0), (37.0, 55.002, None), (37.0, 55.003, 103.0)]
    assert segments[0]["from"] == 0 and segments[-1]["to"] == len(path_coords) - 1



# ---- the grid index behind tag_edges must give the answers of a brute-force vertex scan ---------------------------------

def _brute_near(lat, lon, ways_geom, radius_m):
    from overpass_query import haversine
    return any(haversine(lat, lon, p["lat"], p["lon"]) < radius_m for coords in ways_geom for p in coords)


@pytest.mark.parametrize("lat0,lon0", [(55.79, 37.67), (0.0, 0.0), (69.6, 18.9), (-33.9, 151.2), (55.0, 179.99)])
def test_vertex_grid_agrees_with_a_brute_force_scan(lat0, lon0):
    import random
    rng = random.Random(7)
    ways = [[{"lat": lat0 + rng.uniform(-0.01, 0.01), "lon": lon0 + rng.uniform(-0.02, 0.02)} for _ in range(6)]
            for _ in range(40)]
    for radius in (30, 50):
        grid = route_graph._VertexGrid(ways, radius)
        for _ in range(400):
            lat, lon = lat0 + rng.uniform(-0.012, 0.012), lon0 + rng.uniform(-0.024, 0.024)
            assert grid.near(lat, lon) == _brute_near(lat, lon, ways, radius)


def test_vertex_grid_respects_the_radius_exactly_and_an_empty_set_is_never_near():
    from overpass_query import haversine
    vertex = {"lat": 56.0, "lon": 37.0}
    east = 0.001
    distance = haversine(56.0, 37.0, 56.0, 37.0 + east)
    grid = route_graph._VertexGrid([[vertex]], distance + 0.01)
    assert grid.near(56.0, 37.0 + east) and not route_graph._VertexGrid([[vertex]], distance - 0.01).near(56.0, 37.0 + east)
    assert route_graph._VertexGrid([], 50).near(56.0, 37.0) is False
