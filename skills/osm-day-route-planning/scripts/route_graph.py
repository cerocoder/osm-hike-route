#!/usr/bin/env python3
"""Build a preference-weighted walking graph from Overpass data and route
through it. Standard-library only (uses overpass_query.py for fetching
and haversine).

Typical flow:
    from overpass_query import query_overpass
    from route_graph import fetch_area_data, build_restricted_polygons, \
        filter_excluded_ways, build_graph, tag_edges, \
        weighted_shortest_path, route_through_waypoints

    data = fetch_area_data(lat, lon, radius_m=2000)
    restricted = build_restricted_polygons(data['restricted'], data['barrier_ways'])
    walkable = filter_excluded_ways(data['walkable'], restricted)
    graph, node_coords = build_graph(walkable, data['barrier_nodes'])
    tag_edges(graph, node_coords, data['highways'], data['water'],
              data['forest'], data['fields'])
    path, cost = weighted_shortest_path(graph, start_id, end_id, preferences)

Access/barrier exclusion is hard, not weighted: a way inside a fenced or
access=private/no/military polygon is dropped entirely, and an edge
through a locked/walled barrier node is dropped — the router can't route
through them at all, not just prefer not to.
"""
import heapq
import math

from overpass_query import query_overpass, haversine


RESTRICTED_ACCESS = ("private", "no", "military")


def fetch_area_data(lat: float, lon: float, radius_m: int = 2000) -> dict:
    """One combined Overpass query for everything build_graph/tag_edges/
    exclusion need: walkable ways, highways (for avoidance), water,
    forest, fields, plus access-restricted ways, military land, barrier
    ways (fence/wall — used to detect enclosed private zones), and
    barrier nodes (gates etc. sitting on a path).
    Radius-limited on purpose — see reference.md on Overpass timeouts."""
    ql = f"""
    [out:json][timeout:80];
    (
      way["highway"~"path|footway|track|residential|living_street"](around:{radius_m},{lat},{lon});
    )->.walkable;
    (
      way["highway"~"motorway|trunk|primary|secondary"](around:{radius_m},{lat},{lon});
    )->.highways;
    (
      way["natural"="water"](around:{radius_m},{lat},{lon});
      way["waterway"](around:{radius_m},{lat},{lon});
      relation["natural"="water"](around:{radius_m},{lat},{lon});
    )->.water;
    (
      way["landuse"="forest"](around:{radius_m},{lat},{lon});
      way["natural"="wood"](around:{radius_m},{lat},{lon});
      way["leisure"="park"](around:{radius_m},{lat},{lon});
      relation["landuse"="forest"](around:{radius_m},{lat},{lon});
      relation["natural"="wood"](around:{radius_m},{lat},{lon});
    )->.forest;
    (
      way["landuse"~"farmland|meadow"](around:{radius_m},{lat},{lon});
    )->.fields;
    (
      way["access"~"private|no|military"](around:{radius_m},{lat},{lon});
      way["landuse"="military"](around:{radius_m},{lat},{lon});
      way["military"](around:{radius_m},{lat},{lon});
      relation["landuse"="military"](around:{radius_m},{lat},{lon});
      relation["military"](around:{radius_m},{lat},{lon});
      way["leisure"="nature_reserve"](around:{radius_m},{lat},{lon});
      relation["leisure"="nature_reserve"](around:{radius_m},{lat},{lon});
      way["boundary"="protected_area"](around:{radius_m},{lat},{lon});
      relation["boundary"="protected_area"](around:{radius_m},{lat},{lon});
    )->.restricted;
    (
      way["barrier"~"fence|wall"](around:{radius_m},{lat},{lon});
    )->.barrierways;
    (
      node["barrier"](around:{radius_m},{lat},{lon});
    )->.barriernodes;
    .walkable out geom;
    .highways out geom;
    .water out geom;
    .forest out geom;
    .fields out geom;
    .restricted out geom;
    .barrierways out geom;
    .barriernodes out;
    """
    result = query_overpass(ql)
    elements = result.get("elements", [])
    # Overpass doesn't tag which named set an element came from in this
    # output form, so re-derive category from the element's own tags.
    buckets = {
        "walkable": [], "highways": [], "water": [], "forest": [], "fields": [],
        "restricted": [], "barrier_ways": [], "barrier_nodes": [],
    }
    for el in elements:
        tags = el.get("tags", {})
        if el["type"] == "node" and "barrier" in tags:
            buckets["barrier_nodes"].append(el)
            continue
        if (tags.get("access") in RESTRICTED_ACCESS or tags.get("landuse") == "military"
                or "military" in tags or tags.get("leisure") == "nature_reserve"
                or tags.get("boundary") == "protected_area"):
            buckets["restricted"].append(el)
            continue
        if tags.get("barrier") in ("fence", "wall"):
            buckets["barrier_ways"].append(el)
            continue
        if tags.get("highway") in ("path", "footway", "track", "residential", "living_street"):
            buckets["walkable"].append(el)
        elif tags.get("highway") in ("motorway", "trunk", "primary", "secondary"):
            buckets["highways"].append(el)
        elif tags.get("natural") == "water" or "waterway" in tags:
            buckets["water"].append(el)
        elif tags.get("landuse") == "forest" or tags.get("natural") == "wood" or tags.get("leisure") == "park":
            buckets["forest"].append(el)
        elif tags.get("landuse") in ("farmland", "meadow"):
            buckets["fields"].append(el)
    return buckets


