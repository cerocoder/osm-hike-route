# Tile Provider Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tile-provider plugin system to `osm-day-route-show` — Esri street (existing), Esri satellite, CyclOSM, and IGN España `MTN`, each declaring worldwide vs. probed coverage, exposed as an in-browser Leaflet layer switcher.

**Architecture:** New `scripts/tile_providers/` package mirroring the existing `scripts/place_info/` plugin architecture: a shared `TileProviderPlugin` interface, one module per plugin, a `TileProviderService` aggregator with per-plugin fault isolation and a `tile_coverage.json` cache. `render_map.py` picks a default active base layer and, when more than one provider covers the route, adds a Leaflet `L.control.layers` switcher — no chat-based prompt.

**Tech Stack:** Python 3.10+ stdlib only (`urllib.request`, `json`, `math`, `abc`, `dataclasses`, `pathlib`) — same zero-external-runtime-dependency rule as the rest of this skill. pytest for tests (already the project's test runner).

**Spec:** `docs/superpowers/specs/2026-09-28-osm-day-route-show-tile-providers-design.md`

## Global Constraints

- Stdlib only — no `requests`, no third-party HTTP client, anywhere in `tile_providers/` (spec Context; Global Constraint already established for this whole skill).
- Every plugin's `covers()` / probe must never raise — network/parsing failures resolve to `False`, never propagate (spec: fault isolation, mirrors `PlaceInfoService.fetch_all`).
- `esri_street` and `esri_satellite` are `always_available = True` — never probed, never written to `tile_coverage.json` (spec: Plugin interface, Cache).
- Coverage probe point selection: access points (`properties.type == "access"`) if any exist, else interest points (`properties.type == "interest"`), else no probing at all — only `always_available` plugins offered (spec: Coverage point selection, user-amended during brainstorming).
- `tile_coverage.json` is a **separate** cache file from `place_info.json`, keyed by `provider_id` + the full sorted set of probe points, not per-point (spec: Cache).
- Fixed probe zoom `TILE_PROBE_ZOOM = 15` (spec: Coverage probing).
- CyclOSM's tile URL template uses `{z}/{x}/{y}` order; both Esri templates use `{z}/{y}/{x}` — this must be exactly right per provider, it's a documented past bug class in this codebase (spec: table note; `SKILL.md` Common Mistakes already warns about a sibling issue).
- No chat-based provider picker — the Leaflet layer control in the rendered page is the only UI for switching providers (spec: Non-goals).

## Review Focus

- A non-`always_available` provider (CyclOSM, IGN) probed against a location it has no real data for (e.g. IGN outside Spain) must resolve to `False` and simply not appear in the switcher — not raise, not silently include a broken layer.
- A probe that times out or hits a network/DNS error must degrade to `False` for that one provider without stopping the whole render (same discipline as `PlaceInfoService.fetch_all`, spec: Fault isolation).
- A route with **no** `access`-type points and **no** `interest`-type points (e.g. a bare LineString-only legacy archive) must skip probing entirely and still render with just the two `always_available` Esri layers, no crash.
- `--tile-provider <id>` naming a provider that isn't actually available for this route's location must fail loudly (a clear error), not silently fall back to something else or render a broken layer.
- A second render of the same route directory must not re-probe CyclOSM/IGN over the network — `tile_coverage.json` cache hit must short-circuit the probe entirely.

---

## File Structure

```
skills/osm-day-route-show/scripts/tile_providers/
  __init__.py                      # TileProviderService  (Task 4)
  probe.py                         # latlon_to_tile, probe_tile  (Task 1)
  cache.py                         # cache_key/load_cache/save_entry  (Task 2)
  providers/
    __init__.py                    # empty, package marker  (Task 1)
    base.py                        # TileProviderPlugin  (Task 1)
    esri_street.py                 # EsriStreetProvider  (Task 3)
    esri_satellite.py              # EsriSatelliteProvider  (Task 3)
    cyclosm.py                     # CyclOsmProvider  (Task 3)
    ign_es_mtn.py                  # IgnEsMtnProvider  (Task 3)

skills/osm-day-route-show/scripts/render_map.py   # modified (Task 5, 6, 7)

skills/osm-day-route-show/tests/
  test_tile_providers_probe.py     # Task 1
  test_tile_providers_cache.py     # Task 2
  test_tile_providers_plugins.py   # Task 3
  test_tile_providers_service.py   # Task 4
  test_render_map.py               # modified — appended (Task 5, 6, 7)

skills/osm-day-route-show/SKILL.md                 # modified (Task 7)
```

All test files run from `skills/osm-day-route-show/` via `python3 -m pytest tests/ -v` — `tests/conftest.py` already puts `scripts/` on `sys.path`, so `tile_providers` imports the same way `place_info` already does in existing tests.

---

### Task 1: `tile_providers` package skeleton — `base.py` + `probe.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/tile_providers/__init__.py` (empty for now — Task 4 fills it in)
- Create: `skills/osm-day-route-show/scripts/tile_providers/probe.py`
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/__init__.py` (empty)
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/base.py`
- Test: `skills/osm-day-route-show/tests/test_tile_providers_probe.py`

**Interfaces:**
- Produces: `tile_providers.probe.latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]`
- Produces: `tile_providers.probe.probe_tile(url_template: str, lat: float, lon: float, zoom: int, timeout: float) -> bool`
- Produces: `tile_providers.probe.TILE_PROBE_ZOOM: int = 15`
- Produces: `tile_providers.probe._fetch(url: str, timeout: float) -> tuple[int, str, bytes]` (private, patched directly by tests — same pattern as `place_info.providers.wikimedia_commons._http_get_json`)
- Produces: `tile_providers.providers.base.TileProviderPlugin` — class attributes `provider_id: str`, `display_name: str`, `tile_url_template: str`, `attribution: str`, `max_zoom: int`, `max_native_zoom: int | None`, `always_available: bool = False`; method `covers(self, points: list[tuple[float, float]], timeout: float = 5.0) -> bool`

- [ ] **Step 1: Write the failing tests for `probe.py`**

```python
# skills/osm-day-route-show/tests/test_tile_providers_probe.py
from unittest.mock import patch

from tile_providers.probe import latlon_to_tile, probe_tile


def test_latlon_to_tile_zoom_zero_is_always_the_single_tile():
    assert latlon_to_tile(0.0, 0.0, 0) == (0, 0)


def test_latlon_to_tile_known_reference_point():
    # Madrid, ~40.4168 N, -3.7038 E at zoom 10 — standard slippy-map formula.
    x, y = latlon_to_tile(40.4168, -3.7038, 10)
    assert (x, y) == (503, 383)


def test_probe_tile_true_on_200_image_response():
    with patch("tile_providers.probe._fetch", return_value=(200, "image/png", b"x" * 1000)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is True


def test_probe_tile_false_on_tiny_body():
    """A 200 response with a placeholder-sized body must not count as coverage —
    Review Focus: a provider with no real data for a point (e.g. IGN outside Spain)
    must resolve to False, not a false positive."""
    with patch("tile_providers.probe._fetch", return_value=(200, "image/png", b"x" * 10)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is False


def test_probe_tile_false_on_non_image_content_type():
    with patch("tile_providers.probe._fetch", return_value=(200, "text/html", b"x" * 1000)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is False


def test_probe_tile_false_on_network_error_never_raises():
    """Review Focus: a timeout/DNS/HTTP error must degrade to False, never propagate."""
    import urllib.error

    with patch("tile_providers.probe._fetch", side_effect=urllib.error.URLError("boom")):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is False


def test_probe_tile_formats_url_with_z_x_y():
    captured = {}

    def fake_fetch(url, timeout):
        captured["url"] = url
        return 200, "image/png", b"x" * 1000

    with patch("tile_providers.probe._fetch", side_effect=fake_fetch):
        probe_tile("https://example.org/{z}/{x}/{y}.png", 40.4168, -3.7038, 10, 5.0)

    assert captured["url"] == "https://example.org/10/503/383.png"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `skills/osm-day-route-show/`): `python3 -m pytest tests/test_tile_providers_probe.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'tile_providers'`

- [ ] **Step 3: Implement `probe.py`**

```python
# skills/osm-day-route-show/scripts/tile_providers/probe.py
"""Live tile-coverage probe: a single tile fetch per point, used by
TileProviderPlugin.covers() (see providers/base.py). Lightweight
liveness/coverage check, not a replacement for the more rigorous
multi-zoom hash-comparison research in tile-providers-research.md — see
design spec 2026-09-28-osm-day-route-show-tile-providers-design.md."""
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
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return status == 200 and content_type.startswith("image/") and len(body) >= _MIN_BODY_BYTES
```

- [ ] **Step 4: Write `providers/base.py` (no separate failing-test step — covered by Task 3's plugin tests and Task 4's service tests, which import it directly)**

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/base.py
"""Common interface every tile-provider plugin implements — mirrors
place_info/providers/base.py. TileProviderService only talks to this
interface."""
from ..probe import TILE_PROBE_ZOOM, probe_tile


class TileProviderPlugin:
    provider_id: str
    display_name: str
    tile_url_template: str
    attribution: str
    max_zoom: int
    max_native_zoom: int | None
    always_available: bool = False

    def covers(self, points: list[tuple[float, float]], timeout: float = 5.0) -> bool:
        """`points` is a list of (lat, lon). True immediately, with no
        network call, when always_available. Otherwise requires every
        point to succeed a live tile probe at TILE_PROBE_ZOOM. An empty
        `points` list means "nothing to probe" and resolves to False —
        callers (TileProviderService) are the ones that decide an empty
        list means "skip this provider, offer only always_available
        ones", not this method."""
        if self.always_available:
            return True
        if not points:
            return False
        return all(
            probe_tile(self.tile_url_template, lat, lon, TILE_PROBE_ZOOM, timeout)
            for lat, lon in points
        )
```

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/__init__.py
```

```python
# skills/osm-day-route-show/scripts/tile_providers/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tile_providers_probe.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/tile_providers/probe.py scripts/tile_providers/providers/base.py \
        scripts/tile_providers/providers/__init__.py scripts/tile_providers/__init__.py \
        tests/test_tile_providers_probe.py
git commit -m "Add tile_providers package skeleton: probe.py + TileProviderPlugin base"
```

---

### Task 2: `tile_providers/cache.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/tile_providers/cache.py`
- Test: `skills/osm-day-route-show/tests/test_tile_providers_cache.py`

**Interfaces:**
- Consumes: nothing from Task 1 (stdlib only).
- Produces: `tile_providers.cache.cache_key(provider_id: str, points: list[tuple[float, float]]) -> str`
- Produces: `tile_providers.cache.load_cache(path: Path) -> dict`
- Produces: `tile_providers.cache.save_entry(path: Path, cache: dict, key: str, covers: bool) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_tile_providers_cache.py
import json

from tile_providers.cache import cache_key, load_cache, save_entry


def test_cache_key_is_order_independent_for_same_point_set():
    """Two access points passed in either order must hash to the same key —
    otherwise a cache miss on point-order alone defeats the whole cache."""
    k1 = cache_key("cyclosm", [(40.1, -3.1), (40.2, -3.2)])
    k2 = cache_key("cyclosm", [(40.2, -3.2), (40.1, -3.1)])
    assert k1 == k2


def test_cache_key_differs_by_provider_and_by_points():
    base = cache_key("cyclosm", [(40.1, -3.1)])
    assert base != cache_key("ign_es_mtn", [(40.1, -3.1)])
    assert base != cache_key("cyclosm", [(41.1, -3.1)])


def test_load_cache_returns_empty_dict_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "tile_coverage.json") == {}


