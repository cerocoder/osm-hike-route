"""Waypoint-level checks that run BEFORE the graph is built (spec §3.4):
a restricted-zone hit here must become an explicit message, never a
silent 'no path found' surfaced later from the router."""
from route_graph import point_in_ring, weighted_shortest_path


class RestrictedWaypointError(Exception):
    pass


def is_point_restricted(lat: float, lon: float, restricted_polygons: list) -> bool:
    return any(point_in_ring(lat, lon, ring) for ring in restricted_polygons)


def validate_user_waypoint(lat: float, lon: float, name: str, restricted_polygons: list) -> None:
    """Raises for a USER-supplied point (spec §3.4: 'скилл прямо сообщает
    пользователю, что не может построить маршрут через эту точку, и
    почему'). A skill-CHOSEN candidate should be filtered out with
    is_point_restricted before ever reaching this function — see SKILL.md."""
    if is_point_restricted(lat, lon, restricted_polygons):
        raise RestrictedWaypointError(
            f"Не могу построить маршрут через точку «{name}» — она находится "
            "в закрытой/охраняемой зоне (военный объект, частная территория "
            "или огороженный периметр)."
        )


_TIER_RANK = {"tag-backed": 0, "web-sourced": 1, "derived": 2, "no-data": 3}


class BudgetExceededError(Exception):
    pass


def check_mandatory_budget(mandatory_cost_km: float, max_distance_km: float | None) -> None:
    if max_distance_km is not None and mandatory_cost_km > max_distance_km:
        raise BudgetExceededError(
            f"Маршрут только по обязательным точкам уже {mandatory_cost_km:.1f} км — "
            f"это больше заданного ограничения {max_distance_km:.1f} км. "
            "Увеличьте бюджет или откажитесь от одной из обязательных точек."
        )


def _cheapest_insertion_cost_km(graph, path: list[int], candidate_node: int, preferences: dict) -> float:
    """Cost (km) of visiting candidate_node via the cheapest detour between
    any two consecutive nodes already in `path`. When `path` has a single
    node (a bare loop with no other mandatory point yet), the only
    'insertion' possible is a there-and-back detour off that one node."""
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


def select_optional_points(graph, mandatory_path: list[int], mandatory_cost_km: float,
                            candidates: list[dict], preferences: dict,
                            max_distance_km: float | None):
    """Greedy cheapest-insertion selection under a distance budget (spec
    §3.5 step 3). Candidates unreachable from the mandatory path are
    treated as skipped, same as ones that don't fit the budget."""
    if max_distance_km is None:
        remaining_budget = float("inf")
    else:
        remaining_budget = max_distance_km - mandatory_cost_km

    scored = []
    skipped = []
    for candidate in candidates:
        cost_km = _cheapest_insertion_cost_km(graph, mandatory_path, candidate["node_id"], preferences)
        if cost_km is None:
            skipped.append(candidate["name"])
        else:
            scored.append((cost_km, _TIER_RANK.get(candidate.get("tier"), 99), candidate))
    scored.sort(key=lambda item: (item[0], item[1]))

    included = []
    for cost_km, _rank, candidate in scored:
        if cost_km <= remaining_budget:
            included.append(candidate)
            remaining_budget -= cost_km
        else:
            skipped.append(candidate["name"])
    return included, skipped
