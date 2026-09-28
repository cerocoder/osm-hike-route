---
name: osm-day-route-show
description: Use when a route from osm-day-route-planning's archive (a routes/<slug>-<date>/ folder with route.geojson) needs to be shown on an interactive map, or the user asks to visualize/view/see a planned day route in a browser.
---

# OSM Day Route Show

## Overview

Renders a `route.geojson` (+ optional `notes.md`) from
`osm-day-route-planning`'s archive into a self-contained interactive
Leaflet/OpenStreetMap page — a route line with direction-of-travel
arrows, all point features as markers (with name/type/confidence-tier
popups, plus every place-info plugin's findings when any exist — see
**Place Info** below), a sidebar summarizing route stats (mode, distance,
elevation, duration) plus access-point and interest-layer info pulled
from `notes.md`, and an "Export & open elsewhere" section: a GPX
download (track + all waypoints, with elevation when the archive has it,
for Wikiloc/Garmin import) and links to open the same area in Google
Maps and OpenStreetMap.

**Languages:** the page's own chrome text (sidebar headings, export
labels, route mode labels) is localized to the language the
person is writing in, falling back to English for any language not in
the small built-in translation table — see **Languages & Localization**.
Point names are shown exactly as given in `route.geojson`, never
translated. Free-text sections pulled from `notes.md` (Access,
Interest-layer confidence) are shown as written — the page localizes its
own chrome, not `osm-day-route-planning`'s prose.

**REQUIRED SUB-SKILL:** builds on the archive format from
`osm-day-route-planning` — run that skill first if no route exists yet.

Every script under `scripts/` (`render_map.py` and everything in
`place_info/`) is **stdlib-only** — `urllib.request`/`json`/`argparse`/
`dataclasses`, no `requests`, no third-party HTTP client (Global
Constraint, same zero-external-runtime-dependency rule as
`osm-day-route-planning`).

## When to Use

- User asks to see/show/visualize a route that was just planned or is
  already saved in `routes/`
- Route data exists (`route.geojson`) but hasn't been rendered yet

**Not for:** planning the route itself (that's osm-day-route-planning),
live GPS tracking during a hike/ride (not implemented — see Future
Extension).

## How to Use

1. Determine `type`: `local` or `claude`. If the caller/user hasn't said
   which, ask — don't default silently.
2. Determine two language codes (ISO 639-1) to pass to the renderer:
   - `--user-lang`: the language the person is writing to you in, in
     *this* conversation. Don't ask for this explicitly — infer it from
     the conversation the way you would for any other reply.
   - `--local-lang`: the route location's own local/official language
     (e.g. `ru` for a park in Sverdlovsk Oblast, `es` for one in Spain).
     Infer this from the location the same way you already know its
     country to plan the route in the first place. If genuinely
     uncertain, omit it — the script still works with just `--user-lang`
     (falling back straight to English as the second language).
3. Generate the HTML:
   ```bash
   python3 scripts/render_map.py <route_dir> [output_path] \
       --user-lang <code> --local-lang <code>
   ```
   Defaults to writing `<route_dir>/map.html`. Reads `route.geojson`
   (required) and `notes.md` (optional — only the Access and
   Interest-layer-confidence sections are extracted; heading matching
   tries a small set of aliases in several languages case-insensitively,
   with trailing text after the heading tolerated, e.g. "## Как добраться
   (Екатеринбург → Бажуково)" still matches — see `SECTION_ALIASES` in
   `render_map.py`). Those sections are converted from markdown to real
   HTML (`markdown_to_html` — `- ` and `1. ` list items (with hard-wrapped
   continuation lines rejoined into one item first), `**bold**`,
   `` `code` ``, and `[text](url)` links become an actual `<a href>`, not
   literal bracket/paren text) — the link regex tolerates one level of
   parens inside the URL itself (e.g. a Wikipedia article title).
   This step also queries every place-info plugin for every point (network
   calls — see **Place Info**); pass `--no-wikipedia` to skip it (offline
   use, or a faster re-render while iterating on something else). Pass
   `--wiki-timeout <seconds>` to change the per-request timeout shared by
   all four plugins (default 5s).
4. **`type=local`**: report BOTH the absolute filesystem path (what the
   script prints, resolved) AND a clickable `file://` link built from it
   — the script prints this second line itself
   (`abs_path.as_uri()`, which percent-encodes spaces/non-ASCII
   correctly, unlike hand-building `f"file://{path}"`). Present it as a
   markdown link, e.g. `[map.html](file:///home/user/.../map.html)`, so
   it's clickable wherever the response renders. Do not open it
   yourself — the user opens it in their own browser.
5. **`type=claude`**: publish the same generated HTML as a Claude
   Artifact. Load the `artifact-design` skill first (required before any
   Artifact publish) and follow its page contract (title, icon,
   description) on top of the generated file.

## Direction-of-Travel Arrows

Implemented natively in the page's inline script (`addDirectionArrows` in
`render_map.py`'s generated HTML) — no Leaflet plugin. A small rotated
`▲` divIcon is placed every `max(150m, route_length/25)` along the route
LineString, oriented via a bearing calculation between the surrounding
coordinates. Deliberately not a plugin dependency: three different
"free" tile CDNs turned out to be blocked or key-gated this session
(see Common Mistakes) — a small amount of inline JS here is more
reliable than trusting an unverified third-party script for something
this simple. Verified visually (arrows point the correct way in a real
browser) rather than just by reading the bearing math.

## Export & External Links

The sidebar's "Export & open elsewhere" section (`build_gpx` and
`bbox_center_zoom` in `scripts/render_map.py`):

