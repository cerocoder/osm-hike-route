# Planner speed, console progress and elevation precision — design

Date: 2026-10-01. Scope: `osm-day-route-planning` (speed, elevation precision, progress hooks) and `osm-day-route-day-plan` (progress per plugin). Research behind it: a timing of every planner stage on real Overpass data for Pelayos de la Presa (radius 7 km, walk; 35 398 graph nodes, 72 658 directed edges), repository code untouched.

## Decisions (from the user)

| Question | Decision |
|---|---|
| Console output | Stay with the prose pipeline and add a `progress.py` module; no `plan_route.py` CLI. |
| Elevations | Only cache them (the cache already exists, see A3); no coarser sampling, no smaller area. |
| Elevation precision in `route.geojson` | Stored with 0.1 m precision (was e.g. `682.020635343171`). |
| Language of the progress output | **The user's language, all of it** (step names, details, notes, warnings, the module's own words), not just a few words. |

## Measured starting point

| Stage | Time | Note |
|---|---|---|
| Overpass, one combined query | 32 s | repeated on every re-plan or revision, no cache |
| `filter_excluded_ways`, `build_graph` | 0.3 s | fine |
| `tag_edges` | **59 s** | 56 s in `point_in_ring`: 3.3 million calls, every directed edge against every forest polygon (59 polygons, 4 640 vertices). The highway/water part was already fixed by the grid index merged before. |
| Elevations (first run) | about 91 s | 9 079 samples, 100 per request, first provider allows 1 request/s; cached afterwards |
| Dijkstra | about 100 ms per pair | `select_optional_points` runs three per consecutive pair of the path per candidate |

Prototype of A1 on the same data: landcover for all edges in **0.5 s** (was about 57 s), the same 6 919 forest edges.

## Part A — speed

### A1. Landcover in `tag_edges`
- Compute near-highway, near-water and landcover **once per undirected edge** (the forward and reverse edges of a physical segment have the same midpoint, so the same tags); write the result into both directed edges.
- Forest and field rings get a precomputed bounding box; a ring is tested with `point_in_ring` only if the midpoint lies in its box. Forest still wins over field, as now.
- The result must equal the current one exactly. Tests keep the old brute-force computation as an oracle and compare on random graphs and rings, including points on box borders.

### A2. Overpass response cache
- `query_overpass(ql, ..., cache_dir=None, max_age_s=86400, progress=None)`. With `cache_dir`, the JSON answer is stored as `<cache_dir>/overpass/<sha256 of the query text>.json` (the text contains the centre, the radius and the tag patterns, so a different mode or radius is a different key); a fresh entry (younger than `max_age_s`) is returned without a request. `refresh=True` bypasses the read. Writes are atomic (temporary file, then rename); an unreadable or malformed entry is ignored, never an error. Entries older than 7 days are removed on write.
- `fetch_area_data(..., cache_dir=None, refresh=False, progress=None)` passes them through. The SKILL example passes `Path("routes/.cache")`, the folder that already holds the elevation cache.
- Why 24 hours: OSM changes slowly, but closures matter; the user can always ask for a refresh, and the planner must say when it used a cached answer and how old it is (progress note).
- Failed attempts and endpoint switches are reported through `progress` (see B), so a 3-minute silence on Overpass errors becomes visible.

### A3. Elevations: cache only
- No change to sampling (150 m) or to the set of ways. The cache (`ElevationService`, `routes/.cache/elevation.json`, key = rounded coordinates + dataset) already makes the second run free; A3 is only that the long first run reports progress (batch `k/n`, provider, cached share) through `progress`.
- The cache keeps full precision (only `route.geojson` is rounded, see C).

### A4. `select_optional_points`: one Dijkstra per source instead of three per pair
- New `route_graph.shortest_costs(graph, start, preferences, targets=None)` returns the preference-weighted cost to each target (stops when all targets are settled; `None` for unreachable ones). `weighted_shortest_path` is unchanged.
- The insertion cost of a candidate between consecutive path nodes `a`, `b` is `cost(a→c) + cost(c→b) − cost(a→b)`. The graph is directed (grades differ per direction), so the runs are: one from every distinct path node (targets: all candidates and all path nodes) and one from every candidate (targets: the path nodes) — `P + C` runs instead of `3·P·C`. The costs are the same numbers; results must be identical to the current function (oracle test on random graphs, including unreachable candidates and a one-node path).

## Part B — console progress

### B1. `progress.py` (planning: `scripts/progress.py`; day plan: `scripts/day_plan/progress.py`, an identical copy, compared by a planning test)
Stdlib-only. API:

