"""Water within 500 m of the track and of the points of the route (OpenStreetMap, Overpass).

One `around` query: one clause set for the track (a polyline) and one per point of interest or access point (at most
POINT_MAX). The answer carries bounding boxes; the distance to a body is measured to its box, which is exact enough
for "what is near" and never longer than the true distance. Data only (`omit=True`); `shared["error"]` is set when
Overpass did not answer."""
import hashlib
from dataclasses import asdict, dataclass

from ..base import Section, SectionPlugin
from ..osm_features import haversine_m, route_samples
from ..overpass import EMPTY_TTL_S, ROUTES_TTL_S, OverpassError, run
from .land_cover import polyline_bbox, route_polyline

RADIUS_M = 500
POINT_MAX = 12
ELEMENT_CAP = 800
QUERY_VERSION = "1"
KEEP_TAGS = ("swimming", "bathing", "access", "sport", "water", "salt")
# One key-regex selector per centre keeps the GET URL short; parse_water classifies the matches locally.
# exact (tag, value) pairs: indexed on the server; see water_query
_WATER_TAGS = (("natural", "water"), ("natural", "coastline"), ("waterway", "river"), ("waterway", "canal"),
               ("leisure", "swimming_area"), ("leisure", "bathing_place"))


@dataclass
class Anchor:
    kind: str        # track | start | end | access | poi
    name: str
    lat: float
    lon: float


@dataclass
class WaterBody:
    kind: str        # lake | pond | river | canal
    name: str
    lat: float
    lon: float
    bbox: tuple      # (south, west, north, east)
    size_km: float
    tags: dict
    distance_m: float = 0.0
    near_kind: str = "track"
    near_name: str = ""


def rect_distance_m(lat: float, lon: float, bbox) -> float:
    south, west, north, east = bbox
    return haversine_m(lat, lon, min(max(lat, south), north), min(max(lon, west), east))


def point_anchors(ctx) -> list:
    anchors = []
    for point in ctx.access_points:
        anchors.append(Anchor(point.role if point.role in ("start", "end") else "access", point.name,
                              point.lat, point.lon))
    for point in ctx.interest_points:
        anchors.append(Anchor("poi", point.name, point.lat, point.lon))
    return anchors[:POINT_MAX]


def water_query(poly: str, points: list) -> str:
    """Exact tag values are selected inside the bbox of the route (served by the tag index), then that small set is
    filtered by distance to the track and to each point. A key-regex selector cannot use the index and timed out in a
    dense town on every public mirror; `around` repeated per tag clause also made the URL too long (HTTP 414)."""
    selectors = "".join(f'nwr["{key}"="{value}"];' for key, value in _WATER_TAGS)
    box = polyline_bbox(poly, [(a.lat, a.lon) for a in points], margin_m=RADIUS_M + 100)
    around = f"nwr.w(around:{RADIUS_M},{poly});" + "".join(
        f"nwr.w(around:{RADIUS_M},{a.lat:.5f},{a.lon:.5f});" for a in points)
    return f"[out:json][timeout:9][bbox:{box}];({selectors})->.w;({around});out tags bb center {ELEMENT_CAP};"


def _bbox(element: dict):
    bounds = element.get("bounds")
    if isinstance(bounds, dict) and all(k in bounds for k in ("minlat", "minlon", "maxlat", "maxlon")):
        return (bounds["minlat"], bounds["minlon"], bounds["maxlat"], bounds["maxlon"])
    centre = element.get("center") or element
    if isinstance(centre.get("lat"), (int, float)) and isinstance(centre.get("lon"), (int, float)):
        return (centre["lat"], centre["lon"], centre["lat"], centre["lon"])
    return None


def _diagonal_km(bbox) -> float:
    south, west, north, east = bbox
    return haversine_m(south, west, north, east) / 1000.0


def _water_kind(tags: dict):
    if tags.get("waterway") in ("river", "canal"):
        return tags["waterway"]
    if tags.get("natural") == "water":
        water = tags.get("water")
        if water == "pond":
            return "pond"
        if water in ("river", "canal"):
            return water
        return "lake"
    return None


