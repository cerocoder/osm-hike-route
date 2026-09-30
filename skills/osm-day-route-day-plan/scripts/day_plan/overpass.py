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
EMPTY_TTL_S = 86400          # "no lines" may be a query that gave up early: look again after a day


class OverpassError(Exception):
    pass


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)          # its own function so tests can silence it without touching time.sleep


class MirrorHealth:
    """What one day-plan run has learnt about the mirrors. Several plugins ask Overpass one after another; a mirror
    that has just timed out would otherwise cost every one of them its full timeout again. The mirror that last
    answered is tried first, mirrors that failed are tried last; nothing is written to disk."""

    def __init__(self):
        self._last_ok = None
        self._failed = set()

    def ordered(self, mirrors) -> list:
        mirrors = list(mirrors)
        first = [m for m in mirrors if m == self._last_ok]
        healthy = [m for m in mirrors if m != self._last_ok and m not in self._failed]
        failed = [m for m in mirrors if m != self._last_ok and m in self._failed]
        return first + healthy + failed

    def worked(self, mirror: str) -> None:
        self._last_ok = mirror
        self._failed.discard(mirror)

    def failed(self, mirror: str) -> None:
        self._failed.add(mirror)
        if self._last_ok == mirror:
            self._last_ok = None


def _host(mirror: str) -> str:
    return urllib.parse.urlparse(mirror).netloc or mirror


def run(http, ql: str, mirrors=MIRRORS, retries: int = 1, sleep=None, backoff: float = 3.0,
        health=None, progress=None) -> dict:
    """The first mirror that answers with a usable result. `health` (a MirrorHealth shared by the calls of one run)
    reorders the mirrors; `progress` (optional, see progress.py) is told why a mirror was skipped and when the set is
    tried again."""
    sleep = sleep or _default_sleep
    last = "no mirror tried"
    for attempt in range(retries + 1):
        order = health.ordered(mirrors) if health is not None else list(mirrors)
        if attempt and progress is not None and order:
            progress.note("overpass_attempt", endpoint=_host(order[0]), n=attempt + 1, m=retries + 1)
        for mirror in order:
            try:
                data = http(f"{mirror}?data={urllib.parse.quote(ql)}")
            except HttpError as e:
                last = f"{mirror}: {e}"
                _failed(health, progress, mirror, e)
                continue
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                last = f"{mirror}: unexpected response"
                _failed(health, progress, mirror, "unexpected response")
                continue
            if "runtime error" in str(data.get("remark", "")).lower():
                last = f"{mirror}: {data.get('remark')}"
                _failed(health, progress, mirror, data.get("remark"))
                continue
            if health is not None:
                health.worked(mirror)
            return data
        if attempt < retries:
            sleep(backoff * (attempt + 1))
    raise OverpassError(last)


def _failed(health, progress, mirror: str, reason) -> None:
    if health is not None:
        health.failed(mirror)
    if progress is not None:
        progress.warn("overpass_failed", endpoint=_host(mirror), reason=" ".join(str(reason).split())[:80])


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
    return (f'[out:json][timeout:9];node(around:{radius},{lat:.5f},{lon:.5f})["public_transport"];'
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
    cached = ctx.cache.get_entry(key)
    if cached is not None:
        value = cached[0]
        if ctx.cache.get_entry(key, ROUTES_TTL_S if value else EMPTY_TTL_S) is not None:
            return [RouteInfo(**r) for r in value]
    routes = parse_routes(run(ctx.http, routes_query(lat, lon), health=ctx.overpass_health, progress=ctx.progress))
    ctx.cache.put(key, [asdict(r) for r in routes])
    return routes


_CLOCK = re.compile(r"([0-9]{1,2}):([0-9]{2})(?::[0-9]{2})?")


def interval_minutes(raw: str) -> int | None:
    """OSM `interval`: '10' (minutes), '00:10' or '00:10:00' (h:mm[:ss])."""
    raw = (raw or "").strip()
    if re.fullmatch(r"[0-9]+", raw):
        return int(raw) or None
    m = _CLOCK.fullmatch(raw)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) or None
    return None


def format_interval(raw: str, lang: str) -> str:
    minutes = interval_minutes(raw)
    if minutes is not None:
        return tr("tr_every", lang, n=minutes)
    return raw or "–"
