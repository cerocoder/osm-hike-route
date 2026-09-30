"""One combined Overpass query per route for everything the hazard plugins
need from OpenStreetMap: mobile masts, still and running water, glaciers,
scree, cliffs and bare rock, `sac_scale` paths, industrial sites. A separate
query per plugin would multiply the 429/504 failures seen on the public
servers, so this data-only plugin fetches once, caches it for a week and
shares it (`shared["osm_features"]`); it never writes text into the plan
(`omit=True`).

Features are located by their centre point (`out center`), which is exact for
nodes and small areas but crude for a long river: distances are therefore
approximate and every consumer labels its result `derived`."""
import math
from dataclasses import asdict, dataclass

from .base import Section, SectionPlugin
from .overpass import EMPTY_TTL_S, ROUTES_TTL_S, OverpassError, run

MARGIN_KM = 5.0
SAMPLE_MAX = 120
QUERY_VERSION = "1"
_QL = ('[out:json][timeout:9];('
       'nwr["communication:mobile_phone"="yes"]({b});'
       'nwr["man_made"~"^(mast|tower)$"]["tower:type"="communication"]({b});'
       'nwr["natural"~"^(water|wetland|glacier|scree|cliff|bare_rock)$"]({b});'
       'way["waterway"~"^(river|stream|canal)$"]({b});'
       'way["sac_scale"]({b});'
       'nwr["landuse"="industrial"]({b});nwr["power"="plant"]({b});'
       ');out tags center 4000;')


@dataclass
class OsmFeature:
    kind: str      # mast | water | wetland | waterway | glacier | scree | cliff | bare_rock | sac | industrial
    lat: float
    lon: float
    name: str = ""
    detail: str = ""   # waterway type, or the sac_scale value


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))


def route_bbox(coords: list, margin_km: float = MARGIN_KM) -> tuple:
    """(south, west, north, east) of the route plus a margin."""
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    lat_margin = margin_km / 111.0
    lon_margin = margin_km / (111.0 * max(0.2, math.cos(math.radians((min(lats) + max(lats)) / 2))))
    return (min(lats) - lat_margin, min(lons) - lon_margin, max(lats) + lat_margin, max(lons) + lon_margin)


def features_query(bbox: tuple) -> str:
    return _QL.format(b=",".join(f"{x:.5f}" for x in bbox))


def route_samples(coords: list, max_points: int = SAMPLE_MAX) -> list:
    """Up to max_points (lat, lon) taken evenly along the route, always including both ends."""
    if len(coords) <= max_points:
        return [(c[1], c[0]) for c in coords]
    step = (len(coords) - 1) / (max_points - 1)
    picked = sorted({round(i * step) for i in range(max_points)})
    return [(coords[i][1], coords[i][0]) for i in picked]


def classify(tags: dict) -> list:
    """[(kind, detail)] for one OSM element (an element can be several things)."""
    out = []
    if tags.get("communication:mobile_phone") == "yes" or (
            tags.get("man_made") in ("mast", "tower") and tags.get("tower:type") == "communication"):
        out.append(("mast", ""))
    if tags.get("natural") in ("water", "wetland", "glacier", "scree", "cliff", "bare_rock"):
        out.append((tags["natural"], ""))
    if tags.get("waterway") in ("river", "stream", "canal"):
        out.append(("waterway", tags["waterway"]))
    if "sac_scale" in tags:
        out.append(("sac", str(tags["sac_scale"])))
    if tags.get("landuse") == "industrial" or tags.get("power") == "plant":
        out.append(("industrial", ""))
    return out


def parse_features(data: dict) -> list:
    features = []
    for element in data.get("elements", []):
        centre = element.get("center") or element
        lat, lon = centre.get("lat"), centre.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        tags = element.get("tags") or {}
        for kind, detail in classify(tags):
            features.append(OsmFeature(kind, float(lat), float(lon), str(tags.get("name", "")), detail))
    return features


def nearest_m(samples: list, lat: float, lon: float) -> float:
    return min(haversine_m(lat, lon, s_lat, s_lon) for s_lat, s_lon in samples)


def near(features: list, samples: list, kinds, radius_m: float) -> list:
    """[(feature, distance_m)] of the given kinds within radius_m of the route, nearest first."""
    kinds = (kinds,) if isinstance(kinds, str) else tuple(kinds)
    found = []
    for feature in features:
        if feature.kind in kinds:
            distance = nearest_m(samples, feature.lat, feature.lon)
            if distance <= radius_m:
                found.append((feature, distance))
    return sorted(found, key=lambda pair: pair[1])


class OsmFeaturesPlugin(SectionPlugin):
    """Data only: fetches and shares the features; adds nothing to the plan."""
    plugin_id = "osm_features"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        samples = route_samples(ctx.coords)
        bbox = route_bbox(ctx.coords)
        key = f"osm_features|{QUERY_VERSION}|" + "|".join(f"{x:.2f}" for x in bbox)
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None and (cached[0] or ctx.now.timestamp() - cached[1] <= EMPTY_TTL_S):
            features = [OsmFeature(**f) for f in cached[0]]
            return self._section(features, samples, None)
        try:
            features = parse_features(run(ctx.http, features_query(bbox)))
        except OverpassError as e:
            return self._section([], samples, str(e))
        ctx.cache.put(key, [asdict(f) for f in features])
        return self._section(features, samples, None)

    @staticmethod
    def _section(features: list, samples: list, error) -> Section:
        return Section("hazards", "", "tag-backed" if error is None else "no-data", omit=True,
                       shared={"features": features, "samples": samples, "error": error})