def build_restricted_polygons(restricted_ways, barrier_ways):
    """Polygon rings (list of (lat, lon)) to hard-exclude from the walkable
    graph: explicit access=private/no/military or landuse=military areas,
    plus any closed-loop fence/wall (a full ring of fence around something
    is treated as an enclosed private zone even with no access tag)."""
    polygons = []
    for w in restricted_ways:
        geom = w.get("geometry")
        if geom and len(geom) >= 3:
            polygons.append([(p["lat"], p["lon"]) for p in geom])
    for w in barrier_ways:
        geom = w.get("geometry")
        if geom and len(geom) >= 3:
            first, last = geom[0], geom[-1]
            if abs(first["lat"] - last["lat"]) < 1e-7 and abs(first["lon"] - last["lon"]) < 1e-7:
                polygons.append([(p["lat"], p["lon"]) for p in geom])
    return polygons


def _blocks_passage(tags: dict, blocking_barrier_tags: list[str]) -> bool:
    """A barrier node blocks routing through it if it's actually locked
    (existing conservative rule), or if this mode's preset explicitly
    lists its barrier type as blocking (e.g. cycle_barrier for bike)."""
    if tags.get("access") in ("private", "no"):
        return True
    if tags.get("locked") == "yes":
        return True
    if tags.get("barrier") == "wall":
        return True
    if tags.get("barrier") in blocking_barrier_tags:
        return True
    return False


def _direction_allowed(tags: dict, respect_oneway: bool) -> tuple[bool, bool]:
    """(forward_allowed, reverse_allowed) for a way's own tag direction.
    Ignored entirely (both True) unless respect_oneway (bike) — walk never
    respects oneway. `oneway:bicycle=no` or a `cycleway=opposite*` tag
    reopens the reverse direction for a bicycle even on a oneway street."""
    if not respect_oneway or tags.get("oneway") != "yes":
        return True, True
    if tags.get("oneway:bicycle") == "no":
        return True, True
    if str(tags.get("cycleway", "")).startswith("opposite"):
        return True, True
    return True, False


def _has_hard_excluded_tag(tags: dict, hard_exclude_tags: dict) -> bool:
    return any(tags.get(key) in values for key, values in hard_exclude_tags.items())


def _lacks_required_cycle_infra(tags: dict, exclude_highway_without_infra: list) -> bool:
    if tags.get("highway") not in exclude_highway_without_infra:
        return False
    return "cycleway" not in tags