def test_load_cache_returns_empty_dict_on_corrupt_json(tmp_path):
    path = tmp_path / "tile_coverage.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_cache(path) == {}


def test_save_entry_then_load_round_trips(tmp_path):
    path = tmp_path / "tile_coverage.json"
    cache = {}
    save_entry(path, cache, "cyclosm|40.1:-3.1", True)

    reloaded = load_cache(path)

    assert reloaded == {"cyclosm|40.1:-3.1": True}


def test_save_entry_preserves_earlier_entries(tmp_path):
    """Review Focus: incremental writes must not lose prior probe results
    if a later probe in the same run fails or the run is interrupted."""
    path = tmp_path / "tile_coverage.json"
    cache = {}
    save_entry(path, cache, "cyclosm|40.1:-3.1", True)
    save_entry(path, cache, "ign_es_mtn|40.1:-3.1", False)

    on_disk = json.loads(path.read_text(encoding="utf-8"))

    assert on_disk == {"cyclosm|40.1:-3.1": True, "ign_es_mtn|40.1:-3.1": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tile_providers_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tile_providers.cache'`

- [ ] **Step 3: Implement `cache.py`**

```python
# skills/osm-day-route-show/scripts/tile_providers/cache.py
"""tile_coverage.json — one cache file per route, separate from
place_info.json (different semantics: boolean coverage per provider per
point-set, not a per-provider/per-point result object). Mirrors
place_info/cache.py's incremental-write pattern: a slow/rate-limited
probe run that gets killed by an outer timeout must not lose probes it
already completed."""
import json
from pathlib import Path


def cache_key(provider_id: str, points: list[tuple[float, float]]) -> str:
    coords = ",".join(f"{round(lat, 5)}:{round(lon, 5)}" for lat, lon in sorted(points))
    return f"{provider_id}|{coords}"


def load_cache(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_entry(path: Path, cache: dict, key: str, covers: bool) -> None:
    cache[key] = covers
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tile_providers_cache.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/tile_providers/cache.py tests/test_tile_providers_cache.py
git commit -m "Add tile_providers/cache.py for tile_coverage.json"
```

---

### Task 3: The four provider plugins

**Files:**
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/esri_street.py`
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/esri_satellite.py`
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/cyclosm.py`
- Create: `skills/osm-day-route-show/scripts/tile_providers/providers/ign_es_mtn.py`
- Test: `skills/osm-day-route-show/tests/test_tile_providers_plugins.py`

**Interfaces:**
- Consumes: `tile_providers.providers.base.TileProviderPlugin` (Task 1)
- Produces: `EsriStreetProvider`, `EsriSatelliteProvider`, `CyclOsmProvider`, `IgnEsMtnProvider` — each a zero-arg-constructible class with the attributes listed in the design spec's provider table, importable as `from tile_providers.providers.esri_street import EsriStreetProvider` etc.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_tile_providers_plugins.py
from unittest.mock import patch

from tile_providers.providers.esri_street import EsriStreetProvider
from tile_providers.providers.esri_satellite import EsriSatelliteProvider
from tile_providers.providers.cyclosm import CyclOsmProvider
from tile_providers.providers.ign_es_mtn import IgnEsMtnProvider


def test_esri_street_is_always_available_and_never_probes():
    provider = EsriStreetProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([(40.0, -3.0)], timeout=5.0) is True
    mock_probe.assert_not_called()


def test_esri_satellite_is_always_available_and_never_probes():
    provider = EsriSatelliteProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([], timeout=5.0) is True
    mock_probe.assert_not_called()


def test_esri_street_url_template_uses_z_y_x_order():
    provider = EsriStreetProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/10/383/503"


def test_esri_satellite_url_template_uses_z_y_x_order():
    provider = EsriSatelliteProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/10/383/503"


def test_cyclosm_url_template_uses_z_x_y_order():
    """Review Focus / Global Constraint: CyclOSM's template order is
    {z}/{x}/{y}, the opposite of the two Esri templates above — getting
    this backwards silently loads the wrong tiles."""
    provider = CyclOsmProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://tile-cyclosm.openstreetmap.fr/cyclosm/10/503/383.png"
    assert provider.always_available is False


def test_ign_es_mtn_url_template_has_matrix_row_col_params():
    provider = IgnEsMtnProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert "TileMatrix=10" in url
    assert "TileRow=383" in url
    assert "TileCol=503" in url
    assert provider.always_available is False


def test_all_four_providers_have_distinct_provider_ids():
    ids = {
        EsriStreetProvider().provider_id,
        EsriSatelliteProvider().provider_id,
        CyclOsmProvider().provider_id,
        IgnEsMtnProvider().provider_id,
    }
    assert ids == {"esri_street", "esri_satellite", "cyclosm", "ign_es_mtn"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tile_providers_plugins.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tile_providers.providers.esri_street'`

- [ ] **Step 3: Implement the four plugin modules**

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/esri_street.py
"""Esri's public World_Street_Map REST tiles — already the production
base layer before this plugin system existed (SKILL.md Common Mistakes:
tile.openstreetmap.org, CARTO Voyager, and Wikimedia osm-intl were all
tried first and rejected). Worldwide Esri REST service — treated as
always available, same as esri_satellite."""
from .base import TileProviderPlugin


class EsriStreetProvider(TileProviderPlugin):
    provider_id = "esri_street"
    display_name = "Esri Street Map"
    tile_url_template = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                          "World_Street_Map/MapServer/tile/{z}/{y}/{x}")
    attribution = ("Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, "
                   "Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), "
                   "Esri (Thailand), TomTom")
    max_zoom = 19
    max_native_zoom = 19
    always_available = True
