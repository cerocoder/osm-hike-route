import pytest
from waypoints import (
    is_point_restricted, validate_user_waypoint, RestrictedWaypointError,
    BudgetExceededError, check_mandatory_budget, select_optional_points
)

_SQUARE_RING = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
_ASYMMETRIC_RING = [(0.0, 0.0), (0.0, 3.0), (1.0, 3.0), (1.0, 0.0)]  # lat in [0,1], lon in [0,3]


def test_is_point_restricted_true_when_inside_polygon():
    assert is_point_restricted(0.5, 0.5, [_SQUARE_RING]) is True


def test_is_point_restricted_false_when_outside_all_polygons():
    assert is_point_restricted(5.0, 5.0, [_SQUARE_RING]) is False


def test_is_point_restricted_false_when_no_polygons():
    assert is_point_restricted(0.5, 0.5, []) is False


def test_validate_user_waypoint_raises_with_point_name_in_message():
    with pytest.raises(RestrictedWaypointError) as exc_info:
        validate_user_waypoint(0.5, 0.5, "Военная часть", [_SQUARE_RING])

    assert "Военная часть" in str(exc_info.value)


def test_validate_user_waypoint_passes_silently_when_outside():
    validate_user_waypoint(5.0, 5.0, "Смотровая площадка", [_SQUARE_RING])  # no exception


def test_is_point_restricted_detects_lat_lon_argument_order_correctly():
    # Inside the ring: lat=0.5 (within [0,1]), lon=2.0 (within [0,3])
    assert is_point_restricted(0.5, 2.0, [_ASYMMETRIC_RING]) is True
    # Same numbers, swapped: lat=2.0 is outside [0,1] even though lon=0.5 is inside [0,3]
    assert is_point_restricted(2.0, 0.5, [_ASYMMETRIC_RING]) is False


def test_check_mandatory_budget_raises_when_already_over_budget():
    with pytest.raises(BudgetExceededError):
        check_mandatory_budget(mandatory_cost_km=12.0, max_distance_km=10.0)


def test_check_mandatory_budget_passes_when_no_budget_set():
    check_mandatory_budget(mandatory_cost_km=999.0, max_distance_km=None)  # no exception


def test_check_mandatory_budget_passes_when_within_budget():
    check_mandatory_budget(mandatory_cost_km=8.0, max_distance_km=10.0)  # no exception


def _linear_graph():
    """1 -- 2 -- 3 is the mandatory path (2km total); node 4 sits 0.1km
    off node 2, node 5 sits 5km off node 3 (too far to afford)."""
    return {
        1: [[2, 1000.0, {}]], 2: [[1, 1000.0, {}], [3, 1000.0, {}], [4, 100.0, {}]],
        3: [[2, 1000.0, {}], [5, 5000.0, {}]], 4: [[2, 100.0, {}]], 5: [[3, 5000.0, {}]],
    }


def test_select_optional_points_includes_cheap_candidate_within_budget():
    graph = _linear_graph()
    candidates = [{"node_id": 4, "name": "Родник", "tier": "tag-backed"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=2.5,
    )

    assert [c["name"] for c in included] == ["Родник"]
    assert skipped == []


def test_select_optional_points_skips_candidate_that_would_exceed_budget():
    graph = _linear_graph()
    candidates = [{"node_id": 5, "name": "Дальний вид", "tier": "web-sourced"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=3.0,
    )

    assert included == []
    assert skipped == ["Дальний вид"]


def test_select_optional_points_prefers_tag_backed_on_tied_cost():
    graph = _linear_graph()
    candidates = [
        {"node_id": 4, "name": "Веб-точка", "tier": "web-sourced"},
    ]
    # Only one affordable slot conceptually tested via budget; tie-break
    # ordering itself is exercised by sorting two equal-cost candidates.
    graph[2].append([6, 100.0, {}])
    graph[6] = [[2, 100.0, {}]]
    candidates.append({"node_id": 6, "name": "OSM-точка", "tier": "tag-backed"})

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=2.25,
    )

    # Budget only fits one 0.2km round-trip detour; tag-backed wins the tie.
    assert [c["name"] for c in included] == ["OSM-точка"]


def test_select_optional_points_handles_single_node_mandatory_path():
    """A bare loop with no mandatory point besides the access point yet —
    the only possible insertion is a there-and-back detour."""
    graph = {1: [[2, 100.0, {}]], 2: [[1, 100.0, {}]]}
    candidates = [{"node_id": 2, "name": "Рядом", "tier": "tag-backed"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1], mandatory_cost_km=0.0,
        candidates=candidates, preferences={}, max_distance_km=1.0,
    )

    assert [c["name"] for c in included] == ["Рядом"]
    assert skipped == []
