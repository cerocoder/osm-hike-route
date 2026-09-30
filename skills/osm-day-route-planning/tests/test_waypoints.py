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
    assert skipped == ["Веб-точка"]


def test_select_optional_points_handles_duplicate_names_with_reachable_and_unreachable():
    """Two candidates share the same name "Родник" (common for unnamed OSM springs).
    One is reachable (node 4 off node 2), one is unreachable (node 7 isolated).
    The reachable one should be included, the unreachable one should be in skipped,
    and both should appear in returned lists (no name-based deduplication bug)."""
    graph = _linear_graph()
    # Add isolated node 7 with no connections (unreachable)
    graph[7] = []

    candidates = [
        {"node_id": 4, "name": "Родник", "tier": "tag-backed"},     # reachable
        {"node_id": 7, "name": "Родник", "tier": "tag-backed"},     # unreachable
    ]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=2.5,
    )

    # The reachable one fits the budget and should be included
    assert len(included) == 1
    assert included[0]["node_id"] == 4
    # The unreachable one should be tracked in skipped by name
    assert "Родник" in skipped
    # Verify the unreachable candidate is explicitly tracked (not silently dropped)
    assert skipped.count("Родник") == 1  # only one "Родник" in skipped (the unreachable one)


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


# ---- the one-search-per-source selection gives the answers of the original three-searches-per-pair one -----------------

import random

import route_graph
from waypoints import _TIER_RANK


def _random_directed_graph(seed, nodes=40, edges=110):
    rng = random.Random(seed)
    graph = {i: [] for i in range(nodes + 3)}                     # the last three nodes stay isolated
    for _ in range(edges):
        a, b = rng.sample(range(nodes), 2)
        length = rng.uniform(20, 400)
        graph[a].append([b, length, {"grade_pct": rng.uniform(-15, 15), "landcover": rng.choice([None, "forest", "field"])}])
        if rng.random() < 0.7:                                    # mostly two-way, sometimes one-way
            graph[b].append([a, length, {"grade_pct": rng.uniform(-15, 15), "near_highway": rng.random() < 0.2}])
    return graph, rng


PREFS = {"prefer_forest": 2.0, "avoid_open_field": 1.5, "avoid_near_highway": 2.0, "gradient_threshold_pct": 8,
         "avoid_steep_gradient": 2.0}


def _original_cheapest_insertion_cost_km(graph, path, candidate_node, preferences):
    from route_graph import weighted_shortest_path
    if len(path) == 1:
        _, there = weighted_shortest_path(graph, path[0], candidate_node, preferences)
        return None if there is None else 2 * there / 1000.0
    best = None
    for a, b in zip(path, path[1:]):
        _, cost_to = weighted_shortest_path(graph, a, candidate_node, preferences)
        _, cost_from = weighted_shortest_path(graph, candidate_node, b, preferences)
        _, direct = weighted_shortest_path(graph, a, b, preferences)
        if cost_to is None or cost_from is None:
            continue
        direct = direct or 0.0
        detour = (cost_to + cost_from - direct) / 1000.0
        if best is None or detour < best:
            best = detour
    return best


def _original_select(graph, path, mandatory_cost_km, candidates, preferences, max_distance_km):
    remaining = float("inf") if max_distance_km is None else max_distance_km - mandatory_cost_km
    scored, skipped = [], []
    for candidate in candidates:
        cost = _original_cheapest_insertion_cost_km(graph, path, candidate["node_id"], preferences)
        if cost is None:
            skipped.append(candidate["name"])
        else:
            scored.append((cost, _TIER_RANK.get(candidate.get("tier"), 99), candidate))
    scored.sort(key=lambda item: (item[0], item[1]))
    included = []
    for cost, _rank, candidate in scored:
        if cost <= remaining:
            included.append(candidate)
            remaining -= cost
        else:
            skipped.append(candidate["name"])
    return included, skipped


@pytest.mark.parametrize("seed", range(6))
def test_select_optional_points_agrees_with_the_original_search_per_pair(seed):
    graph, rng = _random_directed_graph(seed)
    path_length = [1, 2, 3, 6, 6, 4][seed]
    path = [rng.randrange(40) for _ in range(path_length)]
    if seed == 5:
        path = path + [path[0]]                                   # a loop: the start repeats
    candidates = [{"name": f"c{i}", "node_id": rng.choice(list(range(40)) + [40, 41, 42]),
                   "tier": rng.choice(["tag-backed", "web-sourced", None])} for i in range(12)]
    candidates[0]["node_id"] = 41                                 # an isolated node: always unreachable
    for budget in (None, 3.0, 8.0):
        expected = _original_select(graph, path, 1.0, candidates, PREFS, budget)
        assert "c0" in expected[1]
        assert select_optional_points(graph, path, 1.0, candidates, PREFS, budget) == expected


def test_shortest_costs_equals_weighted_shortest_path_for_every_target():
    graph, rng = _random_directed_graph(11)
    start = 3
    everything = route_graph.shortest_costs(graph, start, PREFS)
    assert everything[start] == 0.0
    subset = set(rng.sample(range(43), 15)) | {start, 41}
    costs = route_graph.shortest_costs(graph, start, PREFS, subset)
    assert set(costs) == subset and costs[start] == 0.0 and costs[41] is None        # 41 is isolated
    for target in subset:
        _, expected = route_graph.weighted_shortest_path(graph, start, target, PREFS)
        assert costs[target] == expected
        assert everything.get(target) == expected


def test_select_optional_points_ticks_once_per_search():
    graph, rng = _random_directed_graph(2)

    class Recorder:
        def __init__(self):
            self.ticks = []

        def tick(self, done, total, key="tag_progress", **params):
            self.ticks.append((done, total, key))

    recorder = Recorder()
    candidates = [{"name": f"c{i}", "node_id": n} for i, n in enumerate([5, 6, 7])]
    select_optional_points(graph, [1, 2, 1], 1.0, candidates, PREFS, None, progress=recorder)
    assert recorder.ticks == [(1, 5, "optional_run"), (2, 5, "optional_run"), (3, 5, "optional_run"),
                              (4, 5, "optional_run"), (5, 5, "optional_run")]       # 2 distinct path nodes + 3 candidates
