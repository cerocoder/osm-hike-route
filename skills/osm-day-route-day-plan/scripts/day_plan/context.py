"""PlanContext: everything a plugin may read. Built once per run from the
route archive (route.geojson) and the CLI arguments."""
import datetime
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cache import JsonCache
from .facts import load_facts
from .http import get_json, get_text


@dataclass
class RoutePoint:
    """A Point feature of route.geojson (access point or point of interest)."""
    name: str
    type: str
    lat: float
    lon: float
    role: str | None = None            # "start" | "end" for access points
    opening_hours: str | None = None   # raw OSM tag
    access_notes: str | None = None
    note: str | None = None
    osm_id: str | None = None
    ele: float | None = None


@dataclass
class PlanContext:
    route_dir: Path
    date: datetime.date
    lang: str
    departure: str | None
    start_time: datetime.time | None
    mode: str
    route_name: str
    coords: list  # [(lon, lat, ele_or_None), ...] of the route LineString
    distance_km: float | None
    duration_hours: float | None
    centroid: tuple  # (lat, lon), bbox center of the route
    facts: dict
    http: Callable
    cache: JsonCache
    now: datetime.datetime  # timezone-aware UTC
    today: datetime.date = field(init=False)
    http_text: Callable = get_text                        # GET -> text, for services that answer HTML
    access_points: list = field(default_factory=list)    # [RoutePoint] with type == "access"
    interest_points: list = field(default_factory=list)  # [RoutePoint], every other Point feature
    style: str | None = None                             # "leisure" | "sport" for a bicycle, else None
    segments: list | None = None                         # which road each part of the route runs on (route.geojson); None in an older archive

    def __post_init__(self):
        self.today = self.now.date()

    @property
    def date_iso(self) -> str:
        return self.date.isoformat()


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _segments(value, vertex_count: int):
    """The `segments` of the route archive when they are well formed (a list of dicts with integer, contiguous
    from/to ranges covering every vertex), else None: a malformed or missing value must read as "no road data",
    never as a wrong road."""
    if not isinstance(value, list) or not value or vertex_count < 2:
        return None
    expected = 0
    for segment in value:
        if not isinstance(segment, dict):
            return None
        start, end = segment.get("from"), segment.get("to")
        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                or not isinstance(end, int) or start != expected or end <= start):
            return None
        expected = end
    return [dict(s) for s in value] if expected == vertex_count - 1 else None


def _line_feature(geojson: dict) -> dict:
    for feature in geojson.get("features", []):
        if _dict(_dict(feature).get("geometry")).get("type") == "LineString":
            return feature
    raise ValueError("route.geojson has no LineString feature")


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _points(geojson: dict) -> tuple[list, list]:
    access, interest = [], []
    for feature in geojson.get("features", []):
        if not isinstance(feature, dict):
            continue
        geometry = _dict(feature.get("geometry"))
        coords = geometry.get("coordinates")
        if (geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2
                or not (_number(coords[0]) and _number(coords[1]))):
            continue
        props = _dict(feature.get("properties"))
        point = RoutePoint(
            name=_text(props.get("name")) or "Waypoint", type=_text(props.get("type")) or "waypoint",
            lat=coords[1], lon=coords[0], role=_text(props.get("role")),
            opening_hours=_text(props.get("opening_hours")), access_notes=_text(props.get("access_notes")),
            note=_text(props.get("note")), osm_id=_text(props.get("osm_id")),
            ele=coords[2] if len(coords) > 2 else None,
        )
        (access if point.type == "access" else interest).append(point)
    return access, interest


def build_context(route_dir, date: datetime.date, lang: str = "en", departure: str | None = None,
                  start_time: datetime.time | None = None, http: Callable = get_json, http_text: Callable = get_text,
                  cache: JsonCache | None = None, now: datetime.datetime | None = None) -> PlanContext:
    route_dir = Path(route_dir)
    geojson = json.loads((route_dir / "route.geojson").read_text(encoding="utf-8"))
    line = _line_feature(geojson)
    props = _dict(line.get("properties"))
    coords = []
    for c in line["geometry"]["coordinates"]:
        coords.append((c[0], c[1], c[2] if len(c) > 2 else None))
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    if max(lons) - min(lons) > 180.0:  # crosses the antimeridian (e.g. Chukotka)
        lons = [lon + 360.0 if lon < 0 else lon for lon in lons]
    center_lon = (min(lons) + max(lons)) / 2.0
    if center_lon > 180.0:
        center_lon -= 360.0
    centroid = ((min(lats) + max(lats)) / 2.0, center_lon)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    access_points, interest_points = _points(geojson)
    return PlanContext(
        route_dir=route_dir, date=date, lang=lang, departure=departure, start_time=start_time,
        mode=props.get("mode") or "walk",
        style=props.get("style") if isinstance(props.get("style"), str) else None,
        segments=_segments(props.get("segments"), len(coords)),
        route_name=props.get("name") or route_dir.name,
        coords=coords,
        distance_km=props.get("distance_km"),
        duration_hours=props.get("duration_estimate_hours"),
        centroid=centroid,
        facts=load_facts(route_dir),
        http=http, http_text=http_text,
        cache=cache if cache is not None else JsonCache(route_dir / "day_plan_cache.json", now=now.timestamp),
        now=now,
        access_points=access_points, interest_points=interest_points,
    )
