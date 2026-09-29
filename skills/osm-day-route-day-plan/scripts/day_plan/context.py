"""PlanContext: everything a plugin may read. Built once per run from the
route archive (route.geojson) and the CLI arguments."""
import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cache import JsonCache
from .facts import load_facts
from .http import get_json


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

    def __post_init__(self):
        self.today = self.now.date()

    @property
    def date_iso(self) -> str:
        return self.date.isoformat()


def _line_feature(geojson: dict) -> dict:
    for feature in geojson.get("features", []):
        if (feature.get("geometry") or {}).get("type") == "LineString":
            return feature
    raise ValueError("route.geojson has no LineString feature")


def build_context(route_dir, date: datetime.date, lang: str = "en", departure: str | None = None,
                  start_time: datetime.time | None = None, http: Callable = get_json,
                  cache: JsonCache | None = None, now: datetime.datetime | None = None) -> PlanContext:
    route_dir = Path(route_dir)
    geojson = json.loads((route_dir / "route.geojson").read_text(encoding="utf-8"))
    line = _line_feature(geojson)
    props = line.get("properties") or {}
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
    return PlanContext(
        route_dir=route_dir, date=date, lang=lang, departure=departure, start_time=start_time,
        mode=props.get("mode") or "walk",
        route_name=props.get("name") or route_dir.name,
        coords=coords,
        distance_km=props.get("distance_km"),
        duration_hours=props.get("duration_estimate_hours"),
        centroid=centroid,
        facts=load_facts(route_dir),
        http=http,
        cache=cache if cache is not None else JsonCache(route_dir / "day_plan_cache.json", now=now.timestamp),
        now=now,
    )
