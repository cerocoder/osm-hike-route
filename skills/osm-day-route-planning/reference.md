# Overpass Query Reference

## Required headers (avoid the 406)

`overpass-api.de` runs a WAF that 406s requests with no descriptive
User-Agent — both curl's default UA and an ordinary browser UA string
get rejected at `/api/interpreter` (a browser UA can still pass at
`/api/status`, which is misleading — test against `/api/interpreter`
itself). A plain, descriptive, non-browser UA gets through:

```bash
curl -s -m 90 \
  -H "User-Agent: research-script/1.0" \
  -H "Accept: */*" \
  "https://overpass-api.de/api/interpreter" \
  --data-urlencode 'data=<QUERY>' \
  -o out.json
```

Mirror if the main instance is saturated: `https://overpass.kumi.systems/api/interpreter`
(same headers apply). This is what `scripts/overpass_query.py`'s
`query_overpass()` already does — endpoint failover and `research-script/1.0`
header included — so use it directly rather than shelling out to curl.

The four elevation providers (`scripts/elevation/providers/*.py`) are a
separate HTTP surface with their own descriptive UA
(`osm-day-route-planning/1.0 (elevation lookup)`) — same principle, different
string, since they're different hosts.

## Timeout/radius tuning

`around:RADIUS` on `relation`/`way` queries that need full geometry gets
expensive fast — the server computes geometry for every candidate to
check the distance filter. Symptoms: HTTP 504, or a 200 with an
`<Error>...timeout...` body (still exit code 0 from curl — check the
body, not just the HTTP status).

- Start around 10–15 km radius for `out tags;`/`out count;` (cheap — no
  geometry).
- Full `out geom;` fetches (needed for length calculation or graph
  building) should use a bbox or a smaller radius, and set
  `[timeout:80]` in the query with a matching or larger `curl -m`.
- If a query keeps timing out, shrink the radius before increasing
  curl's timeout — the server-side limit is what's failing, not the
  client.

## Query templates

**Curated routes count near a point** (informational counter, spec §3.10 —
walk vs bike use different `route=*` values): implemented as
`overpass_query.build_curated_routes_query(lat, lon, radius_m, route_tags)`
+ `overpass_query.count_curated_routes(result)`. Call with
`route_tags=["hiking", "foot"]` for `walk`, `route_tags=["bicycle", "mtb"]`
for `bike`.

```
[out:json][timeout:25];
relation["route"~"hiking|foot"](around:15000,LAT,LON);
out count;
```

