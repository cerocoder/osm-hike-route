"""Forest and open ground along the route, for the tick estimate (`bio_hazards`).

One Overpass query returns the polygons that touch a 30 m corridor around the track, with their geometry; points
taken along the track (by distance, not per vertex) are tested against the polygons here. Data only: nothing is
written into the plan (`omit=True`); `shared["known"]` is False when Overpass did not answer, so the consumer can say
"terrain not determined" instead of "no forest"."""
import hashlib
import math
from dataclasses import dataclass

from ..base import Section, SectionPlugin
from ..osm_features import haversine_m, route_samples
from ..overpass import ROUTES_TTL_S, OverpassError, run

AROUND_M = 30
SAMPLE_STEP_M = 100.0
SAMPLE_MAX = 300
POLYLINE_MAX = 100
ELEMENT_CAP = 1500
QUERY_VERSION = "1"
# (tag, value) -> kind; one table, so a region can be tuned
COVER_KINDS = {
    ("natural", "wood"): "forest", ("landuse", "forest"): "forest",
    ("natural", "scrub"): "open", ("natural", "heath"): "open", ("natural", "grassland"): "open",
    ("landuse", "meadow"): "open", ("landuse", "grass"): "open", ("landuse", "farmland"): "open",
}


@dataclass
class Polygon:
    kind: str
    outers: list       # rings of (lon, lat)
    inners: list
    bbox: tuple        # (min_lon, min_lat, max_lon, max_lat)

    def covers(self, lon: float, lat: float) -> bool:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            return False
        return (any(_in_ring(lon, lat, ring) for ring in self.outers)
                and not any(_in_ring(lon, lat, ring) for ring in self.inners))


def route_polyline(coords: list) -> str:
    return ",".join(f"{lat:.5f},{lon:.5f}" for lat, lon in route_samples(coords, POLYLINE_MAX))


def polyline_bbox(poly: str, extra_points=(), margin_m: float = 600.0) -> str:
    """`south,west,north,east` of a polyline string ("lat,lon,lat,lon,...") and of extra (lat, lon) points, widened
    by `margin_m`: the box of an Overpass `[bbox:...]` setting."""
    numbers = [float(x) for x in poly.split(",")]
    lats = numbers[0::2] + [lat for lat, _ in extra_points]
    lons = numbers[1::2] + [lon for _, lon in extra_points]
    lat_margin = margin_m / 111000.0
    lon_margin = margin_m / (111000.0 * max(0.2, math.cos(math.radians((min(lats) + max(lats)) / 2))))
    return f"{min(lats) - lat_margin:.5f},{min(lons) - lon_margin:.5f},{max(lats) + lat_margin:.5f},{max(lons) + lon_margin:.5f}"


def cover_query(poly: str) -> str:
    """Exact tag values are selected inside the bbox of the track (served by the tag index), and only that small set
    is filtered by distance to the track. A regex selector, or `around` on every tag clause, made the query so slow in
    a dense town that it timed out on the public servers."""
    selectors = "".join(f'nwr["{key}"="{value}"];' for (key, value) in COVER_KINDS)
    return (f"[out:json][timeout:9][bbox:{polyline_bbox(poly, margin_m=AROUND_M + 50)}];({selectors})->.c;"
            f"nwr.c(around:{AROUND_M},{poly});out tags geom {ELEMENT_CAP};")


