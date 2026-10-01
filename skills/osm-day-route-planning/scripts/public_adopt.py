"""Adopting a public route: its track becomes a path on the planner's graph, so that everything after it (elevation,
way segments, duration, budget check, restricted zones, notes, map) works as for a built route.

The track is resampled every RESAMPLE_M metres, each sample is snapped to the nearest graph node within SNAP_M,
and consecutive nodes are connected by the planner's own router. Points the user adds are inserted at the cheapest
place of the ordered nodes. How closely the result follows the public route is measured (`fidelity`) and reported.
"""
import math
from collections import defaultdict

from elevation.resample import sample_positions
from overpass_query import haversine
from progress import NullProgress
from route_graph import _VertexGrid, shortest_costs, weighted_shortest_path

RESAMPLE_M = 100.0
SNAP_M = 60.0
FIDELITY_M = 30.0
COVERAGE_M = 60.0                        # a track sample is covered when the path has a node this close
FIDELITY_WARN = 0.9
DENSIFY_M = 10.0
NEAR_WAYPOINTS = 4
_CELL = 0.0006                           # about 66 m of latitude


class AdoptionError(Exception):
    """The route cannot be followed on the graph; the message says why."""


class NodeIndex:
    """Nearest graph node to a point within a radius (a spatial hash of the node coordinates)."""

    def __init__(self, node_coords: dict, nodes=None):
        items = [(n, node_coords[n]) for n in (nodes if nodes is not None else node_coords)]
        mean_lat = sum(c[0] for _, c in items) / len(items) if items else 0.0
        self._cell_lat = _CELL
        self._cell_lon = _CELL / max(0.05, math.cos(math.radians(mean_lat)))
        self._cells = defaultdict(list)
        for node, (lat, lon) in items:
            self._cells[self._key(lat, lon)].append((node, lat, lon))

    def _key(self, lat, lon):
        return math.floor(lat / self._cell_lat), math.floor(lon / self._cell_lon)

    def nearest(self, lat, lon, max_m: float = SNAP_M):
        row, col = self._key(lat, lon)
        best = None
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                for node, n_lat, n_lon in self._cells.get((row + d_row, col + d_col), ()):
                    distance = haversine(lat, lon, n_lat, n_lon)
                    if distance <= max_m and (best is None or distance < best[0]):
                        best = (distance, node)
        return best[1] if best else None


def _route(graph, waypoints, preferences, progress):
    """(path, nodes skipped): like route_through_waypoints, but a waypoint that cannot be reached from the previous
    one is skipped (a way that is missing from the graph) instead of failing the whole route."""
    path, skipped = [waypoints[0]], 0
    current = waypoints[0]
    legs = len(waypoints) - 1
    for done, target in enumerate(waypoints[1:], start=1):
        segment, _cost = weighted_shortest_path(graph, current, target, preferences)
        if segment is None:
            skipped += 1
            continue
        path.extend(segment[1:])
        current = target
        progress.tick(done, legs, "route_leg")
    return path, skipped


def _insert(waypoints, node, graph, node_coords, preferences):
    """The waypoint list with `node` inserted where the detour is cheapest, looked for between the neighbours of
    the NEAR_WAYPOINTS waypoints nearest to it. Raises AdoptionError when it cannot be reached."""
    lat, lon = node_coords[node]
    nearest = sorted(range(len(waypoints)), key=lambda i: haversine(lat, lon, *node_coords[waypoints[i]]))[:NEAR_WAYPOINTS]
    pairs = sorted({(i - 1, i) for i in nearest if i > 0} | {(i, i + 1) for i in nearest if i + 1 < len(waypoints)})
    if not pairs:                                                        # a single waypoint: a there-and-back
        pairs = [(0, 0)]
    best = None
    for i, j in pairs:
        a, b = waypoints[i], waypoints[j]
        from_a = shortest_costs(graph, a, preferences, {node, b})
        from_node = shortest_costs(graph, node, preferences, {b})
        if from_a[node] is None or from_node[b] is None:
            continue
        detour = from_a[node] + from_node[b] - (from_a[b] or 0.0)
        if best is None or detour < best[0]:
            best = (detour, j)
    if best is None:
        raise AdoptionError("an added point cannot be reached from the route")
    return waypoints[:best[1]] + [node] + waypoints[best[1]:]


def adopt(candidate: dict, graph: dict, node_coords: dict, preferences: dict, extra_nodes=(), progress=None,
          index: NodeIndex | None = None) -> dict:
    """{"path": [node ids], "fidelity": the smaller of precision and coverage, "precision": the share of the path
    within FIDELITY_M of the public track, "coverage": the share of the track (sampled every RESAMPLE_M) with a path
    node within COVERAGE_M, "deviates": fidelity below FIDELITY_WARN, "dropped_samples": samples with no node (or no
    road) near, "inserted": the added nodes that are on the path}. `extra_nodes` are graph nodes of the user's own
    points, in the order given. Precision alone would call a route that was cut short "faithful", so a path that
    covers only part of the track has a low fidelity. Raises AdoptionError for a route with real gaps, one that is not
    on the graph, or one that could not be followed beyond its first node."""
    progress = progress or NullProgress()
    if candidate.get("gaps"):
        raise AdoptionError("the route has gaps: it cannot be followed as one line")
    index = index or NodeIndex(node_coords, nodes=graph)
    samples = sample_positions(candidate["track"], RESAMPLE_M)
    waypoints, dropped = [], 0
    for lat, lon, _distance in samples:
        node = index.nearest(lat, lon, SNAP_M)
        if node is None:
            dropped += 1
        elif not waypoints or waypoints[-1] != node:
            waypoints.append(node)
    if len(waypoints) < 2:
        raise AdoptionError("the route is not on the graph (no roads of this mode near it)")
    for node in extra_nodes:
        waypoints = _insert(waypoints, node, graph, node_coords, preferences)
    path, skipped = _route(graph, waypoints, preferences, progress)
    if len(path) < 2:
        raise AdoptionError("the route could not be followed on the graph (its start is cut off from the rest)")
    track_points = [{"lat": lat, "lon": lon} for lat, lon, _ in sample_positions(candidate["track"], DENSIFY_M)]
    track_grid = _VertexGrid([track_points], FIDELITY_M)
    precision = sum(1 for node in path if track_grid.near(*node_coords[node])) / len(path)
    path_grid = _VertexGrid([[{"lat": node_coords[n][0], "lon": node_coords[n][1]} for n in path]], COVERAGE_M)
    coverage = sum(1 for lat, lon, _ in samples if path_grid.near(lat, lon)) / len(samples)
    fidelity = min(precision, coverage)
    on_path = set(path)
    return {"path": path, "fidelity": round(fidelity, 3), "precision": round(precision, 3),
            "coverage": round(coverage, 3), "deviates": fidelity < FIDELITY_WARN,
            "dropped_samples": dropped + skipped, "inserted": [n for n in extra_nodes if n in on_path]}


def curated_source(candidate: dict, fidelity: float) -> dict:
    """The `curated_source` property of route.geojson: where the route came from. The website is kept only when it
    is an http(s) link; everything else is plain text from OSM."""
    tags = candidate.get("tags") or {}
    website = tags.get("website")
    return {"relation_id": candidate["id"], "name": tags.get("name"), "ref": tags.get("ref"),
            "network": candidate.get("network"), "operator": tags.get("operator"),
            "website": website if isinstance(website, str) and website.startswith(("http://", "https://")) else None,
            "length_source": candidate.get("length_source"), "fidelity": math.floor(fidelity * 100) / 100}
