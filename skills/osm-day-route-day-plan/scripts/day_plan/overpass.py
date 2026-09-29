"""Minimal Overpass client for the day plan: the public transport lines that
serve an access point. Mirrors and retries are copied from
osm-day-route-planning/scripts/overpass_query.py on purpose (the skills do not
import each other); measured while building this: overpass-api.de answered
429 and 504 under load, overpass.kumi.systems 504, overpass.private.coffee
sometimes returns HTML — so a failed mirror is skipped and the whole set is
retried once after a pause. Any failure ends as OverpassError, which the
plugin turns into a no-data section."""
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass

from .http import HttpError
from .i18n import tr

MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
ROUTE_TYPES = ("bus", "train", "subway", "tram", "light_rail", "trolleybus", "ferry")
ROUTES_TTL_S = 7 * 86400


class OverpassError(Exception):
    pass


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)          # its own function so tests can silence it without touching time.sleep


def run(http, ql: str, mirrors=MIRRORS, retries: int = 1, sleep=None, backoff: float = 3.0) -> dict:
    sleep = sleep or _default_sleep
    last = "no mirror tried"
    for attempt in range(retries + 1):
        for mirror in mirrors:
            try:
                data = http(f"{mirror}?data={urllib.parse.quote(ql)}")
            except HttpError as e:
                last = f"{mirror}: {e}"
                continue
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                last = f"{mirror}: unexpected response"
                continue
            if "runtime error" in str(data.get("remark", "")).lower():
                last = f"{mirror}: {data.get('remark')}"
                continue
            return data
        if attempt < retries:
            sleep(backoff * (attempt + 1))
    raise OverpassError(last)


@dataclass
class RouteInfo:
    mode: str
    ref: str
    name: str
    from_: str
    to: str
    interval: str
    opening_hours: str
    operator: str


def routes_query(lat: float, lon: float, radius: int = 80) -> str:
    types = "|".join(ROUTE_TYPES)
    return (f'[out:json][timeout:25];node(around:{radius},{lat:.5f},{lon:.5f})["public_transport"];'
            f'rel(bn)["route"~"^({types})$"];out tags;')


def parse_routes(data: dict) -> list:
    """Overpass `out tags` result -> de-duplicated RouteInfo list, sorted by
    mode and line number."""
    seen, routes = set(), []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        if tags.get("route") not in ROUTE_TYPES:
            continue
        info = RouteInfo(mode=tags["route"], ref=tags.get("ref", ""), name=tags.get("name", ""),
                         from_=tags.get("from", ""), to=tags.get("to", ""), interval=tags.get("interval", ""),
                         opening_hours=tags.get("opening_hours", ""), operator=tags.get("operator", ""))
        key = (info.mode, info.ref, info.name or (info.from_, info.to))
        if key in seen:
            continue
        seen.add(key)
        routes.append(info)

    def natural(text):
        return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]

    routes.sort(key=lambda r: (ROUTE_TYPES.index(r.mode), natural(r.ref), r.name))
    return routes


def routes_near(ctx, lat: float, lon: float) -> list:
    """RouteInfo list for the lines through public-transport nodes near a point
    (cached 7 days in the route folder). Raises OverpassError."""
    key = f"overpass|routes|{lat:.4f}|{lon:.4f}"
    cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
    if cached is not None:
        return [RouteInfo(**r) for r in cached[0]]
    routes = parse_routes(run(ctx.http, routes_query(lat, lon)))
    ctx.cache.put(key, [asdict(r) for r in routes])
    return routes


_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def interval_minutes(raw: str) -> int | None:
    """OSM `interval`: '10' (minutes), '00:10' or '00:10:00' (h:mm[:ss])."""
    raw = (raw or "").strip()
    if raw.isdigit():
        return int(raw) or None
    m = _CLOCK.match(raw)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) or None
    return None


def format_interval(raw: str, lang: str) -> str:
    minutes = interval_minutes(raw)
    if minutes is not None:
        return tr("tr_every", lang, n=minutes)
    return raw or "–"
