"""Criteria, elevation, key points and ordering of public route candidates (see public_routes.py).

The user's criteria are length, travel time, a maximum ascent and loop or linear. Time comes from the planner's own
duration formula (the mode's pace and ascent rate), so a public route is judged the way a built route is. The
cheap checks (length, the lower bound of the time without any ascent, loop) run first; only the survivors get
elevations, which are one sample per 150 m along the track.
"""
import math
from dataclasses import dataclass

from duration import estimate_duration_hours
from elevation.resample import sample_positions
from overpass_query import haversine, query_overpass
from public_routes import NETWORK_RANK, _options, length_km, parse_distance_km

RANGE_TOLERANCE = 0.25            # a single number from the user means that number +- 25 %
TAG_MARGIN = 1.15                 # a `distance` tag is trusted to within this factor before the geometry is loaded
KEYPOINT_RADIUS_M = 80.0
START_PLACE_RADIUS_M = 3000.0
KIND_PRIORITY = ("peak", "viewpoint", "historic", "water", "hut", "sight")
MIN_SAMPLES_SHARE = 0.8           # elevations are trusted when at least this share of the samples resolved
OPTIONAL_QUERY = {"timeout": 40, "retries": 1}   # key points and places only decorate the list: never wait minutes for them


@dataclass
class Criteria:
    min_km: float | None = None
    max_km: float | None = None
    min_h: float | None = None
    max_h: float | None = None
    max_ascent_m: float | None = None
    loop: bool | None = None                  # True: loops only, False: linear only, None: either
    interests: tuple = ()                     # kinds from KIND_PRIORITY the user asked for


def criteria_from_number(value: float, kind: str, **extra) -> Criteria:
    """A single length ('km') or time ('h') from the user: the range value +- 25 %."""
    low, high = value * (1 - RANGE_TOLERANCE), value * (1 + RANGE_TOLERANCE)
    if kind == "km":
        return Criteria(min_km=low, max_km=high, **extra)
    if kind == "h":
        return Criteria(min_h=low, max_h=high, **extra)
    raise ValueError(f"kind must be 'km' or 'h', not {kind!r}")


def passes_tag_length(candidate: dict, criteria: Criteria) -> bool:
    """Before the geometry is loaded: drop a route whose `distance` tag is clearly outside the length range."""
    tag = parse_distance_km((candidate.get("tags") or {}).get("distance"))
    if tag is None:
        return True
    if criteria.min_km is not None and tag * TAG_MARGIN < criteria.min_km:
        return False
    if criteria.max_km is not None and tag / TAG_MARGIN > criteria.max_km:
        return False
    return True


def prefilter(candidate: dict, criteria: Criteria, pace_kmh: float) -> bool:
    """The checks that need no elevation: length, the lower bound of the time (the length at the mode's pace,
    no ascent at all) and loop or linear. A route with no known length is dropped."""
    km, _source = length_km(candidate)
    if km is None:
        return False
    if criteria.min_km is not None and km < criteria.min_km:
        return False
    if criteria.max_km is not None and km > criteria.max_km:
        return False
    if criteria.max_h is not None and km / pace_kmh > criteria.max_h:
        return False
    if criteria.loop is not None and candidate.get("is_loop") is not None and candidate["is_loop"] != criteria.loop:
        return False
    return True


def _gain_loss(values: list):
    known = [v for v in values if v is not None]
    if len(known) < 2 or len(known) < MIN_SAMPLES_SHARE * len(values):
        return None, None
    ascent = sum(b - a for a, b in zip(known, known[1:]) if b > a)
    descent = sum(a - b for a, b in zip(known, known[1:]) if b < a)
    return round(ascent, 1), round(descent, 1)


def add_elevation(candidates: list, service, progress=None, interval_m: float = 150.0) -> None:
    """ascent_m and descent_m of every candidate (None when too few samples resolved). All samples go to the
    elevation service in one call, so its batching, cache and progress ticks work across the candidates."""
    points, spans = [], []
    for candidate in candidates:
        samples = sample_positions(candidate["track"], interval_m)
        spans.append((len(points), len(points) + len(samples)))
        points.extend((lat, lon) for lat, lon, _ in samples)
    values = service.get_elevations(points, progress=progress) if points else []
    for candidate, (first, last) in zip(candidates, spans):
        candidate["ascent_m"], candidate["descent_m"] = _gain_loss(values[first:last])