- **GPX download** — a `data:` URI (no separate file to keep in sync),
  one `<trk>` from the route LineString plus one `<wpt>` per Point
  feature, `creator="osm-day-route-show"`. Coordinates may be `[lon, lat]`
  (older archives) or `[lon, lat, ele]` (current schema, spec §3.11) —
  `build_gpx` tolerates both, emitting a `<ele>` element only when a third
  coordinate is present. GPX 1.1 is what both Wikiloc and Garmin devices/
  BaseCamp/Connect import natively (checked against Wikiloc's own upload
  docs).
- **Google Maps / OpenStreetMap links** — centered on the route's
  bounding box with a zoom level estimated from its extent (`bbox_center_zoom`).
  This is an approximation for landing in roughly the right place, not a
  precise viewport match — don't treat the zoom number as exact.

## Languages & Localization

Two independent language concerns, handled differently — see `UI_STRINGS`,
`SECTION_ALIASES`, and the `place_info` plugins in `render_map.py` /
`scripts/place_info/`:

- **Page chrome** (`--user-lang`): sidebar headings and export-section
  link text are looked up in a small built-in
  table (`UI_STRINGS`) covering `en`/`ru`/`es`/`fr`/`de`/`pt`/`it`. Point
  popups' place-info entries are labeled with their raw plugin/provider id
  (`"wikipedia"`, `"wikidata"`, `"wikimedia_commons"`, `"opentripmap"`) —
  not localized — since a point can show multiple sources at once and
  per-source localized labels aren't implemented for this round. Any
  other language, or any individual key missing for a listed one, falls
  back to English — never left blank. `<html lang="...">` is set to
  `--user-lang` regardless of whether a translation exists for it. Route
  mode labels (`route_stats_html`'s "walking"/"на велосипеде" etc.) follow
  the same fallback-to-English rule, but only for `en`/`ru` — see the
  known limitation below.
  - **Known limitation — the route-stats block is not fully localized**:
    unlike `UI_STRINGS`' full `en`/`ru`/`es`/`fr`/`de`/`pt`/`it` coverage,
    `_MODE_LABELS` (the mode name itself, "walking"/"пешком") only has
    `en` and `ru` entries — any other `--user-lang` falls back to the
    *English* mode label ("walking"/"cycling"), not a translation (a raw
    enum value like `"walk"` only surfaces for a mode this table doesn't
    know at all). Worse, the stats block's own `<h3>Route</h3>` heading
    and several of `route_stats_html`'s units/phrases are hardcoded
    English regardless of `--user-lang`: `"Route"`, `"km"`, `"h"`,
    `"curated routes nearby"`, and `"Not included (over budget)"` — unlike
    the sidebar's other headings (Getting there, Points of interest,
    Export & open elsewhere), which do go through `UI_STRINGS`. A user
    writing in, say, French or Portuguese sees a stats block that mixes
    their language (most sidebar headings) with English (the stats
    block's own heading, units, and phrases). This is a known gap, not
    something to "fix" as part of routine maintenance — flagged here so
    it isn't mistaken for an oversight.
- **notes.md section headings**: matched against `SECTION_ALIASES`, a list
  of known headings across several languages *for each concept*
  (`access`, `confidence`) — every alias is tried regardless of
  `--user-lang`/`--local-lang`, so English-heading archives (the older
  convention) keep rendering. Add a new language's aliases there, not by
  guessing a single expected heading string.
- **notes.md section body text** is shown exactly as written — it is
  `osm-day-route-planning`'s prose, in whatever language that skill wrote
  it in, and this skill does not translate it.
- **Point/route names**: never translated for display, in any language.
  This is a hard rule, not a default — a point's `name` is the local
  geographic name as given in `route.geojson`, shown as-is even when
  `--user-lang` differs. The one sanctioned exception is *searching* a
  specific-language Wikipedia edition, via the optional `search_names`
  property (see the schema table) and the `names: {lang: name}` dict each
  `place_info` plugin's `fetch()` receives (built from `search_names` plus
  the point's own `name`, in `annotate_place_info`) — neither ever changes
  what's displayed, only what's queried.

## Place Info

Each Point feature (interest point **or** access point — the same
mechanism runs for both) can pick up enrichment from **four independent
plugins**, all queried every time and every non-empty result shown, not
just a single "best" one — a real change from the old Wikipedia-only
behavior. The plugins live in `scripts/place_info/providers/` behind a
shared `PlaceInfoProvider`/`PlaceInfoResult` interface
(`place_info/providers/base.py`), aggregated by `PlaceInfoService`
(`place_info/__init__.py`), and are called from `annotate_place_info` in
`render_map.py` before the page is built:

1. **`wikipedia`** (`providers/wikipedia.py`) — a verified Wikipedia link
   in the best available language. **A wrong link is worse than no
   link** — two real false positives were caught and fixed during
   development (a disambiguation page matching a generic point name
   exactly; an unrelated same-named place 48 km away matching by name
   alone), so nothing here trusts a name match by itself. Resolution
   order, first success wins:
   1. **`wikidata` property** (a QID copied from OSM) → Wikidata's
      sitelinks → the first of `[user_lang, local_lang, en]` that has
      one. Trusted without further verification — it's a curated
      cross-reference, not a guess. This is currently the only curated
      (tag-based) path the plugin actually reaches — see the Common
      Mistakes note about the `wikipedia` tag below.
   2. **Coordinate + name search**, when no `wikidata` QID is present:
      search the local-language Wikipedia (CirrusSearch `nearcoord:`,
      then plain `geosearch` as a fallback) using the point's name, then
      **require both** a fuzzy title match against the query name and the
      candidate article's own `prop=coordinates` landing within 5 km of
      the point, and reject disambiguation pages. If nothing verifies in
      the local language, the same check is tried once more directly
      against English Wikipedia before giving up. A `search_names`
      override for the *primary* search language (`local_lang` or
      `user_lang`) is not currently honored — see Common Mistakes.
2. **`wikidata`** (`providers/wikidata.py`) — a short description in
   `user_lang` (falling back to English) for the point's own `wikidata`
   QID when present, or a SPARQL `wikibase:around` nearby-entity search
   (`wikibase:radius` in km — 0.3, i.e. 300m) when it isn't.
3. **`wikimedia_commons`** (`providers/wikimedia_commons.py`) — a nearby
   (500m) Commons file-namespace geosearch for a representative photo;
   image only, no summary text, no auth needed.
4. **`opentripmap`** (`providers/opentripmap.py`) — the richest
   single-call payload of the four (aggregates OSM+Wikidata+Wikipedia
   data server-side), gated by an API key — see **Configuration**.

**Shared cache**: every plugin's results, for every point (interest or
access), are written into **one** shared `<route_dir>/place_info.json`
file — not a per-plugin cache and not the old `wiki_links.json` name
(retired). Keyed by (`provider_id`, `osm_id`/`wikidata`/`name`, rounded
coordinates) — a repeat render does no network calls for entries already
cached. Written incrementally, after each new result, not only at the
end of the run — a multi-point run against a slow/rate-limited API can
run long enough to be killed by the caller's own timeout, and an
end-of-function-only write would lose every resolution from that run,
not just the unfinished one. `--no-wikipedia` skips place-info enrichment
entirely — `annotate_place_info` is never called, so no plugin runs, the
cache file is never even read, and no point gets a `_placeInfo` list —
useful for a fully offline render or when you don't want any enrichment
at all. It is **not** the way to "reuse an existing cache": running
*without* the flag already does that automatically (a cached entry means
zero network calls but `_placeInfo` still gets populated from
`place_info.json`).