```

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/esri_satellite.py
"""Esri's public World_Imagery REST tiles (satellite) — same trusted host
as esri_street, genuinely unique high-res data through z20+ at the point
tested in tile-providers-research.md. Worldwide Esri REST service —
treated as always available, same reasoning as esri_street."""
from .base import TileProviderPlugin


class EsriSatelliteProvider(TileProviderPlugin):
    provider_id = "esri_satellite"
    display_name = "Esri Satellite"
    tile_url_template = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                          "World_Imagery/MapServer/tile/{z}/{y}/{x}")
    attribution = ("Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
                   "and the GIS User Community")
    max_zoom = 20
    max_native_zoom = 20
    always_available = True
```

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/cyclosm.py
"""CyclOSM — actively maintained OpenStreetMap-France infrastructure,
cycling-oriented style. Not global-by-declaration like the Esri layers,
so it's live-probed per route (tile-providers-research.md found unique
data through z19 at the one point tested, not confirmed worldwide)."""
from .base import TileProviderPlugin


class CyclOsmProvider(TileProviderPlugin):
    provider_id = "cyclosm"
    display_name = "CyclOSM"
    # NOTE: {z}/{x}/{y} order — the opposite of the two Esri templates
    # above, which use {z}/{y}/{x}. See Global Constraints / Review Focus.
    tile_url_template = "https://tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png"
    attribution = ('Map data &copy; <a href="https://www.openstreetmap.org/copyright">'
                   'OpenStreetMap</a> contributors, Tiles style &copy; '
                   '<a href="https://github.com/cyclosm/cyclosm-cartocss-style/releases">CyclOSM</a>')
    max_zoom = 19
    max_native_zoom = 19
    always_available = False