```python
progress = Progress(total_steps=9, lang="ru", stream=None)   # stream defaults to sys.stderr
with progress.step("Граф дорог") as step:      # prints "[3/9] Граф дорог …", on exit "      ✓ 0,1 с · <detail>"
    step.tick(done, total, note=None)          # rate-limited sub-progress
    step.detail("35 398 вершин, 72 658 рёбер")
progress.note("Overpass: использован кэш (возраст 3 ч)")
progress.warn("...")                            # "  ! ..." 
NullProgress()                                  # the default everywhere: does nothing
```
- **Non-TTY (Claude Code tool output, logs):** plain lines only, flushed at once, no `\r` and no colour. `tick` prints at most one line every 5 s and at completion, e.g. `      … высоты 41/91 (45 %)`.
- **TTY:** the `tick` line is rewritten in place (`\r`), a `✓` in green and `!` in yellow; `NO_COLOR` is respected.
- **Language — everything the user reads is in the user's language.** `Progress(lang=...)` takes the language of the conversation (the same code as `--user-lang` of the map and the language of `notes.md`: `en ru es fr de pt it`, English fallback for any other, and for any single missing key). Callers never pass free text: they pass a message **key** and parameters (`progress.step("graph")`, `step.detail("graph_done", nodes=35398, edges=72658)`, `progress.note("overpass_cache_hit", age_h=3)`), and the module holds the catalogue `MESSAGES[lang][key]` with every step title, detail, note, warning and its own words (seconds, done, failed, "attempt 2 of 4", "batch 41 of 91") in all seven languages. Numbers follow the language (decimal comma in `ru es fr de pt it`, a thin space between thousands). An unknown key is shown as the key itself (never an exception in the middle of a planning run). The day-plan copy carries the catalogue for its plugin lines (plugin names reuse the section titles already in `day_plan/i18n.py`).
- A step that raises prints `      ✗ <seconds> · <ExceptionName: message, one line>` and re-raises.
- The clock and the stream are injectable for tests.

### B2. Hooks in the planner
All take an optional `progress=None` (treated as `NullProgress`); nothing changes for callers that do not pass one: `query_overpass`, `fetch_area_data`, `tag_edges` (tick every 5 000 undirected edges), `ElevationService.get_elevations` (tick per batch), `select_optional_points` (tick per Dijkstra run), `route_through_waypoints` (tick per leg).

The SKILL.md pipeline example creates `Progress(total_steps=N, lang=<the user's language>)` and wraps each step of the pipeline in `progress.step(...)`; it also says that a script whose step may exceed 30 s is run in the background with its output written to a log that is then followed.

### B3. Day plan
`run_plugins(ctx, plugins, progress=None)` reports one line per plugin (`✓ weather 0,8 s`, `✗ fire: HTTP 503`), `build_day_plan.main(..., progress=None)` creates a `Progress` only when run as a CLI (`--quiet` switches it off); tests and library callers get `NullProgress`. The existing stdout lines (`wrote …`, hints) and the stderr warnings stay as they are.

## Part C — elevation precision in `route.geojson`
- `build_geojson` rounds every elevation to **0.1 m** (`round(ele, 1)`) in LineString vertices and in Point features; an unknown elevation is still written as `0.0` for the LineString (existing rule, other code treats it as unknown) and left out for a Point. `elevation_gain_m` and `elevation_loss_m` are rounded to 0.1 m as well (they are the sum of unrounded steps: the gain is not recomputed from rounded vertices). `distance_km` and the coordinates keep their precision.
- Existing archives are not rewritten. Readers (day plan, map) need no change.
- The planner `SKILL.md` schema table states the precision.

## Testing
- A1, A4: oracle tests (old implementations kept in the tests) on random inputs; A1 also checks that forward and reverse edges get equal tags.
- A2: hit, miss, expired, `refresh`, malformed entry, atomic write, key changes with radius and mode patterns, pruning of old entries — all in a temporary folder with an injected clock and a fake transport; no network.
- B: fake stream with `isatty` true and false, injected clock for rate limiting, `NO_COLOR`, error path; every key of the catalogue exists in all seven languages with the same placeholders (a test compares the sets), a Russian run prints no English words outside exception text and proper names, an unknown language falls back to English, an unknown key prints the key; hook tests (a recording progress object receives the expected calls); the two `progress.py` copies are identical.
- C: written elevations have at most one decimal; gain/loss rounded; unknown elevation rules unchanged.
- Whole suites of all three skills stay green. Acceptance on the cached Pelayos data: `tag_edges` under 5 s (prototype 0.5 s); a second run of the planning script makes no Overpass request within 24 h.

## Risks
- A stale cached Overpass answer hides a new closure → 24 h limit, the note with the age, `refresh=True`.
- The cache folder grows → pruning of entries older than 7 days on write.
- An optimisation changes a result silently → oracle tests with exact equality.
- Progress lines make tool output noisy → rate limit, one line per step, nothing when `NullProgress`.

## Out of scope
A\* or bidirectional search, coarser elevation sampling or a smaller elevation area, parallel plugins in the day plan, a `plan_route.py` CLI, progress in `render_map`, migrating old archives.