**Fault isolation**: `PlaceInfoService.fetch_all` wraps each plugin's
`fetch()` call in its own `try/except` — if exactly one plugin raises an
unexpected exception, the other three plugins' results still reach the
point's popup and the render still completes; a bug in one plugin never
takes down the others.

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

## Configuration

The `opentripmap` plugin is optional and richer than the other three, but
needs a free API key. Register for a free key at OpenTripMap's own site
(opentripmap.io). Set it once via the `OSM_DAY_ROUTE_OPENTRIPMAP_KEY`
environment variable, or pass it straight through
`annotate_place_info(..., opentripmap_api_key=...)` when calling the
renderer as a library rather than via the CLI. **Its absence is not an
error**: `OpenTripMapProvider.fetch` returns `None` immediately when no
key is configured (and also degrades to `None`, never an exception, on an
HTTP 401/403 from a rejected key) — the other three plugins keep running
and the render completes normally either way. `annotate_place_info` only
constructs `OpenTripMapProvider` at all when a key is present — without
one, it's never queried and no `opentripmap|...` entry is ever written to
`place_info.json`, so configuring a key later and re-rendering queries it
fresh rather than staying poisoned by a stale cached "no result".
**The free-tier daily rate limit was not confirmed during development** —
verify it yourself before relying on this plugin in production use, per
the design spec's own caveat.

