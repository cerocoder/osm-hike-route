---
name: osm-day-route-planning
description: Use when the user asks for a one-day walking or cycling route anchored to a specific named place, with terrain preferences (avoid highways, prefer greenery, avoid water), required stops (shop, drinking fountain, or an arbitrary "interest" point like a museum or a good radio-reception spot), an access point to reach the start/end ("точка заброски" — a station, bus stop, or parking lot), a distance/duration budget, or when they ask how to get to a trailhead from their current location.
---

# OSM Day Route Planning

## Overview

Plans a custom one-day walking or cycling route anchored to a named
location, using OpenStreetMap (via the Overpass API) as the primary data
source, web search as a secondary source for anything OSM tags don't
cover, and a local archive so routes (and the reasoning behind them) can be
reused instead of recomputed. Core principle: **shortest path is not the
goal** — the route is built from a weighted, directed graph shaped by the
user's stated preferences and mode/style, and every non-geographic
"interest" claim carries an explicit confidence label instead of being
asserted as fact.

Two modes share one pipeline and one set of scripts: `walk` and `bike`
(`bike` further splits into `leisure`/`sport` styles). Mode/style selects a
JSON preset (`presets/*.json`) that supplies both the routing tag rules
(what counts as passable, what's hard-excluded, what blocks a bike but not
a foot) and the preference weights — the code never hardcodes either. See
spec §3.2, §3.6.

Every script in `scripts/` (including `elevation/`) is **stdlib-only** —
`urllib.request`/`json`/`heapq`/`math`/`pathlib`, no `requests`, no
third-party HTTP client (Global Constraint, spec §3.6). Presets and
`weights.json` are **JSON, not YAML** for the same reason: this keeps the
project's dependency count at zero rather than adding `pyyaml` just for
config comments (Global Constraint, spec §3.6).

## When to Use

- "Plan me a walking/cycling route near <place>" / "маршрут на день рядом с X"
- Route must avoid/prefer something: highways, water, open fields, greenery,
  steep gradients
- Route must pass through required stops: water shop, fountain, museum,
  or any other point of interest — including non-geographic interests
  (radio reception, foraging spots, geology) that OSM doesn't tag directly
- User asks how to reach the start of a route from where they currently are
  (the access point / "точка заброски")
- User wants to revise a route already built by this skill (swap a point,
  redo a leg, change the access point) — see **Revising an Existing Route**
  below, this is not a fresh build

**Not for:** turn-by-turn live navigation, multi-day treks, driving routes,
ski touring (documented future extension, not implemented — would need a
new preset, no code changes).

## Pipeline

1. **Save the verbatim request first**, before parsing or asking anything
   else — `requests_log.append_request(route_dir, request_text, summary)`
   (spec §3.1). The exact wording matters twice: as the source of the
   user's stated interests for the location-research pass (step (e) below),
   and as the accumulated iteration history for future revisions.
2. **Check the archive first** for a route already built near this location
   with compatible constraints (`weights_io.load_weights`,
   `requests_log.read_requests`). Prefer reuse/adaptation over recomputing
   from scratch. If the request is actually about an *existing* archive,
   stop here and follow **Revising an Existing Route** instead.
3. **Ask mode/style if not stated** — `walk` or `bike` (`leisure`/`sport`).
   Load the corresponding preset with `presets.load_preset(mode, style)`.
   Never default to `walk` silently (spec §3.2) — if the user's own words
   already say it, don't re-ask.
4. **Ask loop-vs-point-to-point if not stated.** Propose a loop as the
   default (logistically simpler — no separate end-of-route transport to
   arrange) but always ask rather than deciding silently, unless the user's
   request already implies it ("маршрут от Х до Y") (spec §3.3).
