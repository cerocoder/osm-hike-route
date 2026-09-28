"""Live tile-coverage probe: a single tile fetch per point, used by
TileProviderPlugin.covers() (see providers/base.py). Lightweight
liveness/coverage check, not a replacement for the more rigorous
multi-zoom hash-comparison research in tile-providers-research.md — see
design spec 2026-09-28-osm-day-route-show-tile-providers-design.md."""
import http.client
import math
import urllib.error
import urllib.request

TILE_PROBE_ZOOM = 15
_USER_AGENT = "osm-day-route-show/1.0 (tile_providers coverage probe)"
# Guards against a 200 response whose body is a tiny placeholder/error
# tile — the same class of failure documented in SKILL.md's Common
# Mistakes for Wikimedia's cache-masked block page.
_MIN_BODY_BYTES = 256


def latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Standard slippy-map (Web Mercator / EPSG:3857) tile coordinates."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _fetch(url: str, timeout: float) -> tuple[int, str, bytes]:
    """Thin urllib wrapper — the single call site tests patch, mirroring
    place_info providers' `_http_get_json` pattern."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def probe_tile(url_template: str, lat: float, lon: float, zoom: int, timeout: float) -> bool:
    """One tile fetch at (lat, lon, zoom). True only on HTTP 200, an
    image/* Content-Type, and a body large enough not to be a placeholder
    tile. Any exception (timeout, DNS failure, HTTP error status)
    resolves to False — a coverage probe must never crash the render."""
    x, y = latlon_to_tile(lat, lon, zoom)
    url = url_template.format(z=zoom, x=x, y=y)
    try:
        status, content_type, body = _fetch(url, timeout)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return False
    return status == 200 and content_type.startswith("image/") and len(body) >= _MIN_BODY_BYTES