## Expected GeoJSON Property Schema

Point features render richer popups when they carry:

| Property | Used for |
|---|---|
| `name` | Popup title. **Must be the bare local name, untranslated** — no added English word, no parenthetical extras. Put anything else in `note`. |
| `type` | Popup subtitle (e.g. `waypoint`, `interest`, `access`) |
| `note` | Extra descriptive detail shown under the type in the popup — this is where "(рядом брод)"-style asides belong, not in `name` |
| `tier` | Appended to the title (e.g. `(web-sourced)`) — the same confidence vocabulary as osm-day-route-planning |
| `role` (on `type: "access"` points only) | `"start"` / `"end"` — colors the marker green/blue. With one access point it's always green; with two and no `role`, color is inferred from which end of the route LineString each point sits closest to |
| `opening_hours` (access points) | Shown verbatim in the popup, when present, via `point_popup_html` |
| `access_notes` (access points) | Shown verbatim in the popup, when present, via `point_popup_html` — right below `opening_hours` |
| `source` | Shown in italics (citation for web-sourced claims) |
| `osm_id` | Stable identity for the place-info cache key (`"node/12345"` etc.) — without it, the cache keys off name+coordinates, which shifts if either is edited later |
| `wikidata` | A QID (`"Q3070795"`) copied from the source OSM element's own `wikidata` tag, when present — the curated, most reliable source for both the `wikipedia` and `wikidata` plugins; see **Place Info** |
| `wikipedia` | An OSM-style `"lang:Title"` string copied from the source element's own `wikipedia` tag, when present. **Not currently consulted** by the `wikipedia` plugin (see Common Mistakes) — kept on the schema for forward compatibility and because `osm-day-route-planning` still writes it when available. |
| `search_names` | `{lang: name}` — only needed when the point's given `name` isn't in the language you'd want to search a *specific* Wikipedia edition in (e.g. a Russian-language point name for a landmark whose home wiki is French). The display name is never affected; this is search-only. An override for the *primary* search language (`local_lang` or `user_lang`) is not currently honored — see Common Mistakes. Most points won't need this. |

The `LineString` (route) feature's own `properties` drive the sidebar's
route-stats block (`route_stats_html`) — all optional, all degrading
gracefully:

