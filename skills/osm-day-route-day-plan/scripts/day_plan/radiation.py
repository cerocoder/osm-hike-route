"""The radiation registry: a hand-curated list of contaminated or closed zones
in `data/radiation_zones.json`, each with geometry, what happened, the
current status and at least one cited source, and the search of a route
against it.

Geometry kinds: `polygons` (a list of outer rings, [lon, lat]), `circle`
(centre and radius) and `buffered_polyline` (one or more lines and a
half-width). Every zone with a published outline says so; where only a
centre and an extent, or a set of named settlements, exist the entry is
`approximate` and says how the shape was made (`geometry_note`).

A route is tested by its segments (a straight segment can cross a small zone
with both ends outside it), together with its access and interest points,
which may lie off the track (a spring, a viewpoint). Nothing here touches the
network; an empty result is "no entry", never "safe"."""
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .geo import (
    KM_PER_DEG, bbox_of, bboxes_close, clip_segments, point_segment_distance, polygon_distance_segments, project,
    segments_distance, to_segments,
)

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "radiation_zones.json"
SEVERITIES = ("danger", "caution", "info")
ADVICE_KINDS = ("full", "mushrooms")
SOURCE_KINDS = ("primary", "secondary")
GEOMETRY_KINDS = ("polygons", "circle", "buffered_polyline")


def load_registry(path=REGISTRY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _valid_url(url) -> bool:
    return isinstance(url, str) and url.startswith(("http://", "https://")) and not any(c.isspace() for c in url) \
        and "." in url.split("//", 1)[1].split("/", 1)[0]


def _lonlat(point) -> bool:
    return (isinstance(point, list) and len(point) == 2 and all(isinstance(v, (int, float)) for v in point)
            and -180.0 <= point[0] <= 180.0 and -90.0 <= point[1] <= 90.0)


def _bilingual(value) -> bool:
    return isinstance(value, dict) and all(isinstance(value.get(lang), str) and value[lang].strip()
                                           for lang in ("en", "ru"))


def validate_zone(zone: dict) -> list:
    """Human-readable problems of one registry entry ([] when it is sound)."""
    problems = []
    zid = zone.get("id", "?")
    for key in ("name", "contamination", "status", "event"):
        value = zone.get(key)
        if not _bilingual(value):
            problems.append(f"{zid}: {key} needs non-empty en and ru text")
    if "geometry_note" in zone and not _bilingual(zone["geometry_note"]):
        problems.append(f"{zid}: geometry_note needs non-empty en and ru text")
    if zone.get("severity") not in SEVERITIES:
        problems.append(f"{zid}: severity must be one of {SEVERITIES}")
    if zone.get("advice") not in ADVICE_KINDS:
        problems.append(f"{zid}: advice must be one of {ADVICE_KINDS}")
    if not isinstance(zone.get("approximate"), bool):
        problems.append(f"{zid}: approximate must be true or false")
    elif zone["approximate"] and not zone.get("geometry_note"):
        problems.append(f"{zid}: an approximate zone needs a geometry_note")
    sources = zone.get("sources")
    if not (isinstance(sources, list) and sources):
        problems.append(f"{zid}: at least one source is required")
    else:
        for source in sources:
            if not (isinstance(source, dict) and _valid_url(source.get("url")) and source.get("title")
                    and source.get("kind") in SOURCE_KINDS):
                problems.append(f"{zid}: bad source {source!r}")
    geometry = zone.get("geometry") or {}
    kind = geometry.get("type")
    if kind == "polygons":
        rings = geometry.get("rings")
        if not (isinstance(rings, list) and rings):
            problems.append(f"{zid}: polygons need rings")
        else:
            for ring in rings:
                if not (isinstance(ring, list) and len(ring) >= 4 and all(_lonlat(p) for p in ring)):
                    problems.append(f"{zid}: a ring needs at least 4 [lon, lat] points")
                elif ring[0] != ring[-1]:
                    problems.append(f"{zid}: a ring must be closed")
    elif kind == "circle":
        if not (_lonlat(geometry.get("center")) and isinstance(geometry.get("radius_km"), (int, float))
                and 0 < geometry["radius_km"] <= 200):
            problems.append(f"{zid}: a circle needs center [lon, lat] and 0 < radius_km <= 200")
    elif kind == "buffered_polyline":
        lines = geometry.get("lines")
        if not (isinstance(lines, list) and lines and all(isinstance(line, list) and len(line) >= 2
                                                          and all(_lonlat(p) for p in line) for line in lines)):
            problems.append(f"{zid}: a buffered polyline needs lines of at least 2 [lon, lat] points")
        if not (isinstance(geometry.get("half_width_km"), (int, float)) and 0 < geometry["half_width_km"] <= 100):
            problems.append(f"{zid}: half_width_km must be in (0, 100]")
    else:
        problems.append(f"{zid}: geometry type must be one of {GEOMETRY_KINDS}")
    return problems


def validate_registry(data: dict) -> list:
    problems = []
    scope = data.get("scope") or {}
    if not (isinstance(data.get("margin_km"), (int, float)) and data["margin_km"] > 0):
        problems.append("margin_km must be positive")
    boxes = scope.get("boxes")
    if not (isinstance(boxes, list) and boxes and all(
            isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)
            and b[0] < b[2] and b[1] < b[3] for b in boxes)):
        problems.append("scope needs boxes [min_lon, min_lat, max_lon, max_lat]")
    zones = data.get("zones")
    if not (isinstance(zones, list) and zones):
        return problems + ["no zones"]
    seen = set()
    for zone in zones:
        if zone.get("id") in seen:
            problems.append(f"duplicate id {zone.get('id')}")
        seen.add(zone.get("id"))
        problems += validate_zone(zone)
    return problems