```

```python
# skills/osm-day-route-show/scripts/tile_providers/providers/ign_es_mtn.py
"""IGN España's MTN (Mapa Topografico Nacional) layer via WMTS KVP
addressing — official Spanish government topographic map. Region-limited
by nature (Spain only), so always live-probed, never always_available.
Exact query-string parameters sourced from tile-providers-research.md's
working example (2026-09-28) — reconfirm with a real rendered map before
trusting in production, per this skill's own established verification
bar (SKILL.md Common Mistakes: curl alone has missed a cache-masked
block before)."""
from .base import TileProviderPlugin


class IgnEsMtnProvider(TileProviderPlugin):
    provider_id = "ign_es_mtn"
    display_name = "IGN España (MTN)"
    tile_url_template = (
        "https://www.ign.es/wmts/mapa-raster?service=WMTS&request=GetTile"
        "&version=1.0.0&layer=MTN&style=default&format=image/jpeg"
        "&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}"
    )
    attribution = "CC-BY 4.0 ign.es"
    max_zoom = 19
    max_native_zoom = 19
    always_available = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tile_providers_plugins.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/tile_providers/providers/esri_street.py scripts/tile_providers/providers/esri_satellite.py \
        scripts/tile_providers/providers/cyclosm.py scripts/tile_providers/providers/ign_es_mtn.py \
        tests/test_tile_providers_plugins.py
git commit -m "Add the four tile-provider plugins: esri_street, esri_satellite, cyclosm, ign_es_mtn"
```

---

### Task 4: `TileProviderService`

**Files:**
- Modify: `skills/osm-day-route-show/scripts/tile_providers/__init__.py` (created empty in Task 1)
- Test: `skills/osm-day-route-show/tests/test_tile_providers_service.py`

**Interfaces:**
- Consumes: `tile_providers.cache.cache_key/load_cache/save_entry` (Task 2), `tile_providers.providers.base.TileProviderPlugin` (Task 1)
- Produces: `tile_providers.TileProviderService(providers: list[TileProviderPlugin], cache_path: Path)` with method `available_providers(self, points: list[tuple[float, float]], timeout: float = 5.0) -> list[TileProviderPlugin]`

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_tile_providers_service.py
from tile_providers import TileProviderService
from tile_providers.providers.base import TileProviderPlugin


class _FakeProvider(TileProviderPlugin):
    def __init__(self, provider_id, always_available=False, result=True, raises=False):
        self.provider_id = provider_id
        self.always_available = always_available
        self._result = result
        self._raises = raises
        self.call_count = 0

    def covers(self, points, timeout=5.0):
        if self.always_available:
            return True
        self.call_count += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._result


def test_always_available_provider_is_offered_without_probing(tmp_path):
    provider = _FakeProvider("esri_street", always_available=True)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["esri_street"]
    assert provider.call_count == 0


def test_provider_that_covers_is_offered(tmp_path):
    provider = _FakeProvider("cyclosm", result=True)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["cyclosm"]


def test_provider_that_does_not_cover_is_excluded(tmp_path):
    provider = _FakeProvider("ign_es_mtn", result=False)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(55.0, 37.0)])  # Moscow — outside Spain

    assert result == []


def test_one_provider_raising_does_not_affect_others(tmp_path):
    """Review Focus: a broken provider must degrade to 'not offered', never
    take down the render or the other providers — same as PlaceInfoService."""
    broken = _FakeProvider("broken", raises=True)
    ok = _FakeProvider("ok", result=True)
    service = TileProviderService([broken, ok], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["ok"]


def test_empty_points_excludes_non_always_available_providers_without_raising(tmp_path):
    """Review Focus: a route with no access/interest points must skip
    probing entirely and still render (only always_available offered)."""
    always = _FakeProvider("esri_street", always_available=True)
    probed = _FakeProvider("cyclosm", result=True)
    service = TileProviderService([always, probed], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([])

    assert [p.provider_id for p in result] == ["esri_street"]
    assert probed.call_count == 0  # covers([]) never even gets to probing


def test_second_call_reuses_cache_and_does_not_reprobe(tmp_path):
    """Review Focus: a second render of the same route must not re-probe
    CyclOSM/IGN over the network."""
    provider = _FakeProvider("cyclosm", result=True)
    cache_path = tmp_path / "tile_coverage.json"

    TileProviderService([provider], cache_path=cache_path).available_providers([(40.0, -3.0)])
    provider.call_count = 0
    second_service = TileProviderService([provider], cache_path=cache_path)
    result = second_service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["cyclosm"]
    assert provider.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tile_providers_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'TileProviderService' from 'tile_providers'`

- [ ] **Step 3: Implement `TileProviderService`**