def parse_water(data: dict) -> tuple:
    """(bodies, coastline bounding boxes, swim spots [(name, lat, lon)]). Named pieces of one body are merged
    (the largest box and every swimming tag are kept)."""
    bodies, coast, spots, named = [], [], [], {}
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        bbox = _bbox(element)
        if bbox is None:
            continue
        centre = element.get("center") or element
        lat, lon = float(centre.get("lat", bbox[0])), float(centre.get("lon", bbox[1]))
        if tags.get("natural") == "coastline":
            coast.append(bbox)
            continue
        if tags.get("leisure") in ("swimming_area", "bathing_place"):
            spots.append((str(tags.get("name", "")), lat, lon))
            continue
        kind = _water_kind(tags)
        if kind is None:
            continue
        body = WaterBody(kind, str(tags.get("name", "")), lat, lon, bbox, _diagonal_km(bbox),
                         {k: tags[k] for k in KEEP_TAGS if k in tags})
        key = (kind, body.name)
        if body.name and key in named:
            old = named[key]
            old.tags = {**body.tags, **old.tags}
            if body.size_km > old.size_km:
                old.bbox, old.size_km, old.lat, old.lon = body.bbox, body.size_km, body.lat, body.lon
            continue
        if body.name:
            named[key] = body
        bodies.append(body)
    return bodies, coast, spots


def _nearest(bbox, anchors: list):
    return min(((rect_distance_m(a.lat, a.lon, bbox), a) for a in anchors), key=lambda pair: pair[0])


def place_bodies(bodies: list, anchors: list) -> list:
    for body in bodies:
        distance, anchor = _nearest(body.bbox, anchors)
        body.distance_m, body.near_kind, body.near_name = min(distance, float(RADIUS_M)), anchor.kind, anchor.name
    return bodies


class WaterNearPlugin(SectionPlugin):
    plugin_id = "water_near"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        points = point_anchors(ctx)
        poly = route_polyline(ctx.coords)
        digest = hashlib.sha1(f"{poly}|{[(round(p.lat, 5), round(p.lon, 5)) for p in points]}".encode("utf-8")).hexdigest()[:12]
        key = f"water_near|{QUERY_VERSION}|{digest}"
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None and (cached[0]["bodies"] or cached[0]["sea"] or cached[0]["swim_spots"]
                                   or ctx.now.timestamp() - cached[1] <= EMPTY_TTL_S):
            value = cached[0]
            bodies = [WaterBody(**{**b, "bbox": tuple(b["bbox"])}) for b in value["bodies"]]
            return self._section(bodies, value["sea"], [tuple(s) for s in value["swim_spots"]], None, value.get("truncated", False))
        try:
            data = run(ctx.http, water_query(poly, points), health=ctx.overpass_health, progress=ctx.progress)
        except OverpassError as e:
            return self._section([], None, [], str(e), False)

        # Check if the response was truncated
        truncated = len(data.get("elements", [])) >= ELEMENT_CAP

        bodies, coast, spots = parse_water(data)
        anchors = [Anchor("track", "", lat, lon) for lat, lon in route_samples(ctx.coords)] + points
        place_bodies(bodies, anchors)
        sea = None
        if coast:
            distance, anchor = min((_nearest(bbox, anchors) for bbox in coast), key=lambda pair: pair[0])
            sea = {"lat": anchor.lat, "lon": anchor.lon, "distance_m": min(distance, float(RADIUS_M)),
                   "near_kind": anchor.kind, "near_name": anchor.name}

        # Only cache if not truncated
        if not truncated:
            ctx.cache.put(key, {"bodies": [asdict(b) for b in bodies], "sea": sea, "swim_spots": spots, "truncated": False})

        return self._section(bodies, sea, spots, None, truncated)

    @staticmethod
    def _section(bodies: list, sea, spots: list, error, truncated: bool) -> Section:
        return Section("hazards", "", "no-data" if error else "tag-backed", omit=True,
                       shared={"bodies": bodies, "sea": sea, "swim_spots": spots, "error": error, "truncated": truncated})
