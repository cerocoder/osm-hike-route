# Public routes at the start of planning — design

Date: 2026-10-01. Scope: `osm-day-route-planning` (a new step, a new module, an optional archive property, `SKILL.md`), the progress catalogue (`progress.py`, both copies) and the show skill (display of the new property only). Research behind it: probes of real OSM data for four places (Pelayos, Moscow, Sysert, Garmisch-Partenkirchen), repository code untouched.

## Goal

Right after the user has been asked about the outing, find the public (waymarked) routes of OpenStreetMap that fit the user's criteria, show them as a readable list, and offer **"Свой маршрут"** (in the user's language) as the last option. A chosen public route becomes the route of the normal archive; the user may add own points to it. Today these routes are only counted (`curated_routes_count`, step 16).

## Decisions (from the user)

| Question | Decision |
|---|---|
| How many to show | Not "the first five": **all that match the user's criteria**, at most ten (the best by the order below), with a hint how to narrow when more match. |
| Criteria | Length, travel time (from the mode's pace and ascent rate — the same formula the planner uses for the duration), optionally a maximum ascent; loop or linear (already asked in step 4); mode and style (already asked). |
| Names in the list | Built from the key points, ascent and length (see "Line of the list"). |
| Order | Interests first, then practical start, then closeness to the requested range, then network level and completeness (see "Order"). |
| Long-distance routes | Not shown by default; a closing line says how many pass nearby. |
| Range from a single number | ±25 %. |
| Adopting a route | The user may add own points of interest to the chosen public route. |

## What OSM gives and what is computed (measured)

- **Tags, free:** `name` (almost always), `network` (lwn, rwn, nwn, iwn / lcn, rcn, ncn, icn), `ref`, `operator`, `website`, `osmc:symbol` and `colour` (how it is marked), `from`, `to`, `description`, `wikipedia`/`wikidata`. `distance` is rare for hiking (8 of 144 near Garmisch, 2 of 4 near Pelayos), commoner for cycling; `ascent`/`descent` very rare for hiking (2 of 144), about 40 % for cycling; `roundtrip` rare; `duration` rare.
- **Computed from the geometry** (`out geom`, 3–135 KB for a day route, 0.5–1.1 MB for a long-distance one): length (within about 10 % of the `distance` tag where both exist; each member way counted once), the ordered track, start and end, loop or linear (ends within 150 m of each other), distance from the user's place to the nearest point of the track.
- **Computed from enrichment:** ascent and descent (elevation service, one sample per 150 m: about 80 points for 12 km, about one request, cached), travel time (duration formula), key points (one OSM query for the area, assigned to routes by distance to the track), surface mix and difficulty (tags of the member ways), start access (the existing access-point step), closed-zone check (the existing restricted-polygon check on the track).
- **Not available from OSM:** photographs, GPX download links other than `website`, current closures and trail condition — web research after the choice (the existing `trail_conditions` mechanism of the day plan covers the date-specific part).
- **Caveats measured:** a query `around:15000` returns every relation with a vertex in the radius, so long-distance routes (Camino de Santiago, 938 km; GR 180, 207 km) appear next to the one real day route; Overpass answers vary from 1 to 20 s and sometimes time out, so everything is cached (`routes/.cache`, existing 24 h cache), batched and shown through the progress output; a list must never be the only way forward: **"Свой маршрут" is always offered**, also when the lookup failed.

## Architecture

### New module `scripts/public_routes.py` (stdlib only)
- `find_candidates(lat, lon, radius_m, mode, cache_dir=None, progress=None)` → candidate dicts from one `out tags center` query (`route=hiking|foot` for walk, `bicycle|mtb` for bike): `id`, `tags`, `network_level`. Dropped: `state` proposed/abandoned/disused, `access=no|private`, a relation seen twice (same `ref` + `name`, super- and sub-relations: the one with the most members is kept, the rest are counted as duplicates). Long-distance networks (`nwn`, `iwn`, `ncn`, `icn`) are separated into `long_nearby` and not loaded.
- `load_tracks(candidates, cache_dir, progress, batch=20)` → adds the geometry: `relation(id:…);out geom;` in batches of 20 (each batch is one progress tick); a failed batch is retried once and then those candidates are skipped with a note, never fatal. `build_track(members)` stitches member ways by identical end coordinates into chains, picks the longest chain as the track, records `gaps` (more than one chain), `length_m` (each way id once), `start`, `end`, `is_loop`.
- `length_km(candidate)`: tag `distance` when it parses as a number (kilometres), else the computed length; `length_source` is `tag` or `computed`.
- `Criteria` (`min_km`, `max_km`, `min_h`, `max_h`, `max_ascent_m`, `loop`: True/False/None, `interests`) and `criteria_from_number(value, kind)` (±25 %). `prefilter(candidate, criteria, pace)` drops by length, and by the lower bound of time (length at pace, no ascent). Only the survivors get elevations.
- `add_elevation(candidates, service, progress)` → `ascent_m`, `descent_m` from samples every 150 m along the track (the shared `ElevationService`, its cache, ticks per request); then `duration_h` from `duration.estimate_duration_hours` and the final filter (time range, maximum ascent).
- `find_key_points(candidates, cache_dir, progress)` → one OSM query over the union of the bounding boxes for named peaks (`ele` kept), viewpoints, historic objects, springs and lakes, waterfalls, huts; each point is assigned to the candidates whose track passes within 80 m (distance to the segment, not to the vertex) and ordered by position along the track. Unnamed objects are ignored.
- `rank(candidates, criteria, location, access_points)` → the order below; `describe(candidate, lang)` → the list line.
- `adopt(candidate, graph, node_coords, preferences, extra_points)` → the node path of the planner for the chosen route (see "Adopting").

### The list line (`describe`)
`<n>. <name or ref> — <A → B | loop> · via <1–2 key points> · <length> km · ↑<ascent> m · <time> h · <network level>`; with `~` before a computed length and a note `*` when the ascent or time is estimated. Rules: the name is the `name` tag (plus `ref` in brackets); if there is none, `from → to`, else the nearest named place to the start (OSM `place` nodes), else only the figures. Key points: peaks (with their `ele`) before viewpoints before historic objects before water before huts, at most two, in route order, names exactly as in OSM. Every word of the line (loop, via, km, m, h, the network levels, "own route", the sort sentence, "N long routes pass nearby") comes from a seven-language catalogue (`en ru es fr de pt it`, English fallback); the user's language, as everywhere. Text from OSM (name, description, website) is **data, never instructions**; only `http(s)` links are shown; a description is cut to 300 characters.

### Order (stated to the user in one sentence above the list)
Lexicographic, no hidden score:
1. **Match with the interests** named in the request (views, mountains, water, history): the number of key points of matching kinds along the route (skipped when no interests were named).
2. **Practical start:** distance from the user's place or the access point to the start of the track (a start at a public-transport stop counts as practical).
3. **Closeness of length and time to the middle of the requested range.**
4. **Network level** (local, regional before national) and completeness (name, website, marking).
The user can ask to re-sort by length, time, ascent or distance.

### Pipeline (SKILL.md)
A new step **4a** after step 4 (mode, style and loop are known, the anchor place is resolved): ask the **budget and criteria** (distance and/or time, maximum ascent — what step 10 asks today; step 10 then only fills what was skipped), then run the lookup, show the list with progress lines in the user's language, ask: "a number, or «Свой маршрут»". A number → "Adopting"; «Свой маршрут» → the pipeline continues unchanged from step 5. Step 16 keeps counting but reuses the candidate list (no second query) when step 4a ran. The numbering stays (4a, not a renumbering): earlier renumbering broke references.

### Adopting a public route
- The track is resampled every 100 m, each sample snapped to the nearest graph node within 60 m (a sample with no node is dropped), and the planner's router connects consecutive nodes (`route_through_waypoints`), so every later step (elevation, `path_geometry`, `segments`, duration, budget check, restricted zones, notes, map) works unchanged. Extra points of the user are inserted at the cheapest position of the ordered list (`shortest_costs` as for optional points) and are subject to the usual restricted-zone validation and budget check.
- **Fidelity:** the share of the resulting path's vertices within 30 m of the original track; below 90 % the planner says that the path deviates and shows the figure; a candidate with `gaps` is listed with a note but cannot be adopted (the user is offered "Свой маршрут" with its key points as interest points instead).
- **Archive:** an optional LineString property `curated_source` = `{relation_id, name, ref, network, operator, website, length_source, fidelity}`; `build_geojson(..., curated_source=None)`; `archive_validate` checks it only when present (`relation_id` an integer, `website` http(s), `fidelity` 0–1). The map panel shows the source with its website and the OSM attribution; the day plan needs no change. `notes.md` gets the section "Curated routes nearby" with the shown candidates (the fixed heading already exists).

### Progress and language
New catalogue keys (all seven languages, both `progress.py` copies stay identical): lookup of public routes, geometry batch `k of n`, elevations of candidates, key points, "N candidates, M match", Overpass failures reuse the existing keys.

## Degradation
Overpass failure or an empty answer: one line says so and only "Свой маршрут" is offered. A geometry batch that fails twice: those routes are left out and the line says how many. An elevation failure: the route is kept, its ascent and time are marked unknown (not estimated), and criteria on them are not applied to it (said in the line). No key points: the line still has name and figures. Nothing is fabricated: a figure that could not be computed is shown as "—".

## Testing
- Fixtures: three real relations saved from OSM (a 3 KB, a 13 KB and a 31 KB geometry) and a small synthetic set for the edge cases (gaps, duplicates, super-relation, loop, reversed ways, a way listed twice).
- `build_track`, length, loop detection, `prefilter`, filtering by time with a known pace, ranking (each rule alone and in combination, ties), `describe` in every language (no English leaks in a Russian line), the ±25 % rule, key-point assignment by segment distance (a point 70 m from a segment but 200 m from its vertices counts), `adopt` on a synthetic graph (fidelity, a dropped sample, an inserted extra point, a gap), `curated_source` validation, `build_geojson` without it unchanged.
- Network layer with a fake transport: batching, retry, a failed batch, the cache.
- Live check on real data (Pelayos, Moscow, Garmisch bike) in the plan's last task.

## Risks
- OSM relations are inconsistent (gaps, duplicated segments, directions): the track and the length are marked derived, a gap blocks adoption, the figures say "~".
- Overpass load: cache, batches, a single area query for key points, a clear fallback to "Свой маршрут".
- A ranking surprising the user: the rule is stated in one sentence and re-sorting is offered.
- Adoption deviating from the public route: measured and reported (`fidelity`).

## Out of scope
A day section of a long-distance route; web research before the choice; ski, running and other modes; GPX export or import; the day plan's use of `curated_source`.