```python
# skills/osm-day-route-show/scripts/tile_providers/__init__.py
"""Public entry point for tile-provider coverage (design spec
2026-09-28-osm-day-route-show-tile-providers-design.md). Determines
which tile providers are usable for a given route's coverage points and
returns them, in the given plugin-list order, with per-plugin fault
isolation identical to place_info.PlaceInfoService.fetch_all."""
from pathlib import Path

from .cache import cache_key, load_cache, save_entry
from .providers.base import TileProviderPlugin


class TileProviderService:
    def __init__(self, providers: list[TileProviderPlugin], cache_path: Path):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._cache = load_cache(self._cache_path)

    def available_providers(self, points: list[tuple[float, float]],
                             timeout: float = 5.0) -> list[TileProviderPlugin]:
        available = []
        for provider in self._providers:
            if provider.always_available:
                available.append(provider)
                continue
            key = cache_key(provider.provider_id, points)
            if key in self._cache:
                if self._cache[key]:
                    available.append(provider)
                continue
            try:
                covers = provider.covers(points, timeout)
            except Exception:
                # A single broken plugin must not take down the others or
                # the render — same discipline as PlaceInfoService.fetch_all.
                covers = False
            save_entry(self._cache_path, self._cache, key, covers)
            if covers:
                available.append(provider)
        return available
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tile_providers_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full tile_providers test suite together**

Run: `python3 -m pytest tests/test_tile_providers_probe.py tests/test_tile_providers_cache.py tests/test_tile_providers_plugins.py tests/test_tile_providers_service.py -v`
Expected: PASS (27 passed)

- [ ] **Step 6: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/tile_providers/__init__.py tests/test_tile_providers_service.py
git commit -m "Add TileProviderService: fault-isolated, cached coverage lookup"
```

---

### Task 5: `render_map.py` — coverage-point selection helper

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Modify (append tests): `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Consumes: nothing new (plain GeoJSON dict, same shape `build_gpx`/`bbox_center_zoom` already consume).
- Produces: `render_map._tile_coverage_points(geojson: dict) -> list[tuple[float, float]]` — `(lat, lon)` tuples, consumed by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_map.py`:

```python
from render_map import _tile_coverage_points


def _geojson_with_access_and_interest_points():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
             "properties": {"name": "Route"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
             "properties": {"type": "access", "name": "Start"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.001, 55.001]},
             "properties": {"type": "access", "name": "End"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005]},
             "properties": {"type": "interest", "name": "Spring"}},
        ],
    }


def test_tile_coverage_points_prefers_access_points():
    points = _tile_coverage_points(_geojson_with_access_and_interest_points())
    assert set(points) == {(55.0, 37.0), (55.001, 37.001)}


def test_tile_coverage_points_falls_back_to_interest_points_when_no_access():
    geojson = _geojson_with_access_and_interest_points()
    for f in geojson["features"]:
        if f["geometry"]["type"] == "Point" and f["properties"]["type"] == "access":
            f["properties"]["type"] = "waypoint"  # neither access nor interest

    points = _tile_coverage_points(geojson)

    assert points == [(55.0005, 37.0005)]


def test_tile_coverage_points_empty_when_no_access_or_interest_points():
    """Review Focus: a legacy LineString-only archive must not crash —
    empty result means 'skip probing', handled by TileProviderService."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
             "properties": {"name": "Old route"}},
        ],
    }

    assert _tile_coverage_points(geojson) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -k tile_coverage_points -v`
Expected: FAIL — `ImportError: cannot import name '_tile_coverage_points' from 'render_map'`

- [ ] **Step 3: Implement `_tile_coverage_points`**

Add to `render_map.py`, near `bbox_center_zoom` (same "GPX / external links" section is the wrong place — add a new section comment above it, right before `bbox_center_zoom`):

```python
# ---------------------------------------------------------------------------
# Tile providers
# ---------------------------------------------------------------------------

def _tile_coverage_points(geojson: dict) -> list[tuple[float, float]]:
    """(lat, lon) points used to probe tile-provider coverage: access
    points if any exist, else interest points, else empty (design spec:
    Coverage point selection — an empty result means TileProviderService
    skips probing entirely and offers only always_available providers)."""
    access, interest = [], []
    for f in geojson.get("features", []):
        if f["geometry"]["type"] != "Point":
            continue
        coord = f["geometry"]["coordinates"]
        lat, lon = coord[1], coord[0]
        ptype = (f.get("properties") or {}).get("type")
        if ptype == "access":
            access.append((lat, lon))
        elif ptype == "interest":
            interest.append((lat, lon))
    return access or interest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -k tile_coverage_points -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the whole test_render_map.py file to check nothing broke**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (all, including pre-existing tests)

- [ ] **Step 6: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/render_map.py tests/test_render_map.py
git commit -m "Add _tile_coverage_points: access-then-interest fallback for coverage probing"
```

---

### Task 6: `render_map.py` — `build_tile_layers_js` pure HTML/JS builder

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Modify (append tests): `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Consumes: `tile_providers.providers.base.TileProviderPlugin` instances (duck-typed — any object with `provider_id`, `display_name`, `tile_url_template`, `attribution`, `max_zoom`, `max_native_zoom`).
- Produces: `render_map.build_tile_layers_js(providers: list, active_id: str | None) -> str` — a JS snippet (one `const tileLayerN = L.tileLayer(...)` per provider, `.addTo(map)` on the active one, and an `L.control.layers({...}).addTo(map)` call only when `len(providers) > 1`), consumed by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_map.py`:

