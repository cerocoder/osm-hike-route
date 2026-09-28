# Tile provider plugins for osm-day-route-show

Date: 2026-09-28
Status: approved (design), pending implementation plan

## Context

`render_map.py` currently hardcodes one tile source — Esri's public
`World_Street_Map` REST tiles — chosen after three other "free" providers
turned out to be blocked or key-gated (see `SKILL.md`'s Common Mistakes).
Separate research (`tile-providers-research.md`, 2026-09-28, not yet wired
in) identified three more candidates worth offering: Esri `World_Imagery`
(satellite), CyclOSM (OSM-styled, actively maintained), and IGN España's
`MTN` layer (official Spanish topographic map — every route this skill has
built so far is in Spain).

This spec adds a **tile-provider plugin system**, mirroring the existing
`place_info` plugin architecture (`scripts/place_info/`): a shared
interface, independent plugin modules, a service that aggregates them with
per-plugin fault isolation. The map picks a base layer automatically and
exposes any other provider that covers the route's location as an
in-browser Leaflet layer switcher — no chat-based prompt, no extra
agent/user round-trip before rendering.

## Goals

- Add four tile-provider plugins: `esri_street` (existing), `esri_satellite`,
  `cyclosm`, `ign_es_mtn`.
- Each non-Esri plugin determines coverage for the current route via a
  live network probe (single tile fetch), not a static bounding box.
- Esri-hosted plugins (`esri_street`, `esri_satellite`) are always treated
  as available — no probe, hardcoded `True` — since both are Esri's
  worldwide REST services, the same trusted host already in production use.
- The rendered page always has one active base layer (backward-compatible
  default: Esri street) and, when more than one provider covers the
  route, an in-page Leaflet layer control to switch between them.
- Probe results are cached per route directory so repeat renders of the
  same route don't re-probe over the network.
- A broken/unreachable plugin degrades to "not offered", never breaks the
  render.

## Non-goals

- No chat-based "ask the user which plugin" step before rendering — the
  browser-side layer switcher *is* the picker.
- No coverage check against the full route geometry or every interest
  point by default — only the point group used for probing (see
  **Coverage point selection** below).
- No rigorous multi-zoom hash-comparison verification (the method
  `tile-providers-research.md` used) as part of the runtime probe — that
  remains a one-time manual research step before a new provider is added
  to the shortlist, documented in that file. The runtime probe is a
  lightweight single-tile liveness/coverage check, not a replacement for
  that research.

## Plugin interface

New package `scripts/tile_providers/`, structured like
`scripts/place_info/`:

```
tile_providers/
  __init__.py          # TileProviderService
  cache.py              # tile_coverage.json read/write helpers
  probe.py               # probe_tile() + lat/lon -> tile x/y/z math
  providers/
    base.py              # TileProviderPlugin ABC
    esri_street.py
    esri_satellite.py
    cyclosm.py
    ign_es_mtn.py
```

`providers/base.py`:

```python
class TileProviderPlugin(ABC):
    provider_id: str        # "esri_street", "esri_satellite", "cyclosm", "ign_es_mtn"
    display_name: str       # shown in the Leaflet layer control
    tile_url_template: str  # Leaflet-ready {z}/{x}/{y} or {z}/{y}/{x} template
    attribution: str        # exact attribution string required by the provider's terms
    max_zoom: int
    max_native_zoom: int | None
    always_available: bool  # True only for esri_street / esri_satellite

    def covers(self, points: list[tuple[float, float]], timeout: float) -> bool:
        """True immediately (no network call) when always_available.
        Otherwise probes one tile per point at a fixed zoom and requires
        every point to succeed. Never raises — network/parsing failures
        resolve to False."""
```

### The four plugins

| `provider_id` | Tile source | `always_available` | `max_zoom` / `max_native_zoom` | Attribution |
|---|---|---|---|---|
| `esri_street` | `server.arcgisonline.com/.../World_Street_Map/MapServer/tile/{z}/{y}/{x}` (unchanged from current production) | **True** | 19 / 19 | existing string, unchanged |
| `esri_satellite` | `server.arcgisonline.com/.../World_Imagery/MapServer/tile/{z}/{y}/{x}` | **True** | 20 / 20 | Esri World_Imagery standard attribution (exact string confirmed during implementation against Esri's own terms page) |
| `cyclosm` | `tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png` — **note the `{z}/{x}/{y}` order, different from the two Esri templates** | False — live probe | 19 / 19 | `Map data © OpenStreetMap contributors, Tiles style © CyclOSM` (+ CyclOSM project link) |
| `ign_es_mtn` | IGN España WMTS, `layer=MTN`, `TileMatrixSet=GoogleMapsCompatible` (exact KVP query-string parameters confirmed during implementation against `tile-providers-research.md`'s working example and re-verified by curl, same bar as the existing Esri layer) | False — live probe | 19 / 19 | `CC-BY 4.0 ign.es` |

`esri_satellite` is marked `always_available` for the same reason
`esri_street` already is in this codebase: both are Esri's own worldwide
REST tile services on the same already-trusted host — probing them adds
a network round-trip for a coverage answer that's always "yes" in
practice.

## Coverage probing

`probe.py`:

- `latlon_to_tile(lat, lon, zoom) -> (x, y)` — standard slippy-map tile
  math, extracted from the manual research into reusable code.
- `probe_tile(url, timeout) -> bool` — one `urllib.request` GET with a
  descriptive `User-Agent` (matching the project's existing convention in
  `place_info` providers). Success = HTTP 200, `Content-Type` starting
  with `image/`, and a non-trivial response body (guards against a
  placeholder/error tile that still returns 200 with a tiny image body —
  the same class of failure documented for Wikimedia's block page in
  `SKILL.md`'s Common Mistakes). Any exception (timeout, DNS failure,
  HTTP error status) resolves to `False` — never propagates.
- Fixed probe zoom: `TILE_PROBE_ZOOM = 15` (typical zoom this skill's
  sidebar map actually displays at).

### Coverage point selection

The points passed to `covers()` are chosen with this fallback chain,
computed once per render before any plugin is probed:

1. All `Point` features with `properties.type == "access"`.
2. If none exist, all `Point` features with `properties.type == "interest"`
   (or any other Point feature type, if `interest`-only proves too
   narrow during implementation — the intent is "any real waypoint",
   access points preferred).
3. If there are no Point features at all, skip probing entirely — only
   `always_available` plugins (the two Esri layers) are offered. This is
   a degrade-gracefully edge case, not an error.

`TileProviderService.available_providers(points)` requires **every**
point in the selected group to succeed for a plugin to count as covering
— a provider that only has data for one of two widely separated access
points doesn't get offered.

### Cache

`<route_dir>/tile_coverage.json`, a new file (not merged into
`place_info.json` — different semantics, different key shape).
`tile_providers/cache.py` mirrors `place_info/cache.py`'s
load/save-incrementally pattern:

- Key: `f"{provider_id}|{sorted_rounded_coords}"` — the full set of probe
  points (rounded to the same precision `place_info` already uses),
  sorted so point order doesn't create spurious cache misses.
- Value: `true` / `false`.
- Written after each plugin's probe completes (not only at the end of the
  run) — same rationale as `place_info.cache.save_entry`: a slow/rate-
  limited run that gets killed by an outer timeout shouldn't lose probes
  it already completed.
- `always_available` plugins never read or write this cache — there's
  nothing to cache.

## render_map.py integration

**New CLI flags:**

- `--tile-provider <id>` (optional) — forces the active/base layer to
  this provider, bypassing the automatic default. Invalid/unavailable id
  is an error (fails fast, doesn't silently fall back).
- `--tile-timeout <seconds>` (default `5.0`) — shared probe timeout,
  same style as the existing `--wiki-timeout`.

**Default active layer** (no `--tile-provider` given): the first
available provider in priority order `[esri_street, ign_es_mtn, cyclosm,
esri_satellite]` — `esri_street` stays the default for backward
compatibility with the current production behavior; the others only
become default when explicitly selected via the flag.

**HTML generation:** replace the single hardcoded `L.tileLayer(...)` call
with a `baseLayers` object built from
`TileProviderService.available_providers(points)` — one
`L.tileLayer(url_template, {attribution, maxZoom, maxNativeZoom})` per
available plugin. The active layer is added to the map directly; if more
than one provider is available, `L.control.layers(baseLayers).addTo(map)`
is added so the viewer can switch base layers in the browser. With only
one available provider (the common case away from Spain, or if both
non-Esri probes fail), no layer control is added — no empty/single-item
switcher clutter.

**Fault isolation:** `TileProviderService.available_providers` wraps each
plugin's probe in its own `try/except Exception` — one broken plugin is
simply excluded from the offered list, the same discipline
`PlaceInfoService.fetch_all` already applies to `place_info` plugins.

## Documentation

New `## Tile Providers` section in `SKILL.md`, covering:

- The four plugins, their attribution/license requirements, and the
  `always_available` distinction.
- The coverage probe + cache (including the access→interest→none
  fallback chain and the per-render vs. cached distinction).
- The new `--tile-provider` / `--tile-timeout` CLI flags.
- Common Mistakes additions: the `{z}/{x}/{y}` vs `{z}/{y}/{x}` template
  order difference between CyclOSM and the Esri layers (a live instance of
  a mistake class this file already warns about elsewhere); IGN's WMTS
  KVP addressing needing verification against a real rendered map, not
  just curl, before being trusted (per the project's own established
  verification bar in `tile-providers-research.md` and the existing
  Common Mistakes entry about cache-masked blocks).

## Testing

- `probe.py`: unit tests for `latlon_to_tile` (known reference values) and
  `probe_tile` (mocked `urllib` — 200/image success, 200/tiny-body
  rejection, non-200, timeout/exception → all resolve correctly).
- `cache.py`: round-trip read/write, incremental-write-doesn't-lose-prior-
  entries behavior (same shape as the existing `place_info` cache tests,
  if any exist to mirror).
- `TileProviderService.available_providers`: fault isolation (one plugin
  raising doesn't affect others), `always_available` short-circuit (no
  network call made), and the access→interest→none point-selection
  fallback.
- `render_map.py`: HTML generation produces the expected `baseLayers` /
  `L.control.layers` output for 1-provider vs. multi-provider cases.

## Open items for implementation time (not blocking this spec)

- Exact Esri `World_Imagery` attribution string and exact IGN `MTN` WMTS
  KVP parameter names/values — both need confirming against the
  providers' own current docs/terms during implementation, the same way
  the existing Esri street layer's attribution was sourced from Esri's
  own terms rather than guessed.
- Whether `TILE_PROBE_ZOOM = 15` is the right fixed probe zoom in
  practice, or needs to vary with the route's own display zoom —
  start with the fixed value and revisit only if it produces wrong
  coverage answers in testing.
