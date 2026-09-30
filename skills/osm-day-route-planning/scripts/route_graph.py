#!/usr/bin/env python3
"""Build a preference-weighted walking graph from Overpass data and route
through it. Standard-library only (uses overpass_query.py for fetching
and haversine).

Typical flow:
    from overpass_query import query_overpass
    from route_graph import fetch_area_data, build_restricted_polygons, \
        filter_excluded_ways, build_graph, tag_edges, \
        weighted_shortest_path, route_through_waypoints

    data = fetch_area_data(lat, lon, radius_m=2000,
                            routable_highway=weights['routable_highway'],
                            hard_exclude_highway=weights.get('hard_exclude_tags', {}).get('highway', []),
                            exclude_highway_without_infra=weights.get('exclude_highway_without_infra', []),
                            mode=weights['mode'])
    restricted = build_restricted_polygons(data['restricted'], data['barrier_ways'])
    walkable = filter_excluded_ways(data['walkable'], restricted,
                                     hard_exclude_tags=weights.get('hard_exclude_tags'),
                                     exclude_highway_without_infra=weights.get('exclude_highway_without_infra'))
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

DEFAULT_ROUTABLE_HIGHWAY = ("path", "footway", "track", "residential", "living_street")
AVOIDANCE_HIGHWAY = ("motorway", "trunk", "primary", "secondary")


def fetch_area_data(lat: float, lon: float, radius_m: int = 2000,
                     routable_highway=None, hard_exclude_highway=None,
                     exclude_highway_without_infra=None, mode: str | None = None) -> dict:
    """One combined Overpass query for everything build_graph/tag_edges/
    exclusion need: walkable ways, highways (for avoidance), water,
    forest, fields, plus access-restricted ways, military land, barrier
    ways (fence/wall — used to detect enclosed private zones), and
    barrier nodes (gates etc. sitting on a path).
    Radius-limited on purpose — see reference.md on Overpass timeouts.

    routable_highway/hard_exclude_highway/exclude_highway_without_infra
    come from the active preset (spec §3.6) — a mode's own routable_highway
    list (e.g. bike's cycleway/secondary) must be fetched HERE, not just
    handled later by filter_excluded_ways, or those ways never reach the
    graph at all. hard_exclude_highway/exclude_highway_without_infra values
    are ALSO fetched into the walkable candidate set (not excluded from the
    query) — filter_excluded_ways needs to see a way in order to drop it;
    leaving those tag values out of the query here would make those preset
    exclusion rules silently do nothing, since the way they're meant to
    exclude would never arrive at all. Defaults to walk's original fixed
    tag list when no preset arguments are given, so an existing no-args
    call keeps behaving exactly as before.

    mode ("walk"/"bike", normally weights["mode"]) scopes the designated-
    path override: a restricted-tagged element that ALSO carries
    bicycle=yes|designated (bike) or foot=yes|designated (walk) is not
    bucketed as restricted for THAT mode only — a bicycle-designated path
    through an access=no area is still closed to walkers. mode=None (an
    old caller) gets no override at all: the strict default."""
    routable_highway = tuple(routable_highway) if routable_highway else DEFAULT_ROUTABLE_HIGHWAY
    hard_exclude_highway = tuple(hard_exclude_highway or ())
    exclude_highway_without_infra = tuple(exclude_highway_without_infra or ())
    walkable_highway_values = sorted(
        set(routable_highway) | set(hard_exclude_highway) | set(exclude_highway_without_infra)
    )
    walkable_pattern = "|".join(walkable_highway_values)
    ql = f"""
    [out:json][timeout:80];
    (
      way["highway"~"{walkable_pattern}"](around:{radius_m},{lat},{lon});
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
    walkable_set = set(walkable_highway_values)
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
        # A dedicated path explicitly opened to bikes OR pedestrians through
        # an otherwise access-restricted area (e.g. access=no +
        # bicycle=designated) is a deliberate OSM pattern — but only for the
        # mode it names, so the override is scoped to the active mode.
        is_restricted_tagged = (
            tags.get("access") in RESTRICTED_ACCESS or tags.get("landuse") == "military"
            or "military" in tags or tags.get("leisure") == "nature_reserve"
            or tags.get("boundary") == "protected_area"
        )
        if mode == "bike":
            has_explicit_mode_override = tags.get("bicycle") in ("yes", "designated")
        elif mode == "walk":
            has_explicit_mode_override = tags.get("foot") in ("yes", "designated")
        else:
            has_explicit_mode_override = False
        if is_restricted_tagged and not has_explicit_mode_override:
            buckets["restricted"].append(el)
            continue
        if tags.get("barrier") in ("fence", "wall"):
            buckets["barrier_ways"].append(el)
            continue
        # Walkable and highway-avoidance membership are independent: a
        # routable (bike-sport secondary) or later hard-excluded (bike's
        # infra-less trunk/primary) road must still feed tag_edges's
        # near_highway buffer for the paths running alongside it.
        highway = tags.get("highway")
        if highway in walkable_set:
            buckets["walkable"].append(el)
        if highway in AVOIDANCE_HIGHWAY:
            buckets["highways"].append(el)
        if highway is None:
            if tags.get("natural") == "water" or "waterway" in tags:
                buckets["water"].append(el)
            elif tags.get("landuse") == "forest" or tags.get("natural") == "wood" or tags.get("leisure") == "park":
                buckets["forest"].append(el)
            elif tags.get("landuse") in ("farmland", "meadow"):
                buckets["fields"].append(el)
    return buckets


def _closed_way_ring(w):
    """A way's own geometry as a ring, only if it's actually closed (first
    and last points coincide) — an open way (e.g. a private driveway) is
    not a polygon and must not be treated as one."""
    geom = w.get("geometry")
    if not geom or len(geom) < 3:
        return None
    first, last = geom[0], geom[-1]
    if abs(first["lat"] - last["lat"]) > 1e-7 or abs(first["lon"] - last["lon"]) > 1e-7:
        return None
    return [(p["lat"], p["lon"]) for p in geom]


def _stitch_rings(segments, epsilon=1e-7):
    """Assemble point-list segments (each a list of (lat, lon), possibly
    given in either direction) into closed rings by matching shared
    endpoints. A relation's outer boundary is often split across several
    way-members that each cover only part of the perimeter. Segments that
    never close into a ring are dropped — they can't form a hard-exclusion
    polygon on their own."""
    remaining = [list(seg) for seg in segments if len(seg) >= 2]
    rings = []

    def close(a, b):
        return abs(a[0] - b[0]) < epsilon and abs(a[1] - b[1]) < epsilon

    while remaining:
        ring = remaining.pop(0)
        extended = True
        while extended and not close(ring[0], ring[-1]):
            extended = False
            for i, seg in enumerate(remaining):
                if close(ring[-1], seg[0]):
                    ring.extend(seg[1:])
                elif close(ring[-1], seg[-1]):
                    ring.extend(list(reversed(seg))[1:])
                elif close(ring[0], seg[-1]):
                    ring[0:0] = seg[:-1]
                elif close(ring[0], seg[0]):
                    ring[0:0] = list(reversed(seg))[:-1]
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
        if len(ring) >= 4 and close(ring[0], ring[-1]):
            rings.append(ring[:-1])  # drop the duplicated closing point
    return rings


def _relation_outer_rings(relation):
    """Outer rings of a relation. A blank/missing role is treated as outer:
    older simple multipolygons often leave the single outer ring unroled.
    (If a blank-role member is actually a hole, it is fully inside an outer
    ring anyway, so the extra ring can't widen the excluded area.)"""
    segments = []
    for member in relation.get("members", []):
        if member.get("role", "") not in ("outer", ""):
            continue
        geom = member.get("geometry")
        if geom and len(geom) >= 2:
            segments.append([(p["lat"], p["lon"]) for p in geom])
    return _stitch_rings(segments)


def build_restricted_polygons(restricted_ways, barrier_ways):
    """Polygon rings (list of (lat, lon)) to hard-exclude from the walkable
    graph: explicit access=private/no/military or landuse=military areas
    (way or relation), plus any closed-loop fence/wall (a full ring of
    fence around something is treated as an enclosed private zone even
    with no access tag). Relations (common for large military zones) are
    reassembled from their `outer`-role member way segments — a single
    relation's boundary is often split across several ways that only
    close into a ring when joined end-to-end."""
    polygons = []
    for w in restricted_ways:
        if w.get("type") == "relation":
            polygons.extend(_relation_outer_rings(w))
        else:
            ring = _closed_way_ring(w)
            if ring:
                polygons.append(ring)
    for w in barrier_ways:
        ring = _closed_way_ring(w)
        if ring:
            polygons.append(ring)
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


_NO_CYCLE_INFRA_VALUES = ("no", "none", "separate")


def _has_cycle_infra(tags: dict) -> bool:
    """A positive cycleway value on the way itself, or on either side via
    cycleway:left/right/both — "no"/"none"/"separate" don't count as infra."""
    for key in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both"):
        value = tags.get(key)
        if value and value not in _NO_CYCLE_INFRA_VALUES:
            return True
    return False


def _lacks_required_cycle_infra(tags: dict, exclude_highway_without_infra: list) -> bool:
    if tags.get("highway") not in exclude_highway_without_infra:
        return False
    return not _has_cycle_infra(tags)


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


# Tags of a way that describe how it can be used in winter and on a bicycle; kept on every edge so that the
# archive can say what each part of the route runs on (route.geojson "segments").
WAY_TAG_KEYS = (
    "highway", "surface", "smoothness", "tracktype", "sac_scale", "mtb:scale", "trail_visibility",
    "bicycle", "foot", "winter_service", "snowplowing",
)


def _way_description(way: dict) -> dict:
    """{"way_id": ..., "highway": ..., ...}: the id and those of WAY_TAG_KEYS the way carries."""
    tags = way.get("tags", {})
    description = {"way_id": way.get("id")}
    description.update({key: tags[key] for key in WAY_TAG_KEYS if key in tags})
    return description


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
        description = _way_description(way)

        for i in range(len(ids) - 1):
            a, b = ids[i], ids[i + 1]
            if a in blocking_ids or b in blocking_ids:
                continue
            lat1, lon1 = node_coords[a]
            lat2, lon2 = node_coords[b]
            length = haversine(lat1, lon1, lat2, lon2)
            graph.setdefault(a, [])
            graph.setdefault(b, [])
            # one dict per directed edge: tag_grades writes a different grade_pct into each direction
            if forward_allowed:
                graph[a].append([b, length, {"way": description}])
            if reverse_allowed:
                graph[b].append([a, length, {"way": description}])
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


class _VertexGrid:
    """Spatial hash over the vertices of a set of lines, answering "is any vertex closer than `radius_m` to this
    point?" by looking at the 3x3 neighbouring cells only instead of every vertex. The answer is the same as a
    brute-force haversine scan over the vertices (distance to line vertices, not to segments: good enough at
    footpath-to-feature scale, tens of metres); the cells are at least `radius_m` wide in both directions, so no
    vertex that close can lie outside the 3x3 block."""

    METERS_PER_DEGREE = 111000.0            # a little under the real 111195 m, so the cells only get larger

    def __init__(self, ways_geom, radius_m):
        self.radius_m = radius_m
        vertices = [(p["lat"], p["lon"]) for coords in ways_geom for p in coords]
        widest_lat = min(89.0, max((abs(lat) for lat, _ in vertices), default=0.0) + 0.5)
        self._cell_lat = radius_m / self.METERS_PER_DEGREE
        self._cell_lon = radius_m / (self.METERS_PER_DEGREE * math.cos(math.radians(widest_lat)))
        self._cells = {}
        for lat, lon in vertices:
            self._cells.setdefault(self._key(lat, lon), []).append((lat, lon))

    def _key(self, lat, lon):
        return math.floor(lat / self._cell_lat), math.floor(lon / self._cell_lon)

    def near(self, lat, lon):
        """True when some vertex is strictly closer than the radius."""
        row, col = self._key(lat, lon)
        for r in (row - 1, row, row + 1):
            for c in (col - 1, col, col + 1):
                for vlat, vlon in self._cells.get((r, c), ()):
                    if haversine(lat, lon, vlat, vlon) < self.radius_m:
                        return True
        return False


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

    highway_grid = _VertexGrid(highway_geoms, highway_buffer_m) if highway_geoms else None
    water_grid = _VertexGrid(water_geoms, water_buffer_m) if water_geoms else None

    for node_id, edges in graph.items():
        for edge in edges:
            neighbor_id = edge[0]
            lat1, lon1 = node_coords[node_id]
            lat2, lon2 = node_coords.get(neighbor_id, (lat1, lon1))
            mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2

            near_highway = highway_grid is not None and highway_grid.near(mid_lat, mid_lon)
            near_water = water_grid is not None and water_grid.near(mid_lat, mid_lon)
            landcover = None
            if any(point_in_ring(mid_lat, mid_lon, ring) for ring in forest_rings):
                landcover = "forest"
            elif any(point_in_ring(mid_lat, mid_lon, ring) for ring in field_rings):
                landcover = "field"

            edge[2].update({"near_highway": near_highway, "near_water": near_water, "landcover": landcover})


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


def path_way_segments(graph, node_path):
    """Runs of the path that stay on one way: [{"from": i, "to": j, "way_id": ..., "highway": ..., ...}, ...] where
    from/to are inclusive indices into node_path (a route.geojson LineString has one vertex per node). Consecutive
    runs share their boundary vertex, the runs cover 0 .. len(node_path) - 1. Of parallel edges between two nodes
    the shortest is used. A path of fewer than two nodes has no segments."""
    runs = []
    for i in range(len(node_path) - 1):
        a, b = node_path[i], node_path[i + 1]
        candidates = [e for e in graph.get(a, []) if e[0] == b]
        if not candidates:
            raise ValueError(f"the path is not connected in the graph between {a} and {b}")
        description = min(candidates, key=lambda e: e[1])[2].get("way") or {}
        if runs and {k: v for k, v in runs[-1].items() if k not in ("from", "to")} == description:
            runs[-1]["to"] = i + 1
        else:
            runs.append({"from": i, "to": i + 1, **description})
    return runs


def path_geometry(graph, node_path, node_coords, node_elevations):
    """(path_coords, way_segments) built from ONE node path, so that the segment indices cannot drift from the
    coordinates. path_coords is [(lon, lat, ele_or_None), ...] one per node (node_coords holds (lat, lon))."""
    coords = []
    for node in node_path:
        lat, lon = node_coords[node]
        coords.append((lon, lat, node_elevations.get(node)))
    return coords, path_way_segments(graph, node_path)


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