def apply_final(candidates: list, criteria: Criteria, pace_kmh: float, ascent_minutes_per_100m: float) -> list:
    """Time from the planner's duration formula, then the time range and the maximum ascent. A route whose ascent
    could not be determined is kept with duration_h None and the criteria it could not be checked against in
    `unchecked`."""
    kept = []
    for candidate in candidates:
        km, source = length_km(candidate)
        candidate["length_km"], candidate["length_source"] = km, source
        ascent = candidate.get("ascent_m")
        candidate["unchecked"] = []
        if ascent is None:
            candidate["duration_h"] = None
            if criteria.min_h is not None or criteria.max_h is not None:
                candidate["unchecked"].append("time")
            if criteria.max_ascent_m is not None:
                candidate["unchecked"].append("ascent")
            kept.append(candidate)
            continue
        hours = estimate_duration_hours(km, ascent, pace_kmh, ascent_minutes_per_100m)
        candidate["duration_h"] = hours
        if criteria.min_h is not None and hours < criteria.min_h:
            continue
        if criteria.max_h is not None and hours > criteria.max_h:
            continue
        if criteria.max_ascent_m is not None and ascent > criteria.max_ascent_m:
            continue
        kept.append(candidate)
    return kept


# ---- key points --------------------------------------------------------------------------------------------------------

def classify(tags: dict):
    """The kind of a named OSM object that is worth naming a route by, or None."""
    natural, tourism = tags.get("natural"), tags.get("tourism")
    if natural in ("peak", "saddle"):
        return "peak"
    if tourism == "viewpoint":
        return "viewpoint"
    if tags.get("historic"):
        return "historic"
    if natural in ("water", "spring", "waterfall") or tags.get("waterway") == "waterfall":
        return "water"
    if tourism in ("alpine_hut", "wilderness_hut"):
        return "hut"
    if tourism == "attraction":
        return "sight"
    return None


def _union_bbox(candidates: list, margin_deg: float):
    lats = [p[0] for c in candidates for p in c["track"]]
    lons = [p[1] for c in candidates for p in c["track"]]
    return min(lats) - margin_deg, min(lons) - margin_deg, max(lats) + margin_deg, max(lons) + margin_deg


def find_key_points(candidates: list, cache_dir=None, progress=None) -> list:
    """Every named peak, viewpoint, historic object, water, hut or sight in the union of the tracks' boxes: one
    query for all the candidates. [{"kind", "lat", "lon", "ele", "names": {"name": ..., "name:ru": ...}}]."""
    if not candidates:
        return []
    box = ",".join(f"{x:.5f}" for x in _union_bbox(candidates, 0.001))
    ql = (f'[out:json][timeout:90];('
          f'node["natural"~"^(peak|saddle|spring|waterfall)$"]["name"]({box});'
          f'nwr["tourism"~"^(viewpoint|alpine_hut|wilderness_hut|attraction)$"]["name"]({box});'
          f'nwr["historic"]["name"]({box});nwr["natural"="water"]["name"]({box});'
          f'nwr["waterway"="waterfall"]["name"]({box}););out tags center 3000;')
    points = []
    for element in query_overpass(ql, **_options(cache_dir, progress), **OPTIONAL_QUERY).get("elements", []):
        tags = element.get("tags") or {}
        kind = classify(tags)
        centre = element.get("center") or element
        lat, lon = centre.get("lat"), centre.get("lon")
        if kind is None or not tags.get("name") or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        names = {k: v for k, v in tags.items() if k == "name" or k.startswith("name:")}
        points.append({"kind": kind, "lat": float(lat), "lon": float(lon), "ele": tags.get("ele"), "names": names})
    return points


def _to_xy(lat, lon, lat0, lon0):
    return (lon - lon0) * 111320.0 * math.cos(math.radians(lat0)), (lat - lat0) * 110574.0


def _along(point_xy, track_xy, cumulative):
    """(distance in metres from the point to the polyline, position along the polyline in metres)."""
    best, position = float("inf"), 0.0
    px, py = point_xy
    for i in range(len(track_xy) - 1):
        (ax, ay), (bx, by) = track_xy[i], track_xy[i + 1]
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        distance = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if distance < best:
            best, position = distance, cumulative[i] + t * math.sqrt(length_sq)
    return best, position