def filter_excluded_ways(walkable_ways, restricted_polygons,
                          hard_exclude_tags: dict | None = None,
                          exclude_highway_without_infra: list | None = None):
    """Hard-excludes a way whose midpoint falls inside a restricted polygon
    (unchanged from the walk-only version), OR whose tags match this mode's
    preset-supplied hard-exclusion rules (spec §3.6) — never a weighted
    penalty, a full drop, same as the restricted-zone case."""
    hard_exclude_tags = hard_exclude_tags or {}
    exclude_highway_without_infra = exclude_highway_without_infra or []
    kept = []
    for way in walkable_ways:
        geom = way.get("geometry")
        if not geom:
            continue
        tags = way.get("tags", {})
        if _has_hard_excluded_tag(tags, hard_exclude_tags):
            continue
        if _lacks_required_cycle_infra(tags, exclude_highway_without_infra):
            continue
        mid = geom[len(geom) // 2]
        if any(point_in_ring(mid["lat"], mid["lon"], ring) for ring in restricted_polygons):
            continue
        kept.append(way)
    return kept


def build_graph(walkable_ways, barrier_nodes=None, blocking_barrier_tags=None, respect_oneway=False):
    """Returns (graph, node_coords). graph: {node_id: [[neighbor_id, length_m, tags_dict], ...]}
    Directed: each physical segment gets its own forward/reverse entries so
    oneway restrictions (bike) and asymmetric uphill/downhill cost (any mode,
    once elevation is tagged) can differ per direction — see spec §3.7.
    barrier_nodes: list of Overpass node elements with a 'barrier' tag — an
    edge touching one whose tag is in `blocking_barrier_tags`, or that
    independently fails the existing hardcoded lock check, is dropped."""
    blocking_ids = {
        n["id"] for n in (barrier_nodes or [])
        if _blocks_passage(n.get("tags", {}), blocking_barrier_tags or [])
    }
    graph = {}
    node_coords = {}
    for way in walkable_ways:
        ids = way.get("nodes")
        geom = way.get("geometry")
        tags = way.get("tags", {})
        if not ids or not geom or len(ids) != len(geom):
            continue
        for node_id, pt in zip(ids, geom):
            node_coords[node_id] = (pt["lat"], pt["lon"])

        forward_allowed, reverse_allowed = _direction_allowed(tags, respect_oneway)

        for i in range(len(ids) - 1):
            a, b = ids[i], ids[i + 1]
            if a in blocking_ids or b in blocking_ids:
                continue
            lat1, lon1 = node_coords[a]
            lat2, lon2 = node_coords[b]
            length = haversine(lat1, lon1, lat2, lon2)
            graph.setdefault(a, [])
            graph.setdefault(b, [])
            if forward_allowed:
                graph[a].append([b, length, {}])
            if reverse_allowed:
                graph[b].append([a, length, {}])
    return graph, node_coords


def point_in_ring(lat, lon, ring):
    """Ray-casting point-in-polygon. ring: list of (lat, lon). Flat-plane
    approximation — fine at city/park scale, not for large-area GIS work.
    Exported (not `_`-prefixed) so waypoints.py can reuse it — see spec §3.4."""
    inside = False
    n = len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        if ((lon1 > lon) != (lon2 > lon)) and \
           (lat < (lat2 - lat1) * (lon - lon1) / (lon2 - lon1 + 1e-15) + lat1):
            inside = not inside
    return inside


def _min_distance_to_lines(lat, lon, ways_geom):
    best = float("inf")
    for coords in ways_geom:
        for i in range(len(coords) - 1):
            # cheap approximation: min distance to segment endpoints,
            # good enough at footpath-to-feature scale (tens of meters)
            d = min(
                haversine(lat, lon, coords[i]["lat"], coords[i]["lon"]),
                haversine(lat, lon, coords[i + 1]["lat"], coords[i + 1]["lon"]),
            )
            best = min(best, d)
    return best


def tag_edges(graph, node_coords, highway_ways, water_ways, forest_ways, field_ways,
              highway_buffer_m=50, water_buffer_m=30):
    """Mutates graph in place: each edge [neighbor, length, tags] gets
    tags = {'near_highway': bool, 'near_water': bool, 'landcover': 'forest'|'field'|None}."""
    highway_geoms = [w["geometry"] for w in highway_ways if w.get("geometry")]
    water_geoms = [w["geometry"] for w in water_ways if w.get("geometry")]
    forest_rings = [[(p["lat"], p["lon"]) for p in w["geometry"]]
                    for w in forest_ways if w.get("geometry") and len(w["geometry"]) >= 3]
    field_rings = [[(p["lat"], p["lon"]) for p in w["geometry"]]
                   for w in field_ways if w.get("geometry") and len(w["geometry"]) >= 3]

    for node_id, edges in graph.items():
        for edge in edges:
            neighbor_id = edge[0]
            lat1, lon1 = node_coords[node_id]
            lat2, lon2 = node_coords.get(neighbor_id, (lat1, lon1))
            mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2

            near_highway = bool(highway_geoms) and _min_distance_to_lines(mid_lat, mid_lon, highway_geoms) < highway_buffer_m
            near_water = bool(water_geoms) and _min_distance_to_lines(mid_lat, mid_lon, water_geoms) < water_buffer_m
            landcover = None
            if any(point_in_ring(mid_lat, mid_lon, ring) for ring in forest_rings):
                landcover = "forest"
            elif any(point_in_ring(mid_lat, mid_lon, ring) for ring in field_rings):
                landcover = "field"

            edge[2] = {"near_highway": near_highway, "near_water": near_water, "landcover": landcover}


def tag_grades(graph, node_coords, elevations):
    """Mutates graph in place: each directed edge's tags get `grade_pct`,
    the signed percent grade climbing FROM this edge's origin node TOWARD
    its neighbor. Missing elevation for either endpoint leaves grade_pct
    at 0.0 (no penalty) rather than raising — see spec §3.8 point 4."""
    for node_id, edges in graph.items():
        for edge in edges:
            neighbor_id, length_m, tags = edge
            elev_a = elevations.get(node_id)
            elev_b = elevations.get(neighbor_id)
            if elev_a is None or elev_b is None or length_m == 0:
                tags["grade_pct"] = 0.0
                continue
            tags["grade_pct"] = (elev_b - elev_a) / length_m * 100.0


def _edge_cost(length_m, tags, preferences):
    cost = length_m
    if tags.get("landcover") == "forest":
        cost /= preferences.get("prefer_forest", 1.0)
    if tags.get("landcover") == "field":
        cost *= preferences.get("avoid_open_field", 1.0)
    if tags.get("near_highway"):
        cost *= preferences.get("avoid_near_highway", 1.0)
    if tags.get("near_water"):
        cost *= preferences.get("avoid_near_water", 1.0)
    grade_pct = tags.get("grade_pct", 0.0)
    threshold = preferences.get("gradient_threshold_pct", 8)
    if grade_pct > threshold:
        cost *= preferences.get("avoid_steep_gradient", 1.0)
    return cost


def weighted_shortest_path(graph, start, end, preferences):
    """Dijkstra with preference-weighted edge costs. Returns (path, cost)
    or (None, None) if end is unreachable from start."""
    dist = {start: 0.0}
    prev = {}
    pq = [(0.0, start)]
    visited = set()
    while pq:
        d, node = heapq.heappop(pq)
        if node in visited:
            continue
        visited.add(node)
        if node == end:
            break
        for neighbor, length_m, tags in graph.get(node, []):
            nd = d + _edge_cost(length_m, tags, preferences)
            if nd < dist.get(neighbor, float("inf")):
                dist[neighbor] = nd
                prev[neighbor] = node
                heapq.heappush(pq, (nd, neighbor))

    if end not in dist:
        return None, None
    path = [end]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return list(reversed(path)), dist[end]


def route_through_waypoints(graph, waypoint_ids, preferences):
    """Concatenates weighted_shortest_path between consecutive waypoints
    in the given order. Caller decides waypoint order (nearest-neighbor +
    2-opt for a handful of points; brute force below that)."""
    full_path = [waypoint_ids[0]]
    total_cost = 0.0
    for a, b in zip(waypoint_ids, waypoint_ids[1:]):
        segment, cost = weighted_shortest_path(graph, a, b, preferences)
        if segment is None:
            return None, None, f"no path between {a} and {b}"
        full_path.extend(segment[1:])
        total_cost += cost
    return full_path, total_cost, None