```python
from render_map import build_tile_layers_js


class _FakeTileProvider:
    def __init__(self, provider_id, display_name="Test Layer", max_native_zoom=19):
        self.provider_id = provider_id
        self.display_name = display_name
        self.tile_url_template = f"https://example.org/{provider_id}/{{z}}/{{x}}/{{y}}.png"
        self.attribution = f"Attribution for {provider_id}"
        self.max_zoom = 19
        self.max_native_zoom = max_native_zoom


def test_build_tile_layers_js_single_provider_has_no_layer_control():
    provider = _FakeTileProvider("esri_street")
    js = build_tile_layers_js([provider], active_id="esri_street")

    assert "L.tileLayer(" in js
    assert ".addTo(map)" in js
    assert "L.control.layers(" not in js


def test_build_tile_layers_js_multi_provider_adds_layer_control():
    providers = [_FakeTileProvider("esri_street"), _FakeTileProvider("cyclosm")]
    js = build_tile_layers_js(providers, active_id="esri_street")

    assert js.count("L.tileLayer(") == 2
    assert "L.control.layers(" in js
    assert "Test Layer" in js  # display_name present as a key in the control


def test_build_tile_layers_js_active_provider_is_added_to_map():
    providers = [_FakeTileProvider("esri_street"), _FakeTileProvider("cyclosm")]
    js = build_tile_layers_js(providers, active_id="cyclosm")

    lines = js.splitlines()
    cyclosm_var_line = next(l for l in lines if "cyclosm" in l and "L.tileLayer(" in l)
    var_name = cyclosm_var_line.split("=")[0].strip().split()[-1]
    assert f"{var_name}.addTo(map)" in js
    # esri_street's own var must NOT get .addTo(map)
    esri_var_line = next(l for l in lines if "esri_street" in l and "L.tileLayer(" in l)
    esri_var_name = esri_var_line.split("=")[0].strip().split()[-1]
    assert f"{esri_var_name}.addTo(map)" not in js


def test_build_tile_layers_js_defaults_to_first_provider_when_active_id_not_found():
    providers = [_FakeTileProvider("esri_street"), _FakeTileProvider("cyclosm")]
    js = build_tile_layers_js(providers, active_id="does_not_exist")

    esri_var_line = next(l for l in js.splitlines() if "esri_street" in l and "L.tileLayer(" in l)
    var_name = esri_var_line.split("=")[0].strip().split()[-1]
    assert f"{var_name}.addTo(map)" in js


def test_build_tile_layers_js_includes_max_native_zoom_when_present():
    provider = _FakeTileProvider("esri_satellite", max_native_zoom=20)
    js = build_tile_layers_js([provider], active_id="esri_satellite")

    assert '"maxNativeZoom": 20' in js
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -k build_tile_layers_js -v`
Expected: FAIL — `ImportError: cannot import name 'build_tile_layers_js' from 'render_map'`

- [ ] **Step 3: Implement `build_tile_layers_js`**

Add to `render_map.py`, right after `_tile_coverage_points`:

```python
def build_tile_layers_js(providers: list, active_id: str | None) -> str:
    """Pure JS-snippet builder — no network calls. One L.tileLayer(...)
    const per available provider, plus, when more than one provider is
    available, an L.control.layers(...) switcher (design spec: hybrid
    UX — default active layer + in-browser switcher, no chat prompt).
    `providers` must be non-empty. `active_id` selects which provider is
    added to the map directly; falls back to providers[0] when None or
    not found among `providers`."""
    active = next((p for p in providers if p.provider_id == active_id), providers[0])

    lines = []
    control_entries = []
    for i, p in enumerate(providers):
        var = f"tileLayer{i}"
        options = {"attribution": p.attribution, "maxZoom": p.max_zoom}
        if p.max_native_zoom is not None:
            options["maxNativeZoom"] = p.max_native_zoom
        lines.append(
            f"const {var} = L.tileLayer({json.dumps(p.tile_url_template)}, "
            f"{json.dumps(options, ensure_ascii=False)});"
        )
        control_entries.append((p.display_name, var))
        if p is active:
            lines.append(f"{var}.addTo(map);")

    if len(providers) > 1:
        pairs = ", ".join(
            f"{json.dumps(name, ensure_ascii=False)}: {var}" for name, var in control_entries
        )
        lines.append(f"L.control.layers({{{pairs}}}).addTo(map);")

    return "\n  ".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -k build_tile_layers_js -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/render_map.py tests/test_render_map.py
git commit -m "Add build_tile_layers_js: pure JS builder for the base-layer switcher"
```

---

### Task 7: Wire into `build_map_html` / CLI, remove hardcoded layer, update docs

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py` (imports, `build_map_html` signature + body, the HTML template's tile-layer block, `main()`)
- Modify (append tests): `skills/osm-day-route-show/tests/test_render_map.py`
- Modify: `skills/osm-day-route-show/SKILL.md`

**Interfaces:**
- Consumes: `tile_providers.TileProviderService` (Task 4), `EsriStreetProvider`/`EsriSatelliteProvider`/`CyclOsmProvider`/`IgnEsMtnProvider` (Task 3), `_tile_coverage_points` (Task 5), `build_tile_layers_js` (Task 6).
- Produces: `build_map_html(..., tile_provider: str | None = None, tile_timeout: float = 5.0)` — new keyword params; raises `ValueError` when `tile_provider` names a provider not available for the route. `main()` gains `--tile-provider` / `--tile-timeout` CLI flags.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_map.py`:

```python
from unittest.mock import patch


def _geojson_route_in_spain():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[-3.56, 40.25], [-3.559, 40.251]]},
             "properties": {"name": "Ruta"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [-3.56, 40.25]},
             "properties": {"type": "access", "name": "Inicio"}},
        ],
    }


def test_build_map_html_includes_esri_layers_and_control_when_no_forced_provider(tmp_path):
    """cyclosm/ign_es_mtn's probe is forced to fail (patched, no real
    network call) so this test is deterministic offline — esri_street and
    esri_satellite alone are already two always_available providers, so
    the layer control must still appear regardless of CyclOSM/IGN."""
    route_dir = tmp_path / "route"
    route_dir.mkdir()
    geojson_path = route_dir / "route.geojson"
    geojson_path.write_text(json.dumps(_geojson_route_in_spain()), encoding="utf-8")

    with patch("tile_providers.providers.base.probe_tile", return_value=False):
        html = build_map_html(geojson_path, None, title="Test Route", resolve_wiki=False)

    assert "World_Street_Map" in html
    assert "World_Imagery" in html
    assert "L.control.layers(" in html


def test_build_map_html_forced_tile_provider_becomes_active_layer(tmp_path):
    route_dir = tmp_path / "route"
    route_dir.mkdir()
    geojson_path = route_dir / "route.geojson"
    geojson_path.write_text(json.dumps(_geojson_route_in_spain()), encoding="utf-8")

    with patch("tile_providers.providers.base.probe_tile", return_value=False):
        html = build_map_html(geojson_path, None, title="Test Route", resolve_wiki=False,
                               tile_provider="esri_satellite")

    lines = html.splitlines()
    sat_line = next(l for l in lines if "World_Imagery" in l and "L.tileLayer(" in l)
    var_name = sat_line.split("=")[0].strip().split()[-1]
    assert f"{var_name}.addTo(map)" in html


def test_build_map_html_raises_on_unavailable_forced_provider(tmp_path):
    """Review Focus: --tile-provider naming something not available for
    this route must fail loudly, not silently substitute another layer.
    probe_tile is forced to fail so 'cyclosm' is deterministically
    unavailable here, independent of real network access."""
    route_dir = tmp_path / "route"
    route_dir.mkdir()
    geojson_path = route_dir / "route.geojson"
    geojson_path.write_text(json.dumps(_geojson_route_in_spain()), encoding="utf-8")

    with patch("tile_providers.providers.base.probe_tile", return_value=False):
        try:
            build_map_html(geojson_path, None, title="Test Route", resolve_wiki=False,
                            tile_provider="cyclosm")
            assert False, "expected ValueError"
        except ValueError as e:
            assert "cyclosm" in str(e)
```