def densify(coords: list, step_m: float = SAMPLE_STEP_M, max_points: int = SAMPLE_MAX) -> list:
    """[(lat, lon)] along the track about every `step_m`, at most `max_points`, both ends included."""
    if not coords or len(coords) < 2:
        return [(coords[0][1], coords[0][0])] if coords else []

    # Calculate cumulative distances along the route
    cumulative_distances = [0.0]
    for (lon1, lat1, *_), (lon2, lat2, *_) in zip(coords, coords[1:]):
        dist = haversine_m(lat1, lon1, lat2, lon2)
        cumulative_distances.append(cumulative_distances[-1] + dist)

    total_distance = cumulative_distances[-1]
    if total_distance == 0:
        return [(coords[-1][1], coords[-1][0])]

    # Calculate the number of points: roughly one every step_m, but at most max_points
    num_points = min(max_points, max(2, math.ceil(total_distance / step_m)))

    # Emit points at regular distance intervals
    points = []
    for i in range(num_points):
        target_distance = i * total_distance / (num_points - 1) if num_points > 1 else 0

        # Find the segment containing this target distance
        for j in range(len(cumulative_distances) - 1):
            if cumulative_distances[j] <= target_distance <= cumulative_distances[j + 1]:
                # Interpolate within this segment
                seg_start = cumulative_distances[j]
                seg_end = cumulative_distances[j + 1]
                seg_dist = seg_end - seg_start

                if seg_dist == 0:
                    f = 0
                else:
                    f = (target_distance - seg_start) / seg_dist

                lon1, lat1, *_ = coords[j]
                lon2, lat2, *_ = coords[j + 1]
                lat = lat1 + (lat2 - lat1) * f
                lon = lon1 + (lon2 - lon1) * f
                points.append((lat, lon))
                break

    return points


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _stitch(ways: list) -> list:
    """Closed rings from member ways joined at identical end points; rings that cannot be closed are dropped."""
    ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while ways:
        ring = ways.pop(0)
        while ring[0] != ring[-1]:
            for i, way in enumerate(ways):
                if way[0] == ring[-1]:
                    ring = ring + way[1:]
                elif way[-1] == ring[-1]:
                    ring = ring + way[::-1][1:]
                elif way[-1] == ring[0]:
                    ring = way[:-1] + ring
                elif way[0] == ring[0]:
                    ring = way[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                break
            else:
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _kind(tags: dict):
    for key in ("natural", "landuse"):
        kind = COVER_KINDS.get((key, tags.get(key)))
        if kind:
            return kind
    return None


def _points(geometry) -> list:
    return [(g["lon"], g["lat"]) for g in geometry or [] if isinstance(g, dict) and "lat" in g and "lon" in g]


def parse_polygons(data: dict) -> list:
    polygons = []
    for element in data.get("elements", []):
        kind = _kind(element.get("tags") or {})
        if kind is None:
            continue
        if element.get("type") == "way":
            ring = _points(element.get("geometry"))
            outers, inners = ([ring] if len(ring) >= 4 and ring[0] == ring[-1] else []), []
        elif element.get("type") == "relation":
            outer_ways, inner_ways = [], []
            for member in element.get("members") or []:
                if member.get("type") == "way" and member.get("geometry"):
                    (inner_ways if member.get("role") == "inner" else outer_ways).append(_points(member["geometry"]))
            outers, inners = _stitch(outer_ways), _stitch(inner_ways)
        else:
            continue
        if outers:
            xs = [x for ring in outers for x, _ in ring]
            ys = [y for ring in outers for _, y in ring]
            polygons.append(Polygon(kind, outers, inners, (min(xs), min(ys), max(xs), max(ys))))
    return polygons


def cover_shares(polygons: list, samples: list) -> dict:
    counts = {"forest": 0, "open": 0}
    for lat, lon in samples:
        hit = None
        for polygon in polygons:
            if polygon.covers(lon, lat):
                if polygon.kind == "forest":
                    hit = "forest"
                    break
                hit = "open"
        if hit:
            counts[hit] += 1
    total = len(samples) or 1
    return {kind: count / total for kind, count in counts.items()}


class LandCoverPlugin(SectionPlugin):
    """Data only: the share of the route on forest and on open ground (meadows, fields, scrub, heath)."""
    plugin_id = "land_cover"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        samples = densify(ctx.coords)
        digest = hashlib.sha1(route_polyline(ctx.coords).encode("utf-8")).hexdigest()[:12]
        key = f"land_cover|{QUERY_VERSION}|{digest}"
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None:
            value = cached[0]
            return self._section(value["forest"], value["open"], None)
        try:
            data = run(ctx.http, cover_query(route_polyline(ctx.coords)), health=ctx.overpass_health,
                       progress=ctx.progress)
        except OverpassError as e:
            return self._section(0.0, 0.0, str(e))
        # Check if the response was truncated
        if len(data.get("elements", [])) >= ELEMENT_CAP:
            return self._section(0.0, 0.0, "response truncated")
        shares = cover_shares(parse_polygons(data), samples)
        ctx.cache.put(key, shares)
        return self._section(shares["forest"], shares["open"], None)

    @staticmethod
    def _section(forest: float, open_ground: float, error) -> Section:
        return Section("hazards", "", "no-data" if error else "tag-backed", omit=True,
                       shared={"known": error is None, "forest": forest, "open": open_ground,
                               "total": forest + open_ground, "error": error})