| Property | Used for |
|---|---|
| `mode` | `"walk"` or `"bike"` — a missing value **defaults to `"walk"`** rather than erroring, for backward compatibility with pre-this-round archives that predate the `mode` property entirely. The value is then looked up in `_MODE_LABELS` for display (`--user-lang`, falling back to English): `walk` → "walking" (en) / "пешком" (ru); `bike` → "cycling" (en) / "на велосипеде" (ru). |
| `style` | Shown in parentheses next to the mode label (e.g. a `bike`/`sport` route renders as "cycling (sport)") |
| `distance_km` | Total route distance, one decimal place |
| `elevation_gain_m` / `elevation_loss_m` | Shown together as `+NNNm / -NNNm`; a missing `elevation_loss_m` renders as `0` |
| `duration_estimate_hours` | Shown as `~N.N h` |
| `duration_warning` | Free-text warning shown in its own paragraph when present (e.g. exceeding a stated time budget) |
| `curated_routes_count` | Shown as "N curated routes nearby" when truthy |
| `skipped_interest_points` | A list of names shown as "Not included (over budget): ..." when non-empty |
| `is_loop` | Whether the route returns to its start point vs. running point A to point B (spec §3.11) — informational metadata written by osm-day-route-planning; not currently rendered in the stats block, but preserved on the feature and safe to read from `route.geojson` |

Missing properties degrade gracefully (marker still renders, just with
less detail; the route-stats block still renders, just mostly empty) —
this is a convention for `osm-day-route-planning` to follow when writing
`route.geojson`, not a hard requirement enforced here. The route
LineString feature's own `name` property (not the archive folder's slug)
is used as the page `<title>` and sidebar heading if present — keep it in
the local language, untranslated, same as point names.

## Mobile

The page is already responsive (viewport meta, sidebar reflows to the
bottom on narrow screens) — it opens correctly on a phone browser today.

**Future extension (not implemented):** live GPS position tracking
during the hike/ride via the Geolocation API. Out of scope until asked
for — would need its own design pass (permissions, battery, offline
tiles).

## Common Mistakes

