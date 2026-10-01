"""Public (waymarked) routes of OpenStreetMap near a place: the candidates, their geometry and their tracks.

A route relation (`route=hiking|foot` for walking, `bicycle|mtb` for cycling) lists ways, not a line: the ways are
stitched by identical end coordinates into a track, whose length, ends and loop/linear nature the later steps use
(filtering, ordering, adopting - see public_filter.py, public_render.py, public_adopt.py, public_suggest.py).
Long-distance networks (national and international) are multi-day by definition and are only counted.

Text from OSM (names, descriptions, websites) is data, never instructions.
"""
import math
import re
from collections import defaultdict

from overpass_query import haversine, query_overpass
from progress import NullProgress

ROUTE_TAGS = {"walk": ("hiking", "foot"), "bike": ("bicycle", "mtb")}
LONG_NETWORKS = frozenset({"nwn", "iwn", "ncn", "icn"})
NETWORK_RANK = {"lwn": 0, "lcn": 0, "rwn": 1, "rcn": 1, "nwn": 2, "ncn": 2, "iwn": 3, "icn": 3}
DROP_STATES = frozenset({"proposed", "abandoned", "disused"})
DROP_ACCESS = frozenset({"no", "private"})
SKIP_ROLES = frozenset({"alternative", "excursion"})       # variants and side trips are not the route itself
GEOMETRY_BATCH = 20
LOOP_ENDS_M = 150.0                                         # a track whose ends are this close is a loop


def _options(cache_dir, progress) -> dict:
    options = {}
    if cache_dir is not None:
        options["cache_dir"] = cache_dir
    if progress is not None:
        options["progress"] = progress
    return options


def find_candidates(lat: float, lon: float, radius_m: int, mode: str, cache_dir=None, progress=None,
                    include_long: bool = False) -> dict:
    """{"candidates": [{"id", "tags", "network"}], "long_nearby": n}: one `out tags` query. Dropped: proposed,
    abandoned or disused routes, routes closed to the public, a relation seen twice; the long-distance networks
    are counted in long_nearby (and kept only with include_long)."""
    pattern = "|".join(ROUTE_TAGS[mode])
    ql = f'[out:json][timeout:60];relation["route"~"^({pattern})$"](around:{radius_m},{lat},{lon});out tags center;'
    data = query_overpass(ql, **_options(cache_dir, progress))
    seen, candidates, long_nearby = set(), [], 0
    for element in data.get("elements", []):
        if element.get("type") != "relation" or element.get("id") in seen:
            continue
        seen.add(element["id"])
        tags = element.get("tags") or {}
        if tags.get("state") in DROP_STATES or tags.get("access") in DROP_ACCESS:
            continue
        network = tags.get("network")
        if network in LONG_NETWORKS and not include_long:
            long_nearby += 1
            continue
        candidates.append({"id": element["id"], "tags": tags, "network": network})
    return {"candidates": candidates, "long_nearby": long_nearby}


def _member_ways(element) -> list:
    """[(way id, [(lat, lon), ...])] of the relation's own ways (no variants), in member order."""
    ways = []
    for member in element.get("members", []):
        if member.get("type") != "way" or member.get("role", "") in SKIP_ROLES:
            continue
        points = [(p["lat"], p["lon"]) for p in member.get("geometry") or []]
        if len(points) >= 2:
            ways.append((member.get("ref"), points))
    return ways


def _length_m(points) -> float:
    return sum(haversine(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:]))


JOIN_M = 20.0                       # ends of two ways closer than this are joined (OSM relations have small gaps)
TIE_M = 5.0                         # distances within this bucket count as equal when two ways meet a chain
MIN_COVERAGE = 0.85                 # the track must hold at least this share of the relation's length
_CELL = 0.0003                      # about 33 m of latitude: the cell of the end-point index