def assign_key_points(candidate: dict, points: list, lang: str = "en") -> None:
    """candidate["key_points"]: the points within KEYPOINT_RADIUS_M of the track (distance to the segments, not to
    the vertices), in route order, one per kind and name. Names: `name:<lang>` when OSM has it, else `name`."""
    track = candidate["track"]
    lat0, lon0 = track[0]
    track_xy = [_to_xy(lat, lon, lat0, lon0) for lat, lon in track]
    cumulative = [0.0]
    for a, b in zip(track_xy, track_xy[1:]):
        cumulative.append(cumulative[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    xs, ys = [p[0] for p in track_xy], [p[1] for p in track_xy]
    margin = KEYPOINT_RADIUS_M
    found, seen = [], set()
    for point in points:
        x, y = _to_xy(point["lat"], point["lon"], lat0, lon0)
        if not (min(xs) - margin <= x <= max(xs) + margin and min(ys) - margin <= y <= max(ys) + margin):
            continue
        distance, position = _along((x, y), track_xy, cumulative)
        if distance > KEYPOINT_RADIUS_M:
            continue
        name = point["names"].get(f"name:{lang}") or point["names"].get("name")
        if (point["kind"], name) in seen:
            continue
        seen.add((point["kind"], name))
        found.append({"kind": point["kind"], "name": name, "ele": point.get("ele"), "position_m": position})
    candidate["key_points"] = sorted(found, key=lambda k: k["position_m"])


def find_start_places(candidates: list, cache_dir=None, progress=None) -> None:
    """candidate["start_place"]: the name of the nearest settlement within START_PLACE_RADIUS_M of the start (one
    query for all the starts), used as a fallback name when a route has neither a name nor `from`."""
    if not candidates:
        return
    starts = [{"track": [c["start"]]} for c in candidates]
    box = ",".join(f"{x:.5f}" for x in _union_bbox(starts, 0.03))
    ql = (f'[out:json][timeout:60];node["place"~"^(city|town|village|hamlet|suburb|neighbourhood)$"]["name"]({box});'
          f'out tags center 2000;')
    places = []
    for element in query_overpass(ql, **_options(cache_dir, progress), **OPTIONAL_QUERY).get("elements", []):
        tags = element.get("tags") or {}
        if isinstance(element.get("lat"), (int, float)) and tags.get("name"):
            places.append((element["lat"], element["lon"], {k: v for k, v in tags.items()
                                                            if k == "name" or k.startswith("name:")}))
    for candidate in candidates:
        lat, lon = candidate["start"]
        nearest = min(((haversine(lat, lon, p[0], p[1]), p[2]) for p in places), key=lambda x: x[0], default=None)
        candidate["start_place"] = nearest[1] if nearest and nearest[0] <= START_PLACE_RADIUS_M else None


# ---- order ------------------------------------------------------------------------------------------------------------

def interest_match(candidate: dict, interests) -> int:
    return sum(1 for k in candidate.get("key_points", []) if k["kind"] in interests)


def _range_distance(candidate: dict, criteria: Criteria) -> float:
    total = 0.0
    if criteria.min_km is not None and criteria.max_km is not None and candidate.get("length_km") is not None:
        middle = (criteria.min_km + criteria.max_km) / 2.0
        total += abs(candidate["length_km"] - middle) / middle
    if criteria.min_h is not None and criteria.max_h is not None and candidate.get("duration_h") is not None:
        middle = (criteria.min_h + criteria.max_h) / 2.0
        total += abs(candidate["duration_h"] - middle) / middle
    return total


def _completeness(candidate: dict) -> int:
    tags = candidate.get("tags") or {}
    return sum(1 for present in (tags.get("name"), tags.get("website"), tags.get("osmc:symbol") or tags.get("colour"))
               if present)


def rank(candidates: list, criteria: Criteria, location=None, access_points=()):
    """(ordered candidates, rules): lexicographic, no hidden score - the interests the user named (the number of
    matching key points), then how practical the start is (distance from the place or an access point), then how
    close the length and time are to the middle of the requested range, then the network level (local before
    national) and the completeness of the data (name, website, marking), then the id. `rules` lists the rules
    that actually applied, in order, for the sentence shown above the list."""
    references = ([tuple(location)] if location else []) + [tuple(p) for p in access_points]
    has_range = any(v is not None for v in (criteria.min_km, criteria.max_km, criteria.min_h, criteria.max_h))
    rules = (["interests"] if criteria.interests else []) + (["start"] if references else []) \
        + (["range"] if has_range else []) + ["network"]

    def start_distance(candidate):
        lat, lon = candidate["start"]
        return min(haversine(lat, lon, r[0], r[1]) for r in references) if references else 0.0

    def key(candidate):
        return (-interest_match(candidate, criteria.interests) if criteria.interests else 0,
                start_distance(candidate), _range_distance(candidate, criteria),
                NETWORK_RANK.get(candidate.get("network"), 1), -_completeness(candidate), candidate["id"])

    return sorted(candidates, key=key), rules