- **Trusting a "free" tile provider without probing it first** — three were tried and rejected in order: `tile.openstreetmap.org` 403s standalone/app usage outright (osm.wiki/Blocked); CARTO's Voyager basemap (`basemaps.cartocdn.com`) now requires an API key (watermarked tiles); Wikimedia's `maps.wikimedia.org/osm-intl` returns "Map tiles are restricted to Wikimedia and affiliated sites only" on any cache-miss tile — CDN-cached tiles from earlier testing kept loading, which made it *look* fine in a quick visual check and only failed once the user panned/zoomed to un-cached tiles. `render_map.py` now uses Esri's public `World_Street_Map` REST tiles (`server.arcgisonline.com`, note the `{z}/{y}/{x}` path order, not `{z}/{x}/{y}`) — verified with direct `curl` across zoom 10–19 plus a 15-request burst, no key, no block, as of 2026-09-27.
- **Verifying a tile provider by loading the page once and eyeballing it** — not enough, per the Wikimedia case above: cached tiles mask a block. Verify with direct `curl` requests (compute XYZ tile coords, check HTTP status *and* actually read the response body — a 403 can come back with a 200-looking body or an image-shaped error page) across several zoom levels and a burst of requests, before trusting a provider in the shipped page.
- **Mixing up `{z}/{x}/{y}` vs `{z}/{y}/{x}` in a tile URL template** — the two Esri layers (`esri_street`, `esri_satellite`) use `{z}/{y}/{x}`, but CyclOSM (`cyclosm`) uses the more common `{z}/{x}/{y}` order. Getting this backwards doesn't error — it silently loads the wrong tiles (or a mismatched region). Every `tile_providers/providers/*.py` module documents its own order in a comment; when adding a fifth provider, verify its documented tile scheme rather than assuming the Esri order.
- **Trusting `ign_es_mtn`'s WMTS KVP query-string parameters from research notes alone** — `tile-providers-research.md`'s parameter names/values were a single manual check, not the burst-request-plus-real-browser verification this project's own Common Mistakes entry above requires before trusting a provider in production. `TileProviderService`'s live probe (one tile fetch per coverage point) catches an outright-broken URL, but a subtly wrong `TileMatrix`/`TileRow`/`TileCol` mapping that still returns a plausible 200 image response for the wrong tile would not be caught by the probe alone — pan/zoom a real rendered map over Spain before trusting this layer, the same way the Wikimedia cache-masked block was only caught by a human looking at the map, not by a status-code check.
- **Auto-opening the page yourself for `type=local`** — the user opens it; don't invoke a browser automation tool as part of normal operation.
- **Publishing to `type=claude` without loading `artifact-design` first** — required by the Artifact tool's own contract.
- **Assuming `notes.md` sections use exact headings** — `extract_md_section` matches against `SECTION_ALIASES`, a list of known headings per concept across several languages, case-insensitively, with trailing text after the heading tolerated. If `osm-day-route-planning`'s template adds a genuinely new heading (not just a new language's translation of an existing one), add it to `SECTION_ALIASES` rather than hardcoding one expected string.
- **Regenerating from scratch instead of re-running the script** — `render_map.py`'s HTML output is idempotent for the same inputs, but note that place-info resolution reads/writes `<route_dir>/place_info.json` as it runs, so a repeat render for the same point does no network calls unless that cache is cleared. **The cache key does not include the language codes** (`cache_key(provider_id, identity, lat, lon)` in `place_info/cache.py`) — changing `--user-lang`/`--local-lang` alone does *not* invalidate a cached entry, so a language change that should re-resolve a link in the new language requires clearing `place_info.json` (or the specific keys) by hand.
- **Rendering notes.md text raw** — dumping the extracted section straight into `<pre>` shows literal `[text](url)`/`**bold**` syntax instead of a clickable link/bold text; always go through `markdown_to_html`.
- **Converting markdown before HTML-escaping the source text** — do it in that order (`markdown_to_html` escapes first, then layers on real tags): escaping after conversion would mangle the `<a>`/`<b>`/`<code>` tags you just created.
- **Only handling `- ` bullets in notes.md** — a `1. `/`2. `/`3. ` numbered list collapses into one giant run-on `<li>` if the parser only recognizes dash bullets; `markdown_to_html` matches `_LIST_MARKER` (`-\s+` or `\d+\.\s+`) for exactly this reason, reproduced with this skill's own generated notes.md.
- **Trusting a Wikipedia name match without verifying coordinates** — reproduced twice in testing: a disambiguation page ("Пирамида") matched a point named exactly "Пирамида" because the title equality check alone doesn't know it's a disambig page; a same-named rock 48 km away ("Дыроватый Камень") matched via `nearcoord:`-filtered search, which turned out to boost proximity rather than strictly enforce it. Always confirm via `prop=coordinates` (within ~5 km) and reject disambiguation pages (`pageprops.disambiguation`) before accepting a search-based match — see `_verified_by_coords` in `providers/wikipedia.py`. A `wikidata`-tag-sourced link skips this check because it's OSM-curated, not name-guessed.
- **Caching a rate-limited/failed Wikipedia lookup as "no article exists"** — a plain `except Exception: return []` around the API call turns a 429 or a non-JSON error body into an indistinguishable empty result, and caching that permanently loses the point's real link. `resolve_wikipedia` distinguishes this case by raising `WikiLookupError` rather than returning `(None, None)` for a genuine failure — but note that `WikipediaProvider.fetch` currently catches `WikiLookupError` and returns `None` just like a confirmed "no article", and `PlaceInfoService.fetch_all` then caches that `None` in `place_info.json` the same as any other empty result. In practice this means a rate-limited/offline run **does** get permanently cached as "no result" today, the same failure mode the original design set out to avoid — the fix, if revisited, is for `PlaceInfoService` to only cache a provider's `None` when it's a confirmed empty result, not an error; until then, delete the affected `place_info.json` entries (or the whole file) after an offline/rate-limited run to force a retry.
- **Hand-building a `file://` URL from a path** — `f"file://{path}"` doesn't percent-encode spaces or non-ASCII (e.g. Cyrillic archive slugs); use `Path(...).resolve().as_uri()`.
- **Writing the place-info cache only once at the end of a run** — a multi-point run against a slow/rate-limited API can run long enough to be killed by the caller's own timeout (reproduced: a 170s wrapper killed a run doing the merged search+geosearch calls), and an end-of-function-only write loses every resolution from that run, not just the unfinished one. `place_info.cache.save_entry` writes `place_info.json` after each new resolution instead.
- **Gating the token-subset name-match by character-length ratio, same as the plain substring check** — a real disambiguated title can be much longer than the query purely because its qualifier is a multi-word region name ("Свердловская область"), which fails a length-ratio gate despite being a correct match with few *extra tokens*. Gate the token-subset path by extra-token count instead (`max_extra_tokens`), not character length — reproduced with "Большой Провал" failing to match "Большой карстовый провал (Свердловская область)" under a length-ratio-only gate.
- **A river/lake/long linear feature's own Wikipedia coordinate is usually its mouth, source, or some other single reference point** — `_verified_by_coords`'s 5 km radius will legitimately reject the correct article for a point sampled somewhere along its middle course. Known limitation, not a bug to chase: a `wikidata` tag on the source OSM way (bypasses the coordinate check entirely) is the real fix, not a wider radius.
- **An OSM `wikipedia=lang:Title` tag on a point is NOT currently consulted by the Wikipedia plugin** — only a `wikidata` QID is. `WikipediaProvider.fetch` builds a synthetic feature containing just `name`/`wikidata`/`search_names`; the `wikipedia` tag never reaches it, even though the underlying `resolve_wikipedia` function still contains logic for it. A known limitation, not something to rely on — if a point only has a `wikipedia` tag and no `wikidata` QID, it falls through to the coordinate+name search path instead.
- **`search_names` overrides for the primary search language (`local_lang` or `user_lang`) are silently ignored** — `annotate_place_info` unconditionally overwrites that language's entry with the point's plain display name (`names = {**names, (local_lang or user_lang): props["name"]}`) before any plugin sees it, so an override supplied for that specific language never reaches `WikipediaProvider.fetch`. Overrides for *other* languages (e.g. an English-only override when the primary search language is Russian) do still work. A known gap, not a bug to work around by expecting the primary-language override to take effect.
- **Unpacking `route.geojson` coordinates as a fixed 2-tuple** — the current schema (spec §3.11) allows a 3D `[lon, lat, ele]` array; `for lon, lat in coords` raises `ValueError: too many values to unpack` the first time a 3D archive is rendered. `build_gpx`, `bbox_center_zoom`, and the point-rendering code all destructure only the first two elements (`lon, lat = coord[0], coord[1]`) and read a possible third element separately, so both 2D and 3D archives render without exceptions.
- **Assuming a pre-this-round archive (2D coordinates, no `mode`/`style`/place-info-eligible properties) will crash the renderer** — it must not. `route_stats_html` treats every stat property as optional (missing `mode` renders as `"walk"`), `build_gpx` treats the third coordinate as optional, and a Point with no `wikidata`/`wikipedia`/`osm_id` still gets a cache key derived from its name and coordinates — verify this by hand against a hand-crafted minimal fixture before considering a render "done" for an old archive.
- **Letting one broken `place_info` plugin take down the others, or the whole render** — `PlaceInfoService.fetch_all` calls each plugin's `fetch()` inside its own `try/except Exception`, so one plugin's bug (or an `opentripmap` key rejected with HTTP 401/403) degrades to that plugin contributing nothing, not an exception that stops the render or hides the other three plugins' results.
- **Treating an unresolved Wikidata QID as a match** — a stub or malformed Wikidata item (no sitelinks, or no description in any language this run cares about) must degrade to "no result" inside `wikidata.py`/`wikipedia.py` themselves, not propagate a `KeyError`/`IndexError` up through `PlaceInfoService` and abort the whole point's enrichment.
- **Writing four separate cache files, one per plugin** — `place_info.json` is the one shared cache for all four plugins and for both interest points and access points; don't reintroduce the old per-source-file pattern (`wiki_links.json`) when adding a fifth plugin later.
- **Assuming `wikidata`'s/`opentripmap`'s coordinate-only "nearby" match is name-verified like the Wikipedia plugin's** — it is not. `WikidataProvider`, when a point has no `wikidata` QID, falls back to a SPARQL `wikibase:around` search within 0.3 km; `OpenTripMapProvider` *always* (it never receives or caches a QID/xid from a prior lookup) queries its `/radius` endpoint within 300m for whatever the API returns first. Neither checks that the result's name actually matches the point's own name — unlike `resolve_wikipedia`'s fuzzy-title-match-plus-coordinate-verification discipline. This can return a genuinely different nearby feature than the point itself (e.g. a village's own Wikidata entry instead of a spring located within it). `WikidataProvider`'s SPARQL query does order by distance (`ORDER BY ?dist`), so it deterministically picks the *closest* entity within the radius rather than an arbitrary one — a cheap, safe improvement, but still not name verification. `OpenTripMapProvider`'s `/radius` call requests no ordering at all (just `limit=1`), so its result is whatever the API lists first within 300m, not necessarily the closest either. Not a bug to fix reflexively; a known trade-off from the design, flagged here as a follow-up candidate rather than something to silently "improve" mid-task.