5. **Resolve access points**, independent of the route itself: query OSM
   for stations/stops/parking near the location (`railway=station|halt`,
   `public_transport=station`, `highway=bus_stop`, `amenity=parking`). Do
   **not** route to them — just identify what's reachable, then recommend
   how to get there from the user's current position (ask if not stated).
   Capture `opening_hours` from the element's own tags and any operational
   detail found via web search (schedule quirks, "касса закрыта") as
   `access_notes` — both are optional Point properties (spec §3.3, §3.11).
   Source priority: **Overpass → WebSearch → Claude in Chrome browser** (the
   browser only on explicit user request, or as a last resort when the
   first two don't have enough — never as the default first move).
6. **Resolve interest points** — skill-chosen, user-given, or both (they're
   additive, user points never replace skill-found ones). Before proposing
   your own, run a **location-research web-search pass keyed to the
   interests the user actually stated** in their verbatim request (step 1)
   — targeted searches per stated interest ("виды" and "история" → two
   separate searches, not one generic "что посмотреть в X"). Background
   model knowledge may suggest candidates to go check, but never substitutes
   for a tier label — every claim shown to the user still goes through the
   Interest-Layer Confidence Tiers below (spec §3.4).
7. **Fetch area data via Overpass**: `route_graph.fetch_area_data(lat, lon,
   radius_m, routable_highway=weights["routable_highway"],
   hard_exclude_highway=weights["hard_exclude_tags"].get("highway", []),
   exclude_highway_without_infra=weights["exclude_highway_without_infra"],
   mode=weights["mode"])` returns walkable ways, highways (for avoidance), water, forest, fields,
   plus everything needed for hard exclusion — restricted ways/areas,
   barrier ways, and barrier nodes — in one query, bucketed by tag. The
   three preset-driven arguments matter: without them, a mode's own
   routable ways (e.g. bike's `cycleway`) are never fetched at all, and
   `filter_excluded_ways`'s hard-exclusion/infra rules for highway values
   have nothing to act on (see reference.md). Always fetched, not
   optional. Pick a radius that covers every access point and interest
   point you plan to validate next, not just the anchor location.
8. **Build restricted polygons**:
   `route_graph.build_restricted_polygons(data["restricted"],
   data["barrier_ways"])`. This must happen **before** waypoint validation
   (step 9) and before graph building — it is the shared input both rely on.
9. **Validate every waypoint against restricted zones before building the
   graph** (spec §3.4, Review Focus #1) — never let this surface later as a
   silent "no path found" from the router:
   - For each **user-supplied** point (interest point or access point), call
     `waypoints.validate_user_waypoint(lat, lon, name, restricted_polygons)`.
     It raises `waypoints.RestrictedWaypointError` with a ready-to-relay
     Russian explanation — catch it and tell the user directly which point
     failed and why, then ask them how to proceed (drop it, or pick another).
   - For each **skill-chosen** candidate, pre-filter with
     `waypoints.is_point_restricted(lat, lon, restricted_polygons)` and
     simply drop any that return `True` — never propose it to the user in
     the first place, nothing to explain.
10. **Ask for the distance/duration budget if not stated** — `max_distance_km`
    and/or `max_duration_hours` (spec §3.5). Same rule as mode/style/loop:
    ask explicitly, never assume a number.
11. **Exclude closed/restricted zones, then build the directed, mode-aware
    graph** over what's left:
    ```python
    walkable = route_graph.filter_excluded_ways(
        data["walkable"], restricted,
        hard_exclude_tags=weights["hard_exclude_tags"],
        exclude_highway_without_infra=weights["exclude_highway_without_infra"],
    )
    graph, node_coords = route_graph.build_graph(
        walkable, data["barrier_nodes"],
        blocking_barrier_tags=weights["blocking_barrier_tags"],
        respect_oneway=(mode == "bike"),
    )
    route_graph.tag_edges(
        graph, node_coords, data["highways"], data["water"],
        data["forest"], data["fields"],
        highway_buffer_m=weights["buffers_m"]["highway"],
        water_buffer_m=weights["buffers_m"]["water"],
    )
    ```
    `respect_oneway` only matters for `bike` — `walk` never respects
    `oneway`. A plain two-way segment with no `oneway` tag stays traversable
    in both directions for **both** modes (Review Focus #5) — `build_graph`
    still emits both a forward and a reverse directed edge unless the way's
    own tags say otherwise.
12. **Fetch elevation and tag gradients** — see **Core Pattern** below for
    the full wiring (this is the one place three separately-tested modules,
    the elevation package, `route_graph.tag_grades`, and the router, combine
    into something none of them tests end-to-end on its own).
13. **Solve the mandatory-only route first**: access point(s) + user-given
    interest points, in the best order (nearest-neighbor + 2-opt for a
    handful of points, brute force below that — remember the graph is
    directed, so reversing a leg's direction is not free). Use
    `route_graph.route_through_waypoints(graph, waypoint_ids, preferences)`.
    Then compute this path's **physical** distance (see **Budget & Duration
    Wiring** below — not the same number `route_through_waypoints` returns)
    and call `waypoints.check_mandatory_budget(mandatory_cost_km,
    max_distance_km)`. If it raises `waypoints.BudgetExceededError`, surface
    this as an explicit conflict — increase the budget, or drop a mandatory
    point — never silently build the oversized route anyway (Review Focus
    #3, spec §3.5 step 2).
14. **Add optional (skill-found) points under the remaining budget** with
    `waypoints.select_optional_points(graph, mandatory_path,
    mandatory_cost_km, candidates, preferences, max_distance_km)`. It
    returns `(included, skipped)` — `skipped` entries (by name) go straight
    into the final summary and `notes.md`, they were never silently dropped.
    After inserting the included points, re-solve the full waypoint order,
    recompute physical distance, and re-check the budget — if it's now over
    (possible with non-default preference weights, see **Budget & Duration
    Wiring**), drop the costliest included optional point and repeat rather
    than shipping an over-budget route.
15. **Compute duration**:
    `duration.estimate_duration_hours(distance_km, elevation_gain_m,
    pace_kmh, ascent_minutes_per_100m)`, then
    `duration.duration_warning(estimated_hours, duration_warning_hours)`
    for the soft daylight-fit warning (never blocks route construction,
    unlike the hard budget check in step 13/14).
16. **Count curated routes nearby** (informational only, spec §3.10):
    `overpass_query.count_curated_routes(overpass_query.query_overpass(
    overpass_query.build_curated_routes_query(lat, lon, radius_m,
    route_tags)))` with `route_tags=["hiking", "foot"]` for `walk` or
    `["bicycle", "mtb"]` for `bike`. Mention the count in the summary and
    `notes.md` — it never affects routing.
17. **Save to the archive** — first build the path geometry and the way
    segments **together**: `path_coords, way_segments =
    route_graph.path_geometry(graph, path, node_coords, elevations)` (one
    call, one node path, so the `(lon, lat, ele)` coordinates and the
    `segments` — which road, with `highway`/`surface`/`tracktype`/`sac_scale`/…,
    each part of the route runs on, as inclusive index ranges into those
    coordinates — cannot drift apart). The day-plan skill reads `segments` to
    judge how passable the trails and roads are in winter; a route saved
    without them gets no such assessment and must be re-planned. Then:
    `weights_io.save_weights(route_dir, weights)` (the merged preset +
    overrides + budget — see spec §3.6/§3.11: this is where **inputs** live),
    `route_output.build_geojson(..., way_segments)` (this is where **computed
    outputs** live — distance, duration, elevation gain/loss, warnings,
    skipped points, and the road each part of the route runs on; never
    re-store an input here), and `notes.md` (see
    reference.md's template; **its `## ` headings are fixed** — write each
    exactly as `notes_headings.heading(key, lang)` returns it for the
    language of the notes, never reword them: the map panel and
    `archive_validate` find the sections by these names). **Write `route.geojson` by serializing exactly
    what `build_geojson(...)` returned — never hand-construct or hand-edit
    the JSON.** `build_geojson`'s parameters (`mode`, `distance_km`,
    `elevation_gain_m`, `elevation_loss_m`, `duration_estimate_hours`, etc.)
    have no defaults specifically so a value cannot be silently left out —
    if you don't have a real number for one of them, that means an earlier
    pipeline step (11–16) wasn't actually run, and the fix is to go back and
    run it, not to invent a placeholder or skip the parameter.
18. **Validate the archive before presenting anything to the user**:
    `python3 scripts/archive_validate.py <route_dir>` (or
    `from archive_validate import validate_archive; validate_archive(route_dir)`
    as a library call). This is not optional and not a formality — it is the
    one hard gate against silently shipping an incomplete archive. It exists
    because this exact failure happened for real: a route was once saved
    with `route.geojson`'s `LineString` in 2D (no elevation), none of the
    computed `LineString` properties (`mode`/`distance_km`/
    `elevation_gain_m`/`elevation_loss_m`/`duration_estimate_hours`/…), and
    no `weights.json`/`requests.md` — because the archive had been written
    by hand instead of through `build_geojson`/`save_weights`/
    `append_request`, skipping pipeline steps 12 (elevation) and 15
    (duration) entirely along the way, with only a one-line note in
    `notes.md` ("elevation wasn't queried") to show for it. If
    `validate_archive` raises `ArchiveIncompleteError`, the route is **not
    done**: read what it lists, go back and actually run the missing
    pipeline step(s) (re-fetch elevation, recompute distance/duration,
    whatever it names), and re-save — never hand-patch `route.geojson`'s
    JSON to make the validator stop complaining. Only once it passes
    silently, present the summary to the user: distance, duration (with
    warning if any), access recommendation, route rationale, confidence
    caveats, and which optional points were skipped for budget.

## Revising an Existing Route

A request that refers to an existing archive (swap a point, redo a leg,
change the access point) is **not** a fresh build — it's the next iteration
of the same archive folder (spec §4):

1. Locate the existing `routes/<slug>-<date>/` folder (same reuse-check
   logic as pipeline step 2).
2. Append the new verbatim request to the journal **before** making any
   change — `requests_log.append_request(route_dir, request_text, summary)`
   — same as a fresh build's step 1, just against the existing folder.
3. Load the existing inputs with `weights_io.load_weights(route_dir)`, then
   apply only what the new request actually asks for with
   `presets.revise_weights(existing, changes)`. It deep-merges `preferences`
   (updates just the given keys, leaves the rest); every other top-level key
   you pass in `changes` **replaces wholesale**, it does not merge — so if
   you're changing one entry of a nested dict like `buffers_m`, pass the
   *whole* `buffers_m` dict in `changes`, not just the one key, or you'll
   silently drop the other one. Everything you don't mention in `changes` —
   mode, style, untouched preferences, budget — stays exactly as it was
   (Review Focus #4).
   **A change of `mode` or `style` must NOT go through `revise_weights`**
   (e.g. "переделай в вело-маршрут"): `revise_weights(existing, {"mode":
   "bike"})` changes only the `mode` key and silently keeps walk's
   `routable_highway`, `hard_exclude_tags`, `pace_kmh`, buffers etc.
   Instead rebuild from the new preset —
   `presets.build_weights(presets.load_preset(new_mode, new_style),
   preference_overrides, existing["max_distance_km"],
   existing["max_duration_hours"])` — carrying over the budget and any
   preference overrides the user had set before (recover those by diffing
   `existing["preferences"]` against the old preset's own `preferences` —
   `load_preset(existing["mode"], existing.get("style"))`, since `walk`
   has no `style` key — and ask if a carried-over override no longer makes sense for the new
   mode). Use `revise_weights` only for changes that leave `mode`/`style`
   themselves untouched.
4. Any point being replaced or added goes through the **same** mandatory
   checks as a first build — restricted-zone validation (pipeline step 9)
   and budget re-check (pipeline steps 13-14). A revision gets no immunity
   from either.
5. Re-solve only what the change actually affects where possible (e.g.
   swapping one interest point mainly changes waypoint order and the paths
   around it — no need to re-fetch access points if they weren't touched).
6. Overwrite `route.geojson`/`notes.md`/`weights.json` in the same archive
   folder — no separate versioned subfolder, the iteration history already
   lives in `requests.md`. **Run `archive_validate.validate_archive(route_dir)`
   after overwriting, same as pipeline step 18 for a fresh build** — a
   revision that only touches part of the route still regenerates the whole
   `route.geojson` via `build_geojson`, so it's just as capable of silently
   losing elevation/duration/distance as a first build would be.

## Interest-Layer Confidence Tiers

Always label which tier a claim comes from — never blur them together.

| Tier | Source | How to present |
|---|---|---|
| `tag-backed` | Direct OSM tag (museum, shop, fountain) | State as fact |
| `web-sourced` | Found via targeted web search for "topic + this specific place" | State with the source cited, and note it's unverified in person |
| `derived` | Computed indirectly (e.g. terrain-based estimate) | Label explicitly as an estimate |
| `no-data` | Nothing found | Say so plainly — never invent a plausible-sounding answer |

For anything OSM doesn't tag directly, search the web for the specific
place before falling back to `no-data` — a local blog, club, or park
authority page often exists even when OSM has nothing.

## Access Exclusion (hard, not weighted)

Closed/private/protected zones are **excluded from the graph entirely**
before any weighting happens — the router cannot route through them at
all, not just "prefer not to" (spec §3.4, Global Constraint). Mechanisms,
all in `scripts/route_graph.py`:

1. **Restricted polygons** (`build_restricted_polygons`): built from
   `access=private|no|military` ways, `landuse=military`/`military=*`
   areas, `leisure=nature_reserve`/`boundary=protected_area` areas
   (`fetch_area_data`'s `restricted` bucket is broader than "military" —
   a marked nature reserve is hard-excluded the same as a barracks; keep
   this in mind before assuming a rejected point must be something
   sinister), **and any closed-loop `barrier=fence|wall` way** — a full
   ring of fence around something is treated as an enclosed private zone
   even with no explicit access tag. Relation-mapped zones (the usual form
   for large military areas and reserves) are reassembled from their
   `outer` member ways; a restricted *way* only counts if it is actually
   closed — an open `access=private` driveway is a line, not a zone (see
   reference.md). With `mode=weights["mode"]` passed to `fetch_area_data`,
   a restricted-tagged element that also carries `bicycle=yes|designated`
   (bike) or `foot=yes|designated` (walk) is **not** bucketed as restricted
   *for that mode only* — the usual OSM pattern for a dedicated path through
   a closed area. A bicycle-designated path stays closed to a walk route,
   and without `mode` no override applies at all (strict default).
   `filter_excluded_ways` drops any
   walkable way whose midpoint falls inside one of these polygons, and
   `waypoints.is_point_restricted`/`validate_user_waypoint` run the same
   point-in-polygon check against individual waypoints before the graph is
   even built (see Pipeline step 9).
2. **Hard-excluded tags per preset** (`filter_excluded_ways` via
   `hard_exclude_tags`/`exclude_highway_without_infra`): mode-specific, not
   hardcoded — `walk` hard-excludes `foot=no`; `bike` hard-excludes
   `bicycle=no|dismount`, `highway=steps`, and (`exclude_highway_without_infra`)
   any `trunk`/`primary` way with no positive cycle-infra tag (`cycleway`,
   `cycleway:left|right|both` — values `no`/`none`/`separate` do **not**
   count as infra). `sport`-style bike
   still hard-excludes the same infra-less trunk/primary ways — style never
   relaxes this particular exclusion, only the preference weights around it
   (spec §3.2).
3. **Blocking barrier nodes** (`_blocks_passage`, applied inside
   `build_graph`): a gate/wall/bollard *on* a path blocks routing through it
   only if it's actually locked — `access=private|no`, `locked=yes`, a plain
   `barrier=wall` with no opening, **or** a barrier tag the mode's preset
   lists in `blocking_barrier_tags` (e.g. `cycle_barrier`/`turnstile` for
   `bike` — passable on foot, blocks a bike). An ordinary gate, stile, or
   kissing_gate with no negative access tag and no mode-specific listing is
   assumed passable and does **not** block.

Verified on real data near a Madrid air base (Cuatro Vientos, 2026-09-27,
walk mode, pre-directed-graph): found actual restricted military
installations (a barracks, a military equestrian school) and hard-excluded
90 of 1509 fetched walkable ways that fell inside them. Re-verify this case
after any change to `build_graph`'s directed-edge behavior (see post-plan
manual verification).

## Core Pattern: Preference-Weighted, Mode-Aware, Elevation-Tagged Routing

Distance alone is the wrong objective — a longer path through forest can
beat a shorter one across an open field, and an uphill segment costs more
than the same length downhill. `scripts/route_graph.py` plus
`scripts/elevation/` cover the full flow. Both live in
`skills/osm-day-route-planning/scripts/`, importable by module name once
that directory is on `sys.path` (see `tests/conftest.py` for the exact
one-liner used in this skill's own test suite):

```python
from pathlib import Path

from overpass_query import query_overpass, haversine        # noqa: F401 (imported by route_graph)
from presets import load_preset, build_weights
from route_graph import (
    fetch_area_data, build_restricted_polygons, filter_excluded_ways,
    build_graph, tag_edges, tag_grades, weighted_shortest_path,
    route_through_waypoints, path_geometry,
)
from waypoints import is_point_restricted, validate_user_waypoint, check_mandatory_budget, select_optional_points
from elevation import ElevationService
from elevation.resample import sample_positions, cumulative_distances, interpolate_at_distances
from elevation.providers.open_topo_data import OpenTopoDataProvider
from elevation.providers.open_meteo import OpenMeteoProvider
from elevation.providers.elevation_api_eu import ElevationApiEuProvider
from elevation.providers.open_elevation import OpenElevationProvider
from duration import estimate_duration_hours, duration_warning
from route_output import build_geojson
from progress import Progress

# Console progress, in the USER'S language (en ru es fr de pt it; English for any other): one line per step, plain
# lines without a terminal, sub-progress only for slow steps. Pass `progress` to the functions below that accept it.
progress = Progress(total_steps=5, lang=user_lang)        # user_lang: the language of the conversation / notes.md

preset = load_preset(mode, style)                 # e.g. load_preset("bike", "leisure")
weights = build_weights(preset, preference_overrides, max_distance_km, max_duration_hours)

with progress.step("overpass"):
    data = fetch_area_data(
        lat, lon, radius_m=1500,
        routable_highway=weights["routable_highway"],
        hard_exclude_highway=weights["hard_exclude_tags"].get("highway", []),
        exclude_highway_without_infra=weights["exclude_highway_without_infra"],
        mode=weights["mode"],  # scopes the designated-path override to this mode
        cache_dir=Path("routes/.cache"),  # the answer is kept for 24 h: a revision does not wait for Overpass again;
        progress=progress,                # refresh=True forces a new query (say so if the user doubts the data)
    )
    progress.detail("overpass_done", walkable=len(data["walkable"]), restricted=len(data["restricted"]))
restricted = build_restricted_polygons(data["restricted"], data["barrier_ways"])
walkable = filter_excluded_ways(
    data["walkable"], restricted,
    hard_exclude_tags=weights["hard_exclude_tags"],
    exclude_highway_without_infra=weights["exclude_highway_without_infra"],
)
with progress.step("graph"):
    graph, node_coords = build_graph(
        walkable, data["barrier_nodes"],
        blocking_barrier_tags=weights["blocking_barrier_tags"],
        respect_oneway=(mode == "bike"),
    )
    progress.detail("graph_done", nodes=len(graph), edges=sum(len(e) for e in graph.values()))
with progress.step("tag_edges"):
    tag_edges(graph, node_coords, data["highways"], data["water"], data["forest"], data["fields"],
              highway_buffer_m=weights["buffers_m"]["highway"], water_buffer_m=weights["buffers_m"]["water"],
              progress=progress)

# --- elevation wiring: batch ONCE across every way, never once per way ---

service = ElevationService(
    [OpenTopoDataProvider(), OpenMeteoProvider(), ElevationApiEuProvider(), OpenElevationProvider()],
    cache_path=Path("routes/.cache/elevation.json"),   # shared across routes, NOT per-route (spec §3.8)
)

def compute_node_elevations(ways: list[dict], service: ElevationService) -> dict[int, float]:
    """One dict entry per OSM node id touched by any way, interpolated from
    ~150m samples along that way (spec §3.8) — never a per-node lookup, and
    never one HTTP round trip per way (a real route can have 1000+ ways;
    ElevationService already chunks internally by each provider's
    max_batch, so hand it every sample across every way in one call)."""
    way_samples = []
    all_points: list[tuple[float, float]] = []
    for way in ways:
        coords = [(pt["lat"], pt["lon"]) for pt in way["geometry"]]
        samples = sample_positions(coords, interval_m=150.0)
        way_samples.append((way, coords, samples))
        all_points.extend((lat, lon) for lat, lon, _ in samples)

    all_elevations = service.get_elevations(all_points, progress=progress)

    node_elevations: dict[int, float] = {}
    unresolved = 0
    cursor = 0
    for way, coords, samples in way_samples:
        n = len(samples)
        elevations = all_elevations[cursor:cursor + n]
        cursor += n
        sample_dists = [dist for _, _, dist in samples]
        # Interpolate only over samples a provider actually resolved — do
        # NOT coerce a None to 0.0 before interpolating, that fabricates a
        # fake sea-level dip next to real elevations and produces a bogus
        # gradient. A None sample is simply left out of the interpolation
        # input (Review Focus #2: no crash, no fabricated value).
        known = [(d, e) for d, e in zip(sample_dists, elevations) if e is not None]
        unresolved += sum(1 for e in elevations if e is None)
        if not known:
            continue  # no elevation info at all for this way; its node ids
                       # simply stay out of node_elevations, and tag_grades
                       # below already treats a missing id as grade_pct=0.0
        known_dists, known_elevs = zip(*known)
        node_dists = cumulative_distances(coords)
        interpolated = interpolate_at_distances(list(known_dists), list(known_elevs), node_dists)
        for node_id, elevation in zip(way["nodes"], interpolated):
            node_elevations[node_id] = elevation

    if unresolved:
        import sys
        print(f"warning: {unresolved} elevation sample(s) unresolved by all "
              f"{len(service._providers)} providers — affected edges get no "
              f"gradient penalty", file=sys.stderr)
    return node_elevations

with progress.step("elevation"):
    elevations = compute_node_elevations(walkable, service)        # ticks once per provider request
    progress.detail("elevation_done", **service.last_request)
tag_grades(graph, node_coords, elevations)          # mutates graph in place: grade_pct per directed edge

preferences = {**weights["preferences"], "gradient_threshold_pct": weights["gradient_threshold_pct"]}
with progress.step("routing"):
    path, cost = weighted_shortest_path(graph, start_node_id, end_node_id, preferences)
```

**Progress output.** Every long step reports to the user, in the user's language (`Progress(lang=...)`: the
language of the conversation; the wording lives in `progress.py`'s catalogue, never pass free text). Functions that
accept `progress=` are `fetch_area_data`, `query_overpass`, `tag_edges`, `ElevationService.get_elevations`,
`select_optional_points` (key `optional`) and `route_through_waypoints` (key `routing`). Run the planning script so that its
output reaches the user while it works: a script whose step may take more than 30 s (Overpass, the first elevation
fetch of an area) is started in the background with its output written to a log that is then followed. When
Overpass answered from `routes/.cache` (its line says how old the answer is), a user who suspects stale data gets
`refresh=True`.

**Do not paste an elevation-wiring version that calls `get_elevations` once
per way** — with a real fetch (radius 1500m+) that's easily 1000+ separate
rate-limited HTTP calls (Open-Topo-Data allows 1 req/s and 1000/day on its
free tier) where one batched call would do. And do not coerce a provider's
`None` to `0.0` **before** interpolating — interpolate only over the
samples that resolved, and only fall back to "no elevation data for this
way" (leaving its nodes out of the dict, which `tag_grades` already treats
as `grade_pct=0.0`) when a way has zero resolved samples.

`gradient_threshold_pct` and `preferences` are two separate keys in a
preset/`weights.json` (see the preset JSON files), but `route_graph._edge_cost`
expects `gradient_threshold_pct` inside the `preferences` dict it's handed —
merge them into one dict before calling `weighted_shortest_path`/
`route_through_waypoints`, as shown above, or the gradient penalty silently
uses `_edge_cost`'s hardcoded fallback (8) instead of the preset's actual
value (e.g. `walk`'s 12).

Preference weights and tag rules come from the loaded preset (pipeline step
3) plus any user overrides — never hardcode them (spec §3.6).
`weighted_shortest_path` returns `(None, None)` when a waypoint is
unreachable in the fetched area — widen `radius_m` and retry rather than
letting it fail silently (this can also mean the only path was
hard-excluded as restricted; check `data["restricted"]` before assuming
it's a radius problem). `route_graph.py`/`elevation/` are libraries (import
them as above) — neither has a `__main__` block, unlike `overpass_query.py`
which can also be run standalone for ad hoc queries.

## Budget & Duration Wiring

`route_through_waypoints`/`weighted_shortest_path` return a **preference-
weighted cost**, not physical distance — with any preference weight other
than 1.0 (which is the normal case, presets set several), a detour through
preferred terrain can score *cheaper* than its real length. This is fine
for choosing a path, but it is the wrong number to hand to
`waypoints.check_mandatory_budget` or to write as `route.geojson`'s
`distance_km` — both are user-facing physical quantities. Compute physical
distance separately by summing `haversine` over the solved path's actual
node coordinates:

```python
def path_distance_km(path: list[int], node_coords: dict) -> float:
    total_m = 0.0
    for a, b in zip(path, path[1:]):
        lat1, lon1 = node_coords[a]
        lat2, lon2 = node_coords[b]
        total_m += haversine(lat1, lon1, lat2, lon2)
    return total_m / 1000.0
```

Use `path_distance_km` (not the router's `cost`) for: the mandatory-route
budget check (Pipeline step 13), the re-check after adding optional points
(Pipeline step 14), and the final `distance_km` written to `route.geojson`.
If the user's budget is time-only (`max_duration_hours`, no
`max_distance_km`), convert it to a **transient** km ceiling
(`max_duration_hours * weights["pace_kmh"]`) for use during optional-point
selection, but do the *final* accept/reject check with
`duration.estimate_duration_hours` against the real elevation-aware
profile, not the rough pace-only conversion — and never write that derived
km figure into `weights.json`, which holds only what the user actually
stated (spec §3.5, §3.11).

`elevation_gain_m`/`elevation_loss_m` for the final summary/`route.geojson`
are the sum of positive/negative elevation deltas between consecutive nodes
on the solved path, using the same `elevations` dict `compute_node_elevations`
built above — skip a delta where either endpoint's elevation is unknown
rather than treating the gap as 0m of climb.

## Archive

Location: `routes/` **relative to the current working directory** at the
time the skill runs — never a hardcoded absolute path (this skill runs
across different machines/agents).

```
routes/
  .cache/
    elevation.json    # shared across ALL routes, not per-route (spec §3.8) —
                       # written by elevation.cache.write_cache, once per batch
  <slug>-<date>/
    route.geojson      # geometry + waypoints — COMPUTED OUTPUTS (route_output.build_geojson)
    weights.json        # merged preset + overrides + budget — INPUTS (weights_io.save_weights)
    requests.md          # verbatim request journal, one block per iteration (requests_log.append_request)
    notes.md              # location, preferences used, why segments were
                           # chosen, confidence caveats for each interest layer,
                           # access-point recommendation, curated-routes count, date
```

Create `routes/` and `routes/.cache/` on first save if they don't exist
(`weights_io.save_weights`/`elevation.cache.write_cache` both call
`mkdir(parents=True, exist_ok=True)`). Before building a new route, check
whether an existing entry already fits — reuse/adapt rather than recompute
(pipeline step 2); if the request is actually about an existing archive,
follow **Revising an Existing Route** instead of starting over.

**Never duplicate a value between `weights.json` and `route.geojson`**
(Global Constraint, spec §3.11): `weights.json` holds what's needed to
*reproduce* a run — mode, style, preference weights, tag rules, budget.
`route.geojson`'s `LineString` properties hold what the run *produced* —
distance, duration, elevation gain/loss, warnings, skipped points. If
you're about to write the same number to both files, one of them is wrong.

**An archive is not saved until `archive_validate.validate_archive(route_dir)`
passes** (pipeline step 18) — it checks that all four files exist, that
`notes.md` has the fixed headings of the five required sections (request,
access, route reasoning, points of interest, distance and duration — in any
language of `notes_headings.py`), that
`route.geojson`'s `LineString` coordinates are 3D and carry every computed
property (`mode`, `distance_km`, `elevation_gain_m`, `elevation_loss_m`,
`duration_estimate_hours`, etc.), and that `weights.json` has a `mode` key.
This is the enforcement mechanism for everything this section says about
inputs/outputs/never-hand-editing — see `scripts/archive_validate.py`'s own
module docstring for the real incident that made this necessary.

**Presets are read-only reference data.** `presets/*.json` is never
modified by a run — `presets.build_weights`/`presets.revise_weights` both
return a fresh dict; the caller writes that to the route's own
`weights.json`, never back to `presets/`.

## Output Format: route.geojson

`osm-day-route-show` renders this file, and reads specific property names
— get them right the first time rather than relying on that skill to
degrade gracefully. Built by `route_output.build_geojson`. The two geometry
types do **not** handle a missing elevation the same way — check
`route_output.py` directly before assuming one behavior covers both:

- **`LineString` coordinates** are always **3D**, `[lon, lat, ele]`, for
  every vertex — `build_geojson`'s coordinate list comprehension coerces a
  `None` elevation to `0.0` rather than emitting `null`, so the array shape
  is always consistent (this was a deliberate Task 19 fix — see spec §3.11
  and the Task 19 ledger ruling).
- **`Point` coordinates** are `[lon, lat]` (2D) when elevation is unknown,
  and `[lon, lat, ele]` (3D) only when it's known — `_point_feature` simply
  **omits** the `ele` slot when `pf.get("ele")` is `None`, it does **not**
  coerce it to `0.0` the way the LineString path does. Don't assume the two
  geometry types are consistent here; a consumer reading Point coordinates
  must handle both a 2-element and a 3-element array.

One `LineString` Feature for the solved path, one `Point` Feature per
waypoint/interest point.

**`LineString` properties** (all computed outputs, spec §3.11 — never
copy an input here):

| Property | Value |
|---|---|
| `name` | The route's own title, in the language you're writing `notes.md` in |
| `mode` | `"walk"` or `"bike"` |
| `style` | `"leisure"`/`"sport"` for bike, `null`/omitted for walk |
| `distance_km` | Physical distance — see **Budget & Duration Wiring**, not the router's weighted cost |
| `elevation_gain_m`, `elevation_loss_m` | Summed positive/negative deltas along the solved path, to 0.1 m (`build_geojson` also rounds every vertex and point elevation to 0.1 m — the data is ~30 m resolution, more decimals are noise; an unknown vertex elevation is still `0.0`) |
| `duration_estimate_hours` | From `duration.estimate_duration_hours` |
| `duration_warning` | String from `duration.duration_warning`, or `null` |
| `curated_routes_count` | From `overpass_query.count_curated_routes` |
| `is_loop` | `true`/`false` — same start/end access point or not |
| `skipped_interest_points` | Names from `select_optional_points`'s `skipped` list |
| `segments` | From `route_graph.path_geometry`: `[{"from": i, "to": j, "way_id": …, "highway": …, "surface": …, …}]` — inclusive vertex indices of the `LineString`, consecutive runs sharing their boundary vertex, together covering every vertex; only the tags the way has (`highway`, `surface`, `smoothness`, `tracktype`, `sac_scale`, `mtb:scale`, `trail_visibility`, `bicycle`, `foot`, `winter_service`, `snowplowing`) |

**Point properties**:

| Property | On | Value |
|---|---|---|
| `name` | both | The bare local geographic name, **exactly as OSM/the local source gives it — never translated, and no added English word or parenthetical aside** (that's `note`'s job). |
| `note` | Point | Extra descriptive detail that doesn't belong in `name`. Optional. |
| `type` | Point | **Exactly this key, not `kind`** (a real bug from the original skill, caught after the fact — `osm-day-route-show` reads `type`, and a wrong key silently drops the popup subtitle and marker styling). One of: `viewpoint`, `cave`, `river`, `meadow`, `historic`, `historic_viewpoint`, `karst`, `access`, `spring`, `fountain`, `sight`, `waypoint` — pick the closest fit. |
| `tier` | Point | One of the four Interest-Layer Confidence Tiers above — reused as-is |
| `role` | Point, `type: "access"` only | `"start"` / `"end"` |
| `source` | Point | Citation URL/text for a `web-sourced` claim |
| `osm_id` | Point | `"node/<id>"` or `"way/<id>"` of the source OSM element, when present — the stable half of `osm-day-route-show`'s Wikipedia-link cache key |
| `wikidata` | Point | Copied through **verbatim** from the source element's own `wikidata` tag, if present |
| `wikipedia` | Point | Copied through verbatim from the source element's own `wikipedia` tag (`"lang:Title"` form), if present and there's no `wikidata` tag |
| `search_names` | Point | `{lang: name}` — only when the point's own `name` isn't in the language you'd want to search a specific Wikipedia edition in |
| `opening_hours` | Point, `type: "access"` only | Copied from the OSM tag if present (spec §3.11) |
| `access_notes` | Point, `type: "access"` only | Free-text schedule/access detail found via web search when the OSM tag alone isn't enough (spec §3.11) |

**Check the POI tags you already fetched for `wikidata`/`wikipedia`/
`opening_hours` before writing `route.geojson`** — Overpass's `out tags`
(or `out geom`) already returns every tag a node/way has, so this is "don't
discard a field already in hand," not an extra query.

## Quick Reference: Constraint → OSM Tag / Preset Field

| Constraint | Overpass filter / preset field |
|---|---|
| Walkable paths (`walk`) | `highway=path\|footway\|track\|residential\|living_street` |
| Routable ways (`bike`) | preset's `routable_highway` — adds `cycleway`, and `secondary` for `bike-sport` — passed to `fetch_area_data`'s `routable_highway` argument, or those ways are never fetched at all |
| Bike hard-exclude | `bicycle=no\|dismount`, `highway=steps` — preset `hard_exclude_tags` |
| Highway needs cycle infra (bike) | `trunk\|primary` with no positive `cycleway`/`cycleway:left\|right\|both` value (`no`/`none`/`separate` = no infra) — preset `exclude_highway_without_infra` |
| Oneway respected (bike only) | `oneway=yes`, reopened by `oneway:bicycle=no` or `cycleway=opposite*` |
| Blocking barrier (mode-specific) | preset `blocking_barrier_tags`, e.g. `cycle_barrier`, `turnstile` for bike |
| Avoid parallel-to-highway | `highway=trunk\|primary\|secondary` (buffer distance = preset `buffers_m.highway`) |
| Prefer greenery | `landuse=forest`, `natural=wood`, `leisure=park` |
| Avoid water | `natural=water`, `waterway=*` (buffer = preset `buffers_m.water`) |
| Avoid steep gradient | `grade_pct` > preset `gradient_threshold_pct`, penalty = preference `avoid_steep_gradient` |
| Water shop | `shop=supermarket\|convenience\|beverages` |
| Drinking fountain | `amenity=drinking_water` |
| Museum | `tourism=museum` |
| Train/halt access point | `railway=station\|halt` |
| Bus stop access point | `highway=bus_stop`, `public_transport=stop_position` |
| Parking access point | `amenity=parking` |
| Existing curated route (walk) | `route=hiking\|foot` — `overpass_query.build_curated_routes_query(..., ["hiking","foot"])` |
| Existing curated route (bike) | `route=bicycle\|mtb` — `overpass_query.build_curated_routes_query(..., ["bicycle","mtb"])` |
| Closed/private/protected zone (hard-excluded) | `access=private\|no\|military`, `landuse=military`, `military=*`, `leisure=nature_reserve`, `boundary=protected_area`, closed-loop `barrier=fence\|wall` |
| Blocking gate/wall on a path (any mode) | `barrier=*` node with `access=private\|no`, `locked=yes`, or plain `barrier=wall` |

Full query templates (with the header workaround Overpass needs) are in
`reference.md`. A ready-to-run fetch helper is in `scripts/overpass_query.py`.

## Common Mistakes

- Rewording a `notes.md` heading ("Порядок точек", "Итог", "Interest-layer confidence") instead of
  the fixed one from `notes_headings.py`: the map panel then says the section is missing and
  `archive_validate` refuses the archive. Put extra material under a required section or add your own
  section with another name; do not rename the fixed ones.

- **Building `path_coords` by hand and `segments` separately** — use
  `route_graph.path_geometry(graph, path, node_coords, elevations)` for both
  from the same node path; hand-built coordinates plus segments from another
  list mismatch by an index and the day plan then reads the wrong road for a
  part of the route (`archive_validate` catches a wrong total length, not a
  shifted boundary).
- **Leaving `segments` out or handing over an old route** — a route saved
  before `segments` existed, or built without `way_segments`, has no road data;
  the day-plan skill then says it cannot judge passability. Re-plan it.

- **Hand-writing or hand-editing `route.geojson`'s JSON instead of calling
  `build_geojson`, or skipping pipeline step 18's validation** — this is how
  an archive silently ends up with 2D `LineString` coordinates (no
  elevation) and missing `distance_km`/`elevation_gain_m`/
  `elevation_loss_m`/`duration_estimate_hours` while still looking like a
  finished route: a real route was shipped this way, with elevation and
  duration simply never computed, and nothing caught it until a user asked
  why the map had no elevation data. `build_geojson`'s parameters have no
  defaults for exactly this reason — if a value is missing, that's a signal
  to go rerun the pipeline step that produces it, not to work around the
  function. Always finish with `archive_validate.validate_archive(route_dir)`
  (pipeline step 18) and treat a raised `ArchiveIncompleteError` as blocking,
  not advisory.
- **Treating shortest path as best** — always apply preference weights
  (Core Pattern), even when the user's example constraint sounds minor.
- **Silently defaulting mode/style, loop-vs-point-to-point, or the budget**
  instead of asking — all three are explicit questions when not already
  stated in the request (spec §3.2/§3.3/§3.5, Global Constraint). Only skip
  the question when the user's own wording already answers it.
- **A user-supplied interest point in a restricted zone silently failing
  later as "no path found"** — validate every waypoint with
  `validate_user_waypoint`/`is_point_restricted` **before** building the
  graph, and relay `RestrictedWaypointError`'s message directly to the user
  (Review Focus #1, spec §3.4).
- **Letting an all-providers-failed elevation batch crash route building**
  — a point every provider fails on gets `None`, which must flow through to
  `grade_pct=0.0` (no gradient penalty) with a stderr warning, never an
  unhandled exception (Review Focus #2, spec §3.8 step 4).
- **Coercing a `None` elevation sample to `0.0` before interpolating** — see
  Core Pattern's elevation wiring; this fabricates a fake sea-level dip and
  a bogus gradient right next to real elevations, which is worse than
  simply leaving that way's nodes without an elevation.
- **Calling `ElevationService.get_elevations` once per way** instead of
  batching every way's samples into one call — burns through a rate-limited
  free-tier provider's daily quota needlessly (Core Pattern).
- **A mandatory-only route that already exceeds the budget getting built
  anyway** — `check_mandatory_budget` raising `BudgetExceededError` must
  become an explicit conflict for the user to resolve (raise the budget,
  drop a mandatory point), never a silently oversized route (Review Focus
  #3, spec §3.5 step 2).
- **Using the router's preference-weighted cost as the physical distance
  for budget checks or `route.geojson`'s `distance_km`** — under non-default
  preferences these two numbers diverge; always recompute physical
  distance via `haversine` over the solved path (**Budget & Duration
  Wiring**).
- **Revising one field of `weights.json` and losing the rest** —
  `revise_weights` only deep-merges `preferences`; passing a partial nested
  dict for any other key (e.g. just one `buffers_m` entry) replaces that
  whole key, not just the given sub-field. Pass the full dict when only
  changing part of it (Review Focus #4, spec §4 step 3).
- **Switching mode/style with `revise_weights(existing, {"mode": ...})`** —
  only the `mode` key changes; tag rules, pace and buffers stay those of the
  old preset, so a "bike" route is still routed and timed as a walk. Rebuild
  with `load_preset(new_mode, new_style)` + `build_weights` instead,
  carrying over budget and overrides (**Revising an Existing Route**, step 3).
- **Letting the switch to a directed graph make a plain two-way segment
  one-way by accident** — a way with no `oneway` tag must still get both a
  forward and a reverse edge for **both** `walk` and `bike`; only an
  explicit `oneway=yes` (and only when `respect_oneway=True`, i.e. `bike`)
  should suppress the reverse edge (Review Focus #5).
- **Mixing up `(lat, lon)` and `(lon, lat, ele)`** — `node_coords` (from
  `build_graph`) and Overpass geometry points are `(lat, lon)`;
  `route_output.build_geojson`'s `path_coords` argument and GeoJSON
  coordinate arrays are `(lon, lat, ele)`. Swapping them silently produces
  a route plotted in the wrong place with no error.
- **Assuming Point coordinates are always 3D like LineString ones** —
  `route_output._point_feature` omits the `ele` slot entirely (a 2-element
  `[lon, lat]` array) when elevation is unknown, it does not coerce to
  `0.0` the way `build_geojson`'s LineString path does. A consumer or
  render step that unconditionally indexes `coordinates[2]` on a Point will
  crash on any point with unresolved elevation. See **Output Format:
  route.geojson**.
- **Fabricating no-data interest layers** — if web search finds nothing,
  say so; don't invent a "known" spot.
- **Skipping the access-point step** — every route needs a reachability
  answer, even if the user didn't ask for one explicitly.
- **Hardcoding the archive path** — always resolve `routes/` relative to
  cwd.
- **Writing back to `presets/*.json`** — presets are read-only reference
  data; a run's merged/revised weights go to the route's own
  `weights.json`, never back to the preset file.
- **Duplicating a value between `weights.json` and `route.geojson`** — one
  holds inputs, the other holds computed outputs; never write the same
  number to both.
- **Omitting an explicit, descriptive User-Agent** against overpass-api.de
  (and against the elevation providers) — the default curl UA and an
  ordinary browser UA both get rejected; only a plain descriptive one gets
  through. See reference.md.
- **Querying too large a radius/timeout in one call** — Overpass 504s;
  split or shrink.
- **Weighting restricted/protected zones instead of excluding them** —
  `access=private/no/military`, `leisure=nature_reserve`,
  `boundary=protected_area`, and enclosed fenced areas are a hard drop
  before the graph is even built, not a high `avoid_*` penalty the router
  could still cross if nothing else exists.
- **Blocking every gate on a trail** — only a locked/private/plain-wall
  barrier node, or one tagged in the mode's `blocking_barrier_tags`, blocks;
  an ordinary gate or stile has no negative access tag and must stay
  passable.
- **Writing `kind` instead of `type` on a Point feature** — silently drops
  the popup subtitle and marker styling in `osm-day-route-show`, with no
  error anywhere to catch it. See **Output Format: route.geojson**.
- **Baking a description into `name`** — besides violating "local name,
  untranslated," it also breaks `osm-day-route-show`'s Wikipedia-link
  matching. Put it in `note`.
- **Dropping `wikidata`/`wikipedia`/`opening_hours` tags on the floor when
  they were already in the Overpass response** — a POI fetched with
  `out tags` may already carry these; skipping them forces
  `osm-day-route-show` into a weaker coordinate-and-name search.