**Important**: this uses `out count;`, not `out tags;` — the response is a
single pseudo-element `{"type": "count", "tags": {"relations": "N", ...}}`,
**not** a list of `type: "relation"` elements. `count_curated_routes` reads
`tags.relations` off that one element; don't write a new counter that
filters for `el["type"] == "relation"`, it will always find zero (this was
an actual bug caught during Task 18's review, not a hypothetical one).

**Full geometry for a specific existing route** (for length calc / graph
seed, e.g. when reusing a curated route from the archive-check step):
```
[out:json][timeout:80];
relation(RELATION_ID);
out geom;
```

**Access points near a location** (pipeline step: resolve access points):
```
[out:json][timeout:60];
(
  node["railway"~"station|halt"](around:5000,LAT,LON);
  node["public_transport"="station"](around:5000,LAT,LON);
  node["highway"="bus_stop"](around:3000,LAT,LON);
  node["amenity"="parking"](around:3000,LAT,LON);
);
out tags center;
```
Check each returned element's tags for `opening_hours` before falling back
to a web search for schedule/access details (spec §3.3) — an access point's
own OSM tags are the cheapest source for this.

**Walkable ways + highways + water + forest + fields + access
restrictions** (graph building): already implemented as
`route_graph.fetch_area_data(lat, lon, radius_m, routable_highway,
hard_exclude_highway, exclude_highway_without_infra, mode)`. `mode`
(`weights["mode"]`) scopes the designated-path override — a
restricted-tagged way that also carries `bicycle=yes|designated` is exempt
only for `mode="bike"`, `foot=yes|designated` only for `mode="walk"`, and
`mode=None` exempts nothing. The three tag-list
arguments come straight from the active preset (spec §3.6) —
`weights["routable_highway"]`, `weights["hard_exclude_tags"].get("highway",
[])`, and `weights["exclude_highway_without_infra"]` respectively — and
control what actually gets fetched into the walkable candidate set;
omitting them defaults to walk's original fixed tag list
(`path|footway|track|residential|living_street`). It fetches all these
categories (including relation-based forest/water multipolygons, and
everything needed for hard access exclusion — see SKILL.md's Access
Exclusion section) in one query and buckets them by tag. Use it directly
rather than re-writing this query by hand; the standalone form below is
for reference/debugging only (it also doesn't vary by preset — swap in
your mode's routable_highway/hard_exclude/infra tag values by hand if
using it directly for bike), and documents the **restricted-zone** tag
set completely (`fetch_area_data`'s own restricted bucket also excludes
`leisure=nature_reserve` and `boundary=protected_area`, not just
military/private — a broader hard-exclusion than "restricted" might
suggest; it means well-marked nature reserves are treated as off-limits
the same as a military base, which is worth knowing before assuming a
route through one failed for some other reason):

```
[out:json][timeout:80];
(
  way["highway"~"path|footway|track|residential|living_street"](around:RADIUS,LAT,LON);
  way["highway"~"motorway|trunk|primary|secondary"](around:RADIUS,LAT,LON);
  way["landuse"~"forest|farmland|meadow"](around:RADIUS,LAT,LON);
  way["natural"~"wood|water"](around:RADIUS,LAT,LON);
  way["leisure"="park"](around:RADIUS,LAT,LON);
  relation["landuse"="forest"](around:RADIUS,LAT,LON);
  relation["natural"~"wood|water"](around:RADIUS,LAT,LON);
  way["access"~"private|no|military"](around:RADIUS,LAT,LON);
  way["landuse"="military"](around:RADIUS,LAT,LON);
  way["military"](around:RADIUS,LAT,LON);
  relation["landuse"="military"](around:RADIUS,LAT,LON);
  relation["military"](around:RADIUS,LAT,LON);
  way["leisure"="nature_reserve"](around:RADIUS,LAT,LON);
  relation["leisure"="nature_reserve"](around:RADIUS,LAT,LON);
  way["boundary"="protected_area"](around:RADIUS,LAT,LON);
  relation["boundary"="protected_area"](around:RADIUS,LAT,LON);
  way["barrier"~"fence|wall"](around:RADIUS,LAT,LON);
  node["barrier"](around:RADIUS,LAT,LON);
);
out geom;
```

**Restricted relations carry geometry on their members, not on
themselves**: with `out geom`, a `type: "relation"` element has no
top-level `geometry` — each entry in `members` carries its own
`geometry`, and a large zone's `outer` boundary is usually split across
several member ways. `build_restricted_polygons` stitches the `outer`
members end-to-end (either direction) into closed rings — a member with a
blank/missing role counts as outer (older simple multipolygons) — and
ignores `inner` members; outer segments that never close (incomplete relation
download) produce no polygon rather than a wrong one. A plain restricted
*way* only becomes a polygon if it is actually closed (first point ==
last point) — an open `access=private` way such as a driveway is a line,
not an area, and does not exclude anything around it.

**Bike-mode routable ways are fetched via preset arguments, not the
hardcoded default** (fixed after being a known gap): pass
`weights["routable_highway"]`, `weights["hard_exclude_tags"].get("highway",
[])`, and `weights["exclude_highway_without_infra"]` to `fetch_area_data`'s
`routable_highway`/`hard_exclude_highway`/`exclude_highway_without_infra`
arguments (SKILL.md's pipeline example does this). Skipping these
arguments silently falls back to walk's fixed tag list — a dedicated cycle
path (`highway=cycleway`) or a `bike-sport` route along a `secondary` road
then won't appear in the fetched data at all, regardless of what the
preset says, so `routable_highway` in a preset is only a guarantee when
these arguments are actually passed through.

**Walkable and highway-avoidance buckets are independent**:
`hard_exclude_highway` and `exclude_highway_without_infra` values are
fetched into the *walkable* candidate bucket (so `filter_excluded_ways` can
see and drop them), and any `motorway|trunk|primary|secondary` way **also**
lands in `highways` regardless — a way can be in both. So a bike-sport
routable `secondary`, or an infra-less `trunk`/`primary` that
`filter_excluded_ways` later hard-drops from the graph, still feeds
`tag_edges`'s `avoid_near_highway` proximity buffer for the paths running
alongside it. (Before this was fixed, walkable took precedence and bike's
highway avoidance only ever reacted to `motorway`.)

**Bike-specific tags used elsewhere in the pipeline** (hard exclusion,
oneway, and blocking barriers — applied by `filter_excluded_ways`/
`build_graph`/`_direction_allowed`, not by the Overpass query itself, since
these are per-way/per-node tag checks on already-fetched elements):

| Concern | Tag(s) | Where checked |
|---|---|---|
| Bike hard-exclude | `bicycle=no\|dismount`, `highway=steps` | `filter_excluded_ways` via preset `hard_exclude_tags` |
| Highway needs cycle infra | `trunk\|primary` without a positive `cycleway`/`cycleway:left\|right\|both` value (`no`/`none`/`separate` don't count) | `filter_excluded_ways` via preset `exclude_highway_without_infra` |
| Oneway (bike only) | `oneway=yes`, reopened by `oneway:bicycle=no` or `cycleway=opposite*` | `build_graph` → `_direction_allowed` (only when `respect_oneway=True`) |
| Blocking barrier (bike only) | `barrier=cycle_barrier\|turnstile` | `build_graph` → `_blocks_passage` via preset `blocking_barrier_tags` |

**Required-waypoint POIs**:
```
[out:json][timeout:60];
(
  node["shop"~"supermarket|convenience|beverages"](around:RADIUS,LAT,LON);
  node["amenity"="drinking_water"](around:RADIUS,LAT,LON);
  node["tourism"="museum"](around:RADIUS,LAT,LON);
);
out tags center;
```

## Archive file templates

`routes/<slug>-<date>/route.geojson` — a FeatureCollection: one 3D
(`[lon, lat, ele]`) LineString for the path, one 3D Point per waypoint/
interest point, properties carrying the tags used to build the route (so a
future reuse check can compare constraints without recomputing). Written by
`route_output.build_geojson` — see SKILL.md's Output Format section for the
full property schema.

`routes/<slug>-<date>/weights.json` — the merged preset + user overrides +
budget that produced this run, written by `weights_io.save_weights`. Copy
the shape of `presets/<mode>[-<style>].json`, plus `max_distance_km`/
`max_duration_hours` (see SKILL.md's Core Pattern / Quick Reference).

`routes/<slug>-<date>/requests.md` — append-only iteration journal, written
by `requests_log.append_request`/read by `requests_log.read_requests`. One
block per iteration:
```markdown
## Итерация N (2026-09-28T12:00:00+00:00)

> <verbatim user request, HTML-comment markers escaped>

Изменения: <one-line summary of what changed>

<!-- requests_log entry: {"iteration": N, "timestamp": "...", "request": "...", "summary": "..."} -->
```

`routes/<slug>-<date>/notes.md` — the `## ` headings are **fixed**, one wording per
section and language (`scripts/notes_headings.py`; below in English, e.g. Russian
"Запрос / Доступ / Обоснование маршрута / Точки интереса / Пропущенные необязательные точки /
Готовые маршруты рядом / Дистанция и время"). Write the heading of the notes' language
exactly; `skipped` and `curated` only when there is something to say:
```markdown
# <Location name> — <date>

## Request
- Location: ...
- Mode/style: walk | bike (leisure|sport)
- Loop or point-to-point: ...
- Required waypoints: ...
- Preferences: ...
- Interest layers requested: ...
- Distance/duration budget: ...

## Access
- Drop-off point(s): ...
- Recommended way to get there from <current position>: ...
- Opening hours / access notes found for each access point: ...

## Route reasoning
- Why this path over shorter alternatives: ...
- Segments chosen for greenery / avoided for highway proximity: ...
- Elevation profile summary (gain/loss, any steep-gradient tradeoffs): ...

## Points of interest
- <layer>: <tier> — <source or "no data found">

## Optional points skipped for budget
- <name>: would have cost ~X km to insert, over budget

## Curated routes nearby
- N public route=hiking/route=bicycle relations found in OSM within the search radius

## Distance and duration
- Total distance: X km
- Estimated duration: Y h (warning: ... / none)
```

## Length calculation (haversine)

Already implemented as `overpass_query.haversine(lat1, lon1, lat2, lon2)` —
import it rather than re-pasting the formula below, which is kept here only
for reference/debugging:

```python
import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def route_length_m(elements):
    """elements: Overpass 'out geom' relation members list"""
    total = 0.0
    for member in elements:
        geom = member.get('geometry')
        if not geom:
            continue
        for i in range(len(geom) - 1):
            total += haversine(geom[i]['lat'], geom[i]['lon'],
                                geom[i+1]['lat'], geom[i+1]['lon'])
    return total
```
