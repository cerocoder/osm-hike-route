# Hike conditions: full-day forecast, ticks by terrain, nearby water — design

Date: 2026-10-01. Scope: the `osm-day-route-day-plan` skill (`weather`, `light`, `transit`, `bio_hazards`, a new start resolver, two new plugins, `record_fact.py`, `facts.py`, `i18n.py`, `SKILL.md`, README). Research behind it: live probes of the Open-Meteo Marine API (sea and lakes), the Open-Meteo archive (no lake variable), USGS NWIS; repository code read, not changed.

## Goal

Three changes requested by the user, one design:

1. The forecast covers the **24 hours of the route's day plus 4 hours after the end of the trip**, so a long hike shows what waits after it. The start of the trip is the start the user gave, or the start the plan itself recommends (which takes the access points and their timetables into account).
2. **Ticks are reported only where the route passes through forest or grass** (meadows, fields), not at the sea or in a desert.
3. **Water within 500 m** of the route or of its points of interest is described: the sea or ocean first, then the two largest other bodies in detail, the rest listed.

## Decisions (from the user)

| Question | Decision |
|---|---|
| Forecast window | All 24 hours of the date, plus 4 hours after the end of the trip. |
| No `--start` given | The plan's recommended start is used as the start for everything (forecast window, finish, return checks). A user-given `--start` always wins. |
| Recommended start | The earliest feasible start, but not earlier than 07:00; if the route would not fit before sunset otherwise, 07:00 is ignored and the earliest feasible start is taken. |
| Ticks | Only on forest, scrub, grassland, heath, meadow, grass or farmland; below 5 % of the route nothing is said about ticks. |
| Water: where | 500 m from the route track and from every point of interest; access points are also used as centres. |
| Water: what is shown | The sea or ocean in a separate first row; then the two largest other bodies with full data; the others listed (name, type, distance, near what), at most 15 lines. |
| Water temperature | Sea: model data. Lakes and rivers: an estimate, labelled as such (no free global source exists). |
| Bathing, pollution, hazards | Bathing from OSM tags; pollution and hazards from web research recorded as facts. |

## Research findings

- **Sea:** `marine-api.open-meteo.com/v1/marine` (hourly, no key) returns `sea_surface_temperature` and `sea_level_height_msl` (tides included). Checked on the Bay of Biscay: 21.5 °C, level −1.7…+0.8 m with a clear tidal cycle. Forecast horizon about 9 days (`null` from about +10, HTTP 400 from about +24); past dates work (2025-08-01: 22.7 °C), so a climatology of the same date over previous years is possible, as `weather.py` already does. The grid is coarse (about 28 km); a coastal point can be `null`.
- **Lakes:** the Marine API returns `null` for Baikal, Ladoga, Onega, Superior, Geneva and the Caspian. The Open-Meteo forecast and archive APIs have no lake temperature variable (`lake_mix_layer_temperature` is rejected). Public datasets exist (ERA5-Land through Copernicus CDS, Copernicus Land LSWT, LakeTEMP with 1.4 M lakes, ARC-Lake) but all need an account or a bulk download: not embedded here.
- **Rivers:** USGS NWIS (parameter 00010) answers without a key but covers only the USA; Hub'Eau, UK EA and others are national. Not embedded.
- **Conclusion:** sea temperature and tides are data; inland temperature is an estimate from air temperature, labelled `derived`.

## Part 1. Start and the forecast window

### New module `day_plan/start.py`
Runs before the plugins and sets `ctx.start` (minutes after midnight, local) and `ctx.start_source` (`user` | `recommended` | `none`), and `ctx.finish` (start + `duration_hours`). The clock offset of the place is taken from the cached weather request (the weather plugin fetches it anyway), so the resolver has no cycle with `light`.

- Priority: `--start` → recommended → `none` (no `duration_hours`: nothing is computed, as today).
- **Earliest** start = max of: sunrise; the opening of the start access point (OSM `opening_hours`) when it has hours; `first_arrival_local` of the `transit` fact (the earliest time public transport brings one to the start point).
- **Latest** start = min of the following, each minus the route duration: sunset − 60 min; `last_departure_local` − 30 min; the closing of the return access point.
- **Recommended** = max(earliest, 07:00) when that is ≤ latest; else earliest when ≤ latest; else the window is empty.
- **Empty window:** a `danger` warning names the conflicting limits ("the first bus arrives at 09:10, daylight allows a start only until 08:40"); the start used is the latest daylight start.
- **No transport fact recorded:** the plan says so ("the first/last public transport was not recorded, the transport limits are not applied") instead of silently using sunrise.
- Polar day/night: sunrise and sunset limits are replaced by the fixed windows `weather.py` already uses; the 07:00 rule stays.
- The line in the plan: "Start: HH:MM (recommended by the plan / given by you)".

### Fact `first_arrival_local`
`record_fact.py --plugin transit --first-arrival HH:MM`, stored by `facts.py` like `last_departure_local`; refused for other plugins. `--first-departure` stays as it is (stored, not compared). `SKILL.md` documents both and tells to record the first arrival at the start point together with the last departure back.

### Existing checks use the resolved start
`light`, `transit`, `poi_hours` and `common.finish_minute` read `ctx.finish`; the "latest start" line of `light` becomes the recommendation line. Without `--start` the return checks now run on the recommended start.