def zone_bbox(zone: dict) -> tuple:
    """(min_lon, min_lat, max_lon, max_lat), including a circle's radius or a buffer's half-width."""
    g = zone["geometry"]
    if g["type"] == "polygons":
        return bbox_of([tuple(p) for ring in g["rings"] for p in ring])
    if g["type"] == "circle":
        (lon, lat), r = g["center"], g["radius_km"]
        dlat = r / KM_PER_DEG
        dlon = r / (KM_PER_DEG * max(0.05, math.cos(math.radians(lat))))
        return lon - dlon, lat - dlat, lon + dlon, lat + dlat
    min_lon, min_lat, max_lon, max_lat = bbox_of([tuple(p) for line in g["lines"] for p in line])
    w = g["half_width_km"]
    dlat = w / KM_PER_DEG
    dlon = w / (KM_PER_DEG * max(0.05, math.cos(math.radians(max(abs(min_lat), abs(max_lat))))))
    return min_lon - dlon, min_lat - dlat, max_lon + dlon, max_lat + dlat


@dataclass
class ZoneHit:
    zone: dict
    distance_km: float   # 0.0 = the route or one of its points is inside or on the zone

    @property
    def inside(self) -> bool:
        return self.distance_km <= 0.0


def _route_segments(route: list, points: list, lat0: float, lon0: float) -> list:
    """Projected segments of the route plus one zero-length segment per point of interest / access point."""
    xy = [project(lon, lat, lat0, lon0) for lon, lat in route]
    segments = to_segments(xy) if xy else []
    segments += [(p, p) for p in (project(lon, lat, lat0, lon0) for lon, lat in points)]
    return segments


def zone_distance_km(zone: dict, route: list, points: list, cap_km: float) -> float | None:
    """Shortest distance in km from the route (or one of its points) to the zone, 0.0 when inside, or None when
    it is more than cap_km away. `route` and `points` are [(lon, lat), ...]."""
    min_lon, min_lat, max_lon, max_lat = zone_bbox(zone)
    lat0, lon0 = (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0
    segments = _route_segments(route, points, lat0, lon0)
    x0, y0 = project(min_lon, min_lat, lat0, lon0)
    x1, y1 = project(max_lon, max_lat, lat0, lon0)
    segments = clip_segments(segments, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), cap_km)
    if not segments:
        return None
    g = zone["geometry"]
    if g["type"] == "polygons":
        best = math.inf
        for ring in g["rings"]:
            xy = [project(lon, lat, lat0, lon0) for lon, lat in ring]
            best = min(best, polygon_distance_segments(segments, xy, cap_km))
            if best == 0.0:
                break
    elif g["type"] == "circle":
        cx, cy = project(g["center"][0], g["center"][1], lat0, lon0)
        best = max(0.0, min(point_segment_distance(cx, cy, *a, *b) for a, b in segments) - g["radius_km"])
    else:
        lines = [[project(lon, lat, lat0, lon0) for lon, lat in line] for line in g["lines"]]
        half = g["half_width_km"]
        best = math.inf
        for line in lines:
            best = min(best, segments_distance(segments, to_segments(line), cap_km + half))
        best = max(0.0, best - half)
    return best if best <= cap_km else None


def find_hits(registry: dict, route: list, points: list, margin_km: float | None = None) -> list:
    """[ZoneHit] for every zone the route or its points are inside or within margin_km of, nearest first."""
    margin = margin_km if margin_km is not None else registry["margin_km"]
    if not route:
        return []
    route_box = bbox_of(route + points)
    hits = []
    for zone in registry["zones"]:
        if not bboxes_close(route_box, zone_bbox(zone), margin):
            continue
        distance = zone_distance_km(zone, route, points, margin)
        if distance is not None:
            hits.append(ZoneHit(zone, distance))
    return sorted(hits, key=lambda h: (h.distance_km, h.zone["id"]))


def in_scope(registry: dict, lat: float, lon: float) -> bool:
    """True when the place lies in one of the boxes the registry is meant to cover (Europe with the Urals, Siberia and the
    Far East north of 49 N, Primorye); elsewhere a radiation part would say nothing."""
    return any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in registry["scope"]["boxes"])