These three tests patch `tile_providers.providers.base.probe_tile` (the same function `TileProviderPlugin.covers` calls) so `cyclosm`/`ign_es_mtn` never make a real network call and deterministically resolve to unavailable — no dependence on the test environment's outbound network access, matching this project's existing convention of mocking the lowest-level HTTP call site (e.g. `place_info.providers.wikidata._http_get_json` in `tests/test_place_info_wikidata.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -k "build_map_html_includes_esri or forced_tile_provider or unavailable_forced_provider" -v`
Expected: FAIL — `TypeError: build_map_html() got an unexpected keyword argument 'tile_provider'`

- [ ] **Step 3: Add imports and the priority constant**

In `render_map.py`, after the existing `place_info` imports:

```python
from place_info import PlaceInfoService
from place_info.providers.wikipedia import WikipediaProvider
from place_info.providers.wikidata import WikidataProvider
from place_info.providers.wikimedia_commons import WikimediaCommonsProvider
from place_info.providers.opentripmap import OpenTripMapProvider
from tile_providers import TileProviderService
from tile_providers.providers.esri_street import EsriStreetProvider
from tile_providers.providers.esri_satellite import EsriSatelliteProvider
from tile_providers.providers.cyclosm import CyclOsmProvider
from tile_providers.providers.ign_es_mtn import IgnEsMtnProvider

# Default active layer when --tile-provider isn't given: first of these
# that's actually available for the route (design spec: backward-
# compatible default stays esri_street).
TILE_PROVIDER_PRIORITY = ["esri_street", "ign_es_mtn", "cyclosm", "esri_satellite"]
```

- [ ] **Step 4: Modify `build_map_html`'s signature and body**

Change the signature (currently at the line matching `def build_map_html(geojson_path: Path, notes_path: Path | None, title: str,` / `user_lang: str = "en", local_lang: str | None = None,` / `resolve_wiki: bool = True, wiki_timeout: float = 5.0) -> str:`) to:

```python
def build_map_html(geojson_path: Path, notes_path: Path | None, title: str,
                    user_lang: str = "en", local_lang: str | None = None,
                    resolve_wiki: bool = True, wiki_timeout: float = 5.0,
                    tile_provider: str | None = None, tile_timeout: float = 5.0) -> str:
```

Right after the existing `if resolve_wiki: ... annotate_place_info(...)` block (and before the `access_html = ""` line), add:

```python
    tile_cache_path = geojson_path.parent / "tile_coverage.json"
    tile_service = TileProviderService(
        [EsriStreetProvider(), EsriSatelliteProvider(), CyclOsmProvider(), IgnEsMtnProvider()],
        tile_cache_path,
    )
    coverage_points = _tile_coverage_points(geojson)
    available_tile_providers = tile_service.available_providers(coverage_points, timeout=tile_timeout)
    available_tile_ids = [p.provider_id for p in available_tile_providers]

    if tile_provider is not None:
        if tile_provider not in available_tile_ids:
            raise ValueError(
                f"tile provider {tile_provider!r} is not available for this route "
                f"(available: {available_tile_ids})"
            )
        active_tile_provider_id = tile_provider
    else:
        active_tile_provider_id = next(
            (pid for pid in TILE_PROVIDER_PRIORITY if pid in available_tile_ids),
            available_tile_ids[0],
        )
    tile_layers_js = build_tile_layers_js(available_tile_providers, active_tile_provider_id)
```

- [ ] **Step 5: Replace the hardcoded tile-layer block in the HTML template**

Find this block inside the f-string returned by `build_map_html` (currently right after `const map = L.map('map', ...)`):

```
  // Esri's public REST tile service (World_Street_Map) allows this kind of
  // no-key embedded use; OSM's own tile.openstreetmap.org, CARTO's Voyager
  // basemap, and Wikimedia's osm-intl tiles were all tried first and each
  // turned out to block or require a key for standalone-app hotlinking.
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom',
    maxZoom: 19
  }}).addTo(map);
```

Replace it with:

```
  // Tile provider(s) chosen for this route (design spec
  // 2026-09-28-osm-day-route-show-tile-providers-design.md): one
  // L.tileLayer per provider available for this route's location, the
  // active one added directly, an L.control.layers switcher added only
  // when more than one provider is available.
  {tile_layers_js}
```

(Single braces — `tile_layers_js` is a pre-rendered string value being interpolated, the same technique already used for `geojson_json`/`type_labels_js`/`tier_labels_js` elsewhere in this same f-string; its own JS content keeps whatever literal braces it already contains.)

- [ ] **Step 6: Add CLI flags to `main()`**

In `main()`, after the existing `--wiki-timeout` argument:

```python
    parser.add_argument("--tile-provider", default=None,
                         help="force this tile provider as the active map layer "
                              "(esri_street, esri_satellite, cyclosm, ign_es_mtn); "
                              "must be available for the route's location or the "
                              "render fails with an error")
    parser.add_argument("--tile-timeout", type=float, default=5.0,
                         help="per-request timeout in seconds for tile-provider "
                              "coverage probes (cyclosm, ign_es_mtn only — the two "
                              "Esri layers are never probed)")
```

And update the `build_map_html(...)` call inside `main()` to pass them through:

```python
    html = build_map_html(
        geojson_path, notes_path if notes_path.exists() else None, title=title,
        user_lang=args.user_lang, local_lang=args.local_lang,
        resolve_wiki=not args.no_wikipedia, wiki_timeout=args.wiki_timeout,
        tile_provider=args.tile_provider, tile_timeout=args.tile_timeout,
    )
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -k "build_map_html_includes_esri or forced_tile_provider or unavailable_forced_provider" -v`
Expected: PASS (3 passed) — note per Step 1's caveat, this depends on `cyclosm`/`ign_es_mtn` resolving to unavailable in a network-restricted environment; re-read that note if a result surprises you.

- [ ] **Step 8: Run the full existing test suite to check nothing regressed**

Run: `python3 -m pytest tests/ -v`
Expected: PASS, all tests (the pre-existing ~45 plus everything added in Tasks 1–7)

- [ ] **Step 9: Update `SKILL.md`**

Add a new `## Tile Providers` section immediately after the existing `## Place Info` section (right before `## Configuration`):

```markdown
## Tile Providers

The map's base layer comes from one of four independent plugins (design
spec `docs/superpowers/specs/2026-09-28-osm-day-route-show-tile-providers-design.md`),
behind a shared `TileProviderPlugin` interface
(`scripts/tile_providers/providers/base.py`), aggregated by
`TileProviderService` (`scripts/tile_providers/__init__.py`) — the same
plugin-architecture pattern as **Place Info** above, applied to map
tiles instead of point enrichment.

1. **`esri_street`** — Esri's public `World_Street_Map` tiles, the
   layer this skill has always used (see Common Mistakes below for why
   three other "free" providers were rejected first).
2. **`esri_satellite`** — Esri's public `World_Imagery` (satellite)
   tiles, same trusted host as `esri_street`.
3. **`cyclosm`** — OpenStreetMap-France's CyclOSM style
   (`tile-cyclosm.openstreetmap.fr`), cycling-oriented.
4. **`ign_es_mtn`** — IGN España's official `MTN` topographic layer,
   Spain only.

`esri_street` and `esri_satellite` are **always offered** — both are
Esri's own worldwide REST tile services, never probed, never written to
any cache. `cyclosm` and `ign_es_mtn` are **live-probed** per render: one
tile fetch (`tile_providers/probe.py`) per coverage point at a fixed
zoom (`TILE_PROBE_ZOOM = 15`), requiring every point to succeed. A
provider that fails its probe (or raises — `TileProviderService` wraps
each plugin's probe in its own `try/except`, same fault isolation as
`PlaceInfoService.fetch_all`) is simply not offered for that route; it
never breaks the render.

**Coverage points**: access points (`properties.type == "access"`) if
the route has any, else interest points
(`properties.type == "interest"`), else no probing at all (only the two
Esri layers are offered) — `_tile_coverage_points` in `render_map.py`.

**Cache**: probe results are cached in `<route_dir>/tile_coverage.json`
(separate file from `place_info.json` — different key shape), keyed by
provider id plus the full sorted set of coverage points, so a repeat
render of the same route does no network calls for providers already
resolved. Written after each provider's probe completes, not only at
the end of the run, same incremental-write reasoning as
`place_info.json`.

**Picking a layer**: by default the rendered page uses the first
available provider from `esri_street, ign_es_mtn, cyclosm,
esri_satellite` (in that priority order) as the active base layer —
`esri_street` stays the default when it's the only one available,
preserving this skill's existing behavior. Pass `--tile-provider <id>`
to `render_map.py` to force a different active layer; it's an error if
that id isn't available for the route's location. When more than one
provider is available, the rendered page also gets an in-browser
Leaflet layer switcher (`L.control.layers`) so the viewer can change
layers themselves — there's no chat-based "which plugin?" prompt, the
switcher **is** the picker. `--tile-timeout <seconds>` (default 5.0)
controls the per-probe timeout for `cyclosm`/`ign_es_mtn`.
```

Then add these two entries to the existing `## Common Mistakes` list (append near the other tile-provider-related entry, `"Trusting a "free" tile provider without probing it first"`):

```markdown
- **Mixing up `{z}/{x}/{y}` vs `{z}/{y}/{x}` in a tile URL template** — the two Esri layers (`esri_street`, `esri_satellite`) use `{z}/{y}/{x}`, but CyclOSM (`cyclosm`) uses the more common `{z}/{x}/{y}` order. Getting this backwards doesn't error — it silently loads the wrong tiles (or a mismatched region). Every `tile_providers/providers/*.py` module documents its own order in a comment; when adding a fifth provider, verify its documented tile scheme rather than assuming the Esri order.
- **Trusting `ign_es_mtn`'s WMTS KVP query-string parameters from research notes alone** — `tile-providers-research.md`'s parameter names/values were a single manual check, not the burst-request-plus-real-browser verification this project's own Common Mistakes entry above requires before trusting a provider in production. `TileProviderService`'s live probe (one tile fetch per coverage point) catches an outright-broken URL, but a subtly wrong `TileMatrix`/`TileRow`/`TileCol` mapping that still returns a plausible 200 image response for the wrong tile would not be caught by the probe alone — pan/zoom a real rendered map over Spain before trusting this layer, the same way the Wikimedia cache-masked block was only caught by a human looking at the map, not by a status-code check.
```

- [ ] **Step 10: Commit**

```bash
cd skills/osm-day-route-show
git add scripts/render_map.py tests/test_render_map.py SKILL.md
git commit -m "Wire tile_providers into render_map.py: CLI flags, layer switcher, docs"
```

---

## Final verification

- [ ] Run the entire suite one more time from `skills/osm-day-route-show/`: `python3 -m pytest tests/ -v` — expect every test passing, none skipped.
- [ ] Render a real archive (any existing `routes/<slug>-<date>/` directory with `route.geojson`) with no flags: `python3 scripts/render_map.py <route_dir> /tmp/tile-check.html --no-wikipedia` and open `/tmp/tile-check.html` in a browser — confirm the map loads with the Esri street layer active and, if run somewhere with real network access, a layer switcher appears in the top-right if `cyclosm`/`ign_es_mtn` resolved as available for that route's location.
- [ ] Re-run the same render a second time and confirm `<route_dir>/tile_coverage.json` was created and the second run's log/timing shows no new network probes for providers already cached (manual spot-check, not an automated test).