### Weather (`plugins/weather.py`)
- The shown window: the 24 hours of the date, then up to 4 hours after the finish. When the finish + 4 h passes midnight, the next day is requested too (the cache key gets the date range; one Open-Meteo request with `start_date` and `end_date`). `daytime_rows` stays as the function for the day (used by the bio plugin), the table uses the new window.
- Rows after the finish are marked "after the finish" in a column or a trailing marker; warnings (thunder, gusts, cold, heat, rain, fog) are computed on every shown hour, and a warning caused only by an after-finish hour says so.
- A line above the table: the start and its source. Climatology source (beyond +15 days): the same, from the archive for both days.
- `shared["rows"]`, `shared["daytime_rows"]` keep their meaning for dependent plugins; `shared["window_rows"]` is added.

## Part 2. Ticks only on forest and grass

### New data-only plugin `plugins/land_cover.py` (`omit=True`)
One Overpass query around the track (`around:30`, polyline of the route, geometry returned): `natural=wood|scrub|grassland|heath`, `landuse=forest|meadow|grass|farmland`. The kinds are one constants table. Cached for a week like the other OSM queries, run through the shared Overpass mirror health, size-capped.

- Up to 300 points along the track are tested locally against the returned polygons (bounding-box prefilter first, multipolygon holes honoured).
- Result: `shared["land_cover"] = {"share": {"forest": f, "grass": g}, "total": t, "known": True}`; `known=False` when Overpass failed.

### `bio_hazards`
- `depends_on` gains `land_cover`.
- Total share below 5 %: no tick line, no tick warning, no tick advice. If nothing else is in the section, it is left out as today.
- 5 % or more: the existing temperature and season logic, plus the line "forest ~N %, meadows and fields ~M % of the route"; the `caution` warning only here.
- `known=False`: the existing line stays with "terrain type not determined, estimate without vegetation" and the warning is `info`, not `caution`.
- Regional facts (`facts.json`, `bio_hazards`) are shown only when ticks were assessed for this route.
- Mosquito, blackfly and horsefly logic is unchanged.

## Part 3. Water within 500 m

### New data-only plugin `plugins/water_near.py` (`omit=True`)
One Overpass query `nwr(around:500, <track polyline and points>)` for `natural=water`, `natural=coastline`, `waterway=river|canal`, `leisure=swimming_area|bathing_place` (streams are not taken). Centres: the track, every point of interest, every access point. Output `out tags bb center`; the size is the bounding-box diagonal. Cache a week; a size cap and a nearest-first cut. Each body keeps the nearest centre: "at the track", "at the start", "at <name of the point>", and the distance.

### Plugin `plugins/water.py` (group `hazards`, title "Water nearby")
`depends_on = ("weather", "water_near")`.

- **Order:** the sea or ocean (a coastline within 500 m) first, in its own row; then the two largest of the others; then the rest as a plain list, at most 15 lines, then "and N more".
- **Temperature:**
  - Sea: Marine API `sea_surface_temperature` at a coastal sample; if `null`, the neighbouring grid points (four offsets) are tried; still nothing: "no data". Beyond the forecast horizon: the mean of the same date over the previous years (marked "climatology, not a forecast"). Label `derived`.
  - Lake or river: an estimate from the daily mean air temperature over the previous 14–30 days (one cached archive request), exponentially smoothed; the time constant grows with the size of the body, a river reacts faster. Label `derived`, "an estimate, the error is a few degrees". Below 4 °C: "ice is possible".
- **Bathing:** from OSM tags (`swimming`, `bathing`, `access`, `leisure`, `sport`): allowed / forbidden / not stated, check locally. Label `tag-backed`. Water below 15 °C adds a cold-shock caution.
- **Pollution and hazards** (currents, algae, jellyfish, crocodiles, steep banks, local bans): a new fact type `water` in `record_fact.py` (`--plugin water`, with `--warning`), filled from the web after the plan is built; no fact: "no data on pollution recorded". Label `web-sourced`.
- **Tides (sea only):** the extrema (high and low water, time and height) of `sea_level_height_msl` over the shown forecast window; label `derived`, "a guide, not a navigation table". A range of 2 m or more adds an `info` warning.
- **Layout:** a table (water, near what, temperature, bathing, pollution and hazards), the tide block under the sea, then the list of the rest.
- **Failures:** Overpass down: "water not determined" (`no-data`); Marine down: temperature "–", the rest stays. Each source is isolated like the other plugins.

## Cross-cutting

- **i18n:** every new string through `tr()`; English and Russian complete, the other languages as the neighbouring plugins do.
- **Order of plugins:** start resolver → weather → light → … → land_cover, water_near (data) → bio_hazards, water.
- **Confidence:** each section keeps the repository's tiers; the water section is `web-sourced` when a fact is used, else `derived`.
- **Docs:** `SKILL.md` (start resolver, `first_arrival_local`, `water` fact, new sections) and README.

## Testing

- Start: each limit alone, an empty window, exactly 07:00, the 07:00 exception for a long route, `--start` from the CLI winning, no `duration_hours`, polar day.
- Weather: a two-day request when the finish + 4 h passes midnight, after-finish marking, a warning caused only by an after-finish hour.
- Land cover: a beach route (no tick lines), a forest route, a mixed one, an Overpass failure, a point inside a multipolygon with a hole.
- Water: a Bay of Biscay fixture (sea + a lake), a mountain lake without the sea, a river, no water, Overpass failure, Marine failure, `swimming=no`, tide extrema, ordering and the 15-line cut.
- Facts: `--first-arrival` stored and refused for other plugins; the `water` fact stored and shown.
- Real-network probes are not part of the test suite: Overpass and Open-Meteo are mocked with fixtures.

## Out of scope

- Embedding LakeTEMP, ERA5-Land, Copernicus LSWT or national river-temperature services (they need accounts or bulk downloads); a later extension if a free API appears.
- Navigation-grade tide tables.
- Bathing-water quality from an official API (the web fact covers it).
- Changes to route planning or the map (`osm-day-route-planning`, `osm-day-route-show`).
