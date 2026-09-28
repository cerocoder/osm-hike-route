# Tile provider research (2026-09-28)

Research only — nothing in this file has been wired into `render_map.py` yet.
Current production tile layer is still Esri `World_Street_Map` (see
`render_map.py`'s `L.tileLayer(...)` call and its own Common Mistakes note
on why three other "free" providers were rejected before it:
`tile.openstreetmap.org` 403s standalone use, CARTO Voyager now needs a key,
Wikimedia `osm-intl` blocks on any cache-miss tile).

## Method

A curl-only, no-key HTTP status check is not enough — the project has
already been burned once by a provider that returns HTTP 200 with a
*plausible-looking but wrong* body (Wikimedia's block page cached at some
zooms, not others). For this round, every candidate was probed by:

1. Fetching real tiles (not `/status` endpoints) at the exact same lat/lon
   (40.2500, -3.5600 — inside the area this skill's existing routes cover)
   across several zoom levels, with a descriptive non-browser `User-Agent`.
2. Hashing each response body and comparing hashes **across zoom levels**.
   A provider that has no real data past some zoom typically re-serves the
   deepest tile it does have (byte-identical, or the same image scaled) —
   this shows up as a repeated hash, not an HTTP error, so a status-code-only
   check would have missed it entirely.
3. Cross-checking any provider whose story sounded stable against current
   news (OpenTopoMap's turned out not to be — see below).

This was a **single request per zoom**, not the "burst of requests" the
project's own established bar calls for before trusting a provider in
production (see `render_map.py` skill's Common Mistakes: a cache-miss vs.
cache-hit distinction needs more than one shot). Treat every "recommended"
row below as *needs the burst + real-browser check next*, not as cleared
for production.

## Satellite imagery

| Provider | Key | Real distinct max zoom (this test point) | License | Verdict |
|---|---|---|---|---|
| **Esri `World_Imagery`** (`server.arcgisonline.com/.../World_Imagery/MapServer/tile/{z}/{y}/{x}`) | none | **20+**, no repeats at any tested level | Esri public REST — same terms as the `World_Street_Map` layer already in use | Same already-trusted host, different layer. Genuinely unique high-res data through z20 here. Strongest candidate. |
| EOX Sentinel-2 cloudless (`tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg`) | none | technically unique bytes through z18, but native Sentinel-2 resolution is ~10m/px — past z14–15 it's just upsampled blur, not real detail | **CC BY-NC-SA 4.0** for current years (non-commercial only) | Independent of Esri, but the license has a non-commercial clause, and it's useless at the zoom levels a walking route actually needs (15+). |

## Topographic

| Provider | Key | Real distinct max zoom (this test point) | License | Verdict |
|---|---|---|---|---|
| **IGN España, layer `MTN`** (`ign.es/wmts/mapa-raster`, WMTS KVP, `TileMatrixSet=GoogleMapsCompatible`) | none | **19**, unique data at every level tested (15–19) | **CC-BY 4.0** (attribution string: "CC-BY 4.0 ign.es") | Official Spanish national topographic map (Mapa Topográfico Nacional), government infrastructure. Every route this skill has built so far is in Spain — direct fit. Real contour-based detail deep into the zoom range. Best topo candidate found. **Caveat found during the tile-provider-plugin final review (2026-09-28): outside Spain this endpoint still returns HTTP 200 with a plausible `image/jpeg` body, but it's a flat beige placeholder tile (a few hundred bytes to ~2KB, vs. ~19KB for a real Madrid-area tile) — a naive body-size or status-code probe alone falsely reports coverage worldwide. The shipped `IgnEsMtnProvider` now rejects any point outside a rough Spain bounding box before ever probing.** |
| Esri `World_Topo_Map` | none | ~18 here (z19 repeats z18's bytes; z20 falls back to a generic Esri "no data" tile — same hash as `World_Shaded_Relief`/`World_Terrain_Base` below, suggesting it's a shared ArcGIS Online fallback, not per-service) | Esri public REST | Same trusted host as current layer, but hits its resolution ceiling earlier than the satellite layer at this specific rural point. |
| Esri `World_Shaded_Relief` / `World_Terrain_Base` | none | **~11–13**, then byte-identical fallback tile at every deeper zoom tested (11 through 20) | Esri public REST | Not blocked, just genuinely low-resolution by design (documented Esri ceiling) — unusable at the zoom levels (15–18) a hiking route sidebar actually shows. |
| OpenTopoMap (`tile.opentopomap.org`) | none | still answers with unique tiles through z17 today | CC-BY-SA (OSM + SRTM) | ⚠️ **Do not adopt.** The upstream maintainer announced (GitHub issue [der-stefan/OpenTopoMap#382](https://github.com/der-stefan/OpenTopoMap/issues/382), opened 2025-11-19) that the raster tile service is moving into "survival mode": data is already frozen at January 2023, and tiles above z13 are expected to stop being served soon. This is exactly the "works today, breaks without warning" failure mode this project has already been burned by twice (CARTO, Wikimedia) — don't repeat it a third time on a provider that's telling us in advance. |
| CyclOSM (`a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png`) | none | unique data through z19, no repeats | Standard OSM attribution + "CyclOSM & OSM-FR" | Actively maintained by OpenStreetMap-France infrastructure, holds up well at depth — but it's a *cycling*-oriented style (routes/surfaces emphasis), not contour-line topographic. Worth keeping in mind as a more durable OSM-styled fallback than OpenTopoMap, but it isn't what "more topographic" was asking for. **Note: the bare host `tile-cyclosm.openstreetmap.fr` (no subdomain) does NOT resolve — only the load-balanced subdomains `a.`/`b.`/`c.tile-cyclosm.openstreetmap.fr` actually serve tiles. This research's own probing used the working `a.` subdomain; an earlier draft of the shipped plugin mistakenly hardcoded the bare host and was caught and fixed during the tile-provider-plugin final review (2026-09-28) — every CyclOSM probe was silently failing DNS before that fix.** |
| Thunderforest Outdoors/Landscape | **requires an API key** | not tested | paid tier, free quota | Ruled out at a glance by the key requirement — noted for completeness only. |

## Side finding: the currently-deployed layer already hits this same ceiling

`World_Street_Map` (the layer `render_map.py` uses today) was checked at the
same test point for comparison: z19 returns the byte-identical tile to z18
here — i.e., in this specific rural area, the map is already silently
re-requesting/re-serving the same tile at the currently-configured
`maxZoom: 19`. Not a bug (Leaflet just displays it scaled, nothing breaks),
but the config only sets `maxZoom`, not `maxNativeZoom`. Whenever a new
layer is actually wired in, set `maxNativeZoom` per layer to that layer's
real ceiling (from this table) so Leaflet upscales client-side instead of
re-requesting the same URL:

- `World_Imagery`: 20+
- `World_Topo_Map` / IGN `MTN`: ~18–19
- `World_Shaded_Relief` / `World_Terrain_Base`: ~13

## Next steps before actually adopting anything here

1. Burst-request each shortlisted candidate (Esri `World_Imagery`, IGN
   `MTN`) — several rapid requests across zooms/areas, not one — per this
   project's own established verification bar.
2. Load each into an actual browser and pan/zoom manually — the Wikimedia
   incident specifically was caught by a *human* noticing a visual block
   message that curl's status code did not surface.
3. Decide whether IGN's WMTS KVP URL scheme (query-string tile addressing,
   not the plain `{z}/{y}/{x}` path Esri uses) needs a small wrapper in
   `render_map.py`'s tile-layer setup, or whether Leaflet's `L.tileLayer`
   template string can just embed the query params directly (it can, but
   worth confirming zoom/x/y map into `TileMatrix`/`TileRow`/`TileCol`
   with no off-by-one — this research computed x/y from the standard
   slippy-map formula and it matched IGN's own advertised
   `GoogleMapsCompatible` matrix set, but wasn't cross-checked against a
   real rendered map).
4. If a layer switcher/picker is added (rather than swapping the one
   hardcoded layer), decide the UI for it — out of scope for this research.
</content>