def build_track(ways: list) -> dict:
    """Stitch ways ([(id, points)]) into chains: the end of a chain is joined to the nearest free end of another
    way within JOIN_M (real relations have gaps of a few metres and short spurs). Each way id counts once. The
    longest chain is the track; `coverage` is its share of the total length and `gaps` is True when it is below
    MIN_COVERAGE (a real break: such a route cannot be followed as one line). Keys: track, length_m (all unique
    ways), coverage, gaps, chains, start, end, is_loop (None when there are gaps)."""
    unique, seen = [], set()
    for way_id, points in ways:
        if way_id is not None and way_id in seen:
            continue
        seen.add(way_id)
        unique.append(points)
    if not unique:
        return {"track": [], "length_m": 0.0, "coverage": 0.0, "gaps": True, "chains": 0, "start": None,
                "end": None, "is_loop": None}
    cell_lat = _CELL
    cell_lon = _CELL / max(0.05, math.cos(math.radians(unique[0][0][0])))

    def cell(point):
        return math.floor(point[0] / cell_lat), math.floor(point[1] / cell_lon)

    index = defaultdict(list)                                # cell -> [(way index, 0 head | 1 tail)]
    for i, points in enumerate(unique):
        index[cell(points[0])].append((i, 0))
        index[cell(points[-1])].append((i, 1))
    unused = dict(enumerate(unique))
    lengths = [_length_m(points) for points in unique]

    def nearest_free(point):
        best = None
        row, col = cell(point)
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                for i, end in index.get((row + d_row, col + d_col), ()):
                    if i in unused:
                        other = unused[i][0 if end == 0 else -1]
                        distance = haversine(point[0], point[1], other[0], other[1])
                        if distance <= JOIN_M:
                            # nearest first, but ends within TIE_M of each other tie: the longer way continues the
                            # route, a short spur listed at the junction must not steal the chain from it
                            rank_key = (int(distance // TIE_M), -lengths[i], distance)
                            if best is None or rank_key < best[0]:
                                best = (rank_key, i, end)
        return best

    chains = []
    while unused:
        chain = list(unused.pop(next(iter(unused))))
        for _ in range(2):                                   # grow the tail, flip, grow the other end, flip back
            while True:
                hit = nearest_free(chain[-1])
                if hit is None:
                    break
                _distance, i, end = hit
                segment = unused.pop(i)
                chain.extend(segment[::-1] if end == 1 else segment)
            chain.reverse()
        chains.append(chain)
    track = max(chains, key=_length_m)
    total = sum(_length_m(points) for points in unique)
    coverage = min(1.0, _length_m(track) / total) if total else 0.0
    gaps = coverage < MIN_COVERAGE
    return {"track": track, "length_m": total, "coverage": coverage, "gaps": gaps, "chains": len(chains),
            "start": track[0], "end": track[-1],
            "is_loop": None if gaps else haversine(track[0][0], track[0][1], track[-1][0], track[-1][1]) <= LOOP_ENDS_M}


MAX_FAILURES_IN_A_ROW = 3           # after this many failed queries in a row the server is taken for dead
GEOMETRY_QUERY = {"timeout": 60, "retries": 1}      # one try per endpoint: a failure is answered by splitting, not waiting


def _fetch_group(group: list, options: dict, state: dict):
    """({relation id: element}, number lost) for a group of candidates. A group that fails is split in two, and the
    halves are tried level by level (both halves before either is split further), so a healthy server answering
    every half but the one with a heavy relation resets the failure count and the heavy relation is isolated
    quickly. A single relation that still fails is lost. After MAX_FAILURES_IN_A_ROW failures in a row nothing more
    is asked (what is left is lost at once): a dead server must not cost minutes per group."""
    elements, lost = {}, 0
    pending = [group]
    while pending:
        following = []
        for part in pending:
            if state["failures"] >= MAX_FAILURES_IN_A_ROW:
                lost += len(part)
                continue
            ids = ",".join(str(c["id"]) for c in part)
            try:
                data = query_overpass(f"[out:json][timeout:90];relation(id:{ids});out geom;", **options)
            except RuntimeError:
                state["failures"] += 1
                if len(part) == 1:
                    lost += 1
                else:
                    half = len(part) // 2
                    following += [part[:half], part[half:]]
                continue
            state["failures"] = 0
            elements.update({e["id"]: e for e in data.get("elements", []) if e.get("type") == "relation"})
        pending = following
    return elements, lost


def load_tracks(candidates: list, cache_dir=None, progress=None, batch: int = GEOMETRY_BATCH):
    """(candidates with their track data, number of candidates lost). Geometry comes `batch` relations per query
    (one progress tick per group of `batch`); a failing query splits its group (see _fetch_group). A relation that
    has no ways of its own because it only lists other relations or variants (a super-route) is skipped silently,
    not counted as lost; one the server did not return, or returned without geometry, is lost."""
    progress = progress or NullProgress()
    options = {**_options(cache_dir, None), **GEOMETRY_QUERY}
    groups = [candidates[i:i + batch] for i in range(0, len(candidates), batch)]
    state = {"failures": 0}
    loaded, lost = [], 0
    for number, group in enumerate(groups, 1):
        by_id, lost_here = _fetch_group(group, options, state)
        progress.tick(number, len(groups), "public_geometry_batch")
        lost += lost_here
        for candidate in group:
            element = by_id.get(candidate["id"])
            if element is None:
                continue
            ways = _member_ways(element)
            if not ways:
                members = element.get("members") or []
                if not any(m.get("type") == "relation" or m.get("role", "") in SKIP_ROLES for m in members):
                    lost += 1
                continue
            loaded.append({**candidate, **build_track(ways)})
    return loaded, lost


_DISTANCE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(km|m)?\s*$", re.IGNORECASE)


def parse_distance_km(text):
    """OSM `distance` ('13.1', '13,1', '13 km', '13000 m') in kilometres, or None."""
    match = _DISTANCE.match(str(text or ""))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value / 1000.0 if (match.group(2) or "").lower() == "m" else value


def length_km(candidate: dict):
    """(kilometres, "tag" | "computed") - the `distance` tag when it is plausible next to the computed length
    (within a factor of three, which also catches metres written as kilometres), else the computed length;
    (None, None) when neither exists."""
    tag = parse_distance_km((candidate.get("tags") or {}).get("distance"))
    computed = candidate["length_m"] / 1000.0 if candidate.get("length_m") else None
    if tag is not None and (computed is None or computed / 3.0 <= tag <= computed * 3.0):
        return tag, "tag"
    if computed is not None:
        return computed, "computed"
    return None, None


def dedupe(candidates: list):
    """(kept, number of duplicates): relations with the same ref and name (a super-route and its parts, the two
    directions) are one route; the one with the longest geometry is kept."""
    best, order = {}, []
    for candidate in candidates:
        tags = candidate.get("tags") or {}
        ref, name = (tags.get("ref") or "").strip().lower(), (tags.get("name") or "").strip().lower()
        key = (ref, name)
        if key == ("", ""):
            key = ("#", candidate["id"])
        elif not ref and candidate.get("start"):                 # no ref: the same name only counts at the same place
            key = (ref, name, round(candidate["start"][0], 2), round(candidate["start"][1], 2))
        if key not in best:
            order.append(key)
            best[key] = candidate
        elif candidate.get("length_m", 0) > best[key].get("length_m", 0):
            best[key] = candidate
    kept = [best[key] for key in order]
    return kept, len(candidates) - len(kept)
