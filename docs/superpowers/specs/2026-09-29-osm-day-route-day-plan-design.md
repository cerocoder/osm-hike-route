# osm-day-route-day-plan: a day briefing for a saved route

Date: 2026-09-29
Status: draft (design), pending user review

## Context

`osm-day-route-planning` builds a route and saves it in
`routes/<place>-<date>/`; `osm-day-route-show` renders that folder as
`map.html`. Neither says anything about the *specific day* the person will
walk or ride: daylight, hourly weather, whether the bus back still runs,
whether the museum is open, and what can hurt them on the way.

This spec adds a third skill, `osm-day-route-day-plan`. For a saved route
and a date it writes `day-plan-<YYYY-MM-DD>.md` into the route folder, and
`osm-day-route-show` embeds every such plan in `map.html`.

Same house rules as the other two skills: **stdlib-only** Python, no API
keys required (a few optional keys unlock extra sources), every claim
carries a confidence label, and a missing datum is reported as `no-data`,
never invented. Plugin architecture mirrors `place_info/` and
`tile_providers/`.

## Goals

- Given a route folder and a date, produce one Markdown day plan covering:
  daylight, hourly weather, how to reach the access points, whether points
  of interest are open, hazards, air, radiation, fire danger and mobile
  coverage.
- Embed **all** plans of a route, by date, into `map.html`, so the single
  HTML file can be forwarded and still contains every planned day.
- Offer each plan as a downloadable `.md` and as a browser-printable PDF.
- Isolate failures: one broken source degrades one section to `no-data`.

## Non-goals

- No route changes. If the plan shows the route does not fit the day
  (sunset before the estimated finish, last bus before the estimated
  return, radiation zone on the track), the skill warns and points back to
  `osm-day-route-planning`.
- No astronomical events (meteor showers, eclipses, moon phases, twilight
  tables). Only sunrise, sunset and day length. Astronomy is a candidate
  for a separate skill.
- No live navigation, no multi-day plans.
- No server-side PDF generation (would need a third-party library).
- No weather/fire/coverage map layers in `map.html` (possible later).
- No scraping of operator coverage maps, Yandex Weather's pollen map, or
  ISDM-Rosleskhoz maps (no public API); these appear as links only.

## Skill boundary and division of labour

Deterministic work is done by stdlib scripts. Anything that needs a web
search (timetables, animals, restrictions, people-related risks, seasonal
notes) is done by Claude following `SKILL.md`, and recorded in
`facts.json` (section id, Markdown, sources, confidence tier). The
orchestrator merges `facts.json` into the plan. Where `facts.json` has no
entry for a web-dependent section, that section is `no-data` with a hint on
what to search for.

Inputs: route folder, date (`YYYY-MM-DD`), language, departure point
(city, station or stop). If the departure point is not in the conversation
or `notes.md`, Claude asks.

## Output: `day-plan-<YYYY-MM-DD>.md`

Written to the route folder. Plans for different dates coexist; re-running
for the same date overwrites that date's file. Section order is fixed:

1. **Summary**: the 3-5 highest-severity warnings across all sections.
2. **Light**: sunrise, sunset, day length, and margin between sunset and
   the route's estimated finish for a start time (default: start so the
   route ends with a margin, or the person's stated start).
3. **Weather by hour**: table for the daylight window (and route window).
4. **Getting there**: access points, their operating hours on that
   weekday/holiday, services serving them, recommendations from the
   departure point.
5. **Points of interest**: open or closed on that date, special features.
6. **Hazards**: ticks and biting insects (mosquitoes, blackflies,
   horseflies), animals, mountain hazards, people-related risks (see
   plugins), air quality and pollen, radiation, fire danger.
7. **Mobile coverage**.

The file begins with a metadata line: forecast fetched-at timestamp (UTC
and local), date, mode, departure point (city/station level only, see
Privacy), plugin versions.

Language: the person's language. Section headings are localized (en, ru,
es, fr, de, pt, it), and `show` matches them by an alias table like
`SECTION_ALIASES`.

## Orchestrator and plugin interface

New package `scripts/day_plan/`, structured like `scripts/place_info/`:

- `base.py`: `SectionPlugin` with `plugin_id`, `order`, `depends_on`
  (plugin ids whose shared data it needs), and
  `run(ctx) -> Section`. `Section` holds `markdown`, `confidence`,
  `sources`, `warnings` (each with `severity`: info/caution/danger and
  text), and optional `shared` data for dependants.
- `service.py`: runs plugins in dependency order, wraps each in
  try/except (failure gives a `no-data` section plus a logged reason),
  assembles the file. Weather is fetched once by the weather plugin and
  passed to dependants via `shared`.
- `cache.py`: per-route-folder JSON cache. Weather TTL 3 h, static data
  unlimited. Same pattern as `place_info/cache.py`.

`ctx` carries: parsed `route.geojson`, date, timezone, language,
departure point, `facts` from `facts.json`, HTTP helper with timeout.

Plugin order: `light`, `weather`, `transit`, `poi_hours`, `bio_hazards`,
`mountain`, `people_hazards`, `air`, `radiation`, `fire`, `cell_coverage`, then
`summary` last.

## Plugins

### light
Sunrise, sunset and day length computed locally with the NOAA solar
algorithm from the route centroid and the date, converted to the local
timezone. No network. Also reports the margin to the route's estimated
finish. Confidence `derived`.

### weather
Open-Meteo Forecast API (free, no key), hourly, `timezone=auto`:
temperature, apparent temperature, precipitation and its probability,
cloud cover, visibility and weather code (fog: codes 45/48 or visibility
under 1000 m), wind speed, wind direction (reported as *from*, degrees and
compass point), wind gusts, snow depth, thunderstorm codes. Forecast
horizon 16 days. Past dates and dates beyond the horizon use the Open-Meteo
archive: past dates show actuals; far-future dates show a climatological
estimate from the same date in previous years, explicitly labelled
`derived`, never presented as a forecast. Confidence `derived` (model
output).

### transit
Access-point operating hours and headways from OSM (`opening_hours`,
`interval`, `route=bus|train|subway|tram` relations) via Overpass.
Weekday, weekend and public-holiday variants for the date. Web search adds
timetables, last departures and route recommendations from the departure
point (recorded in `facts.json`). Public holidays: checked against a
free holiday source at implementation time; fallback is a web-sourced
note. `tag-backed` (OSM) or `web-sourced`.

### poi_hours
Minimal `opening_hours` evaluator covering common syntax (weekday ranges,
time ranges, `off`, `PH`, seasonal months). Unparseable values are shown
verbatim with `no-data` status, never guessed. Notes about closures and
special features from `notes.md` and `facts.json`. `tag-backed` or
`web-sourced`.

### bio_hazards
- **Ticks:** activity estimated from the weather plugin's daily mean
  temperature and the month (ticks generally active from about +5 to
  +7 C), plus regional facts from `facts.json` (`derived` and
  `web-sourced`).
- **Biting insects ("gnus": mosquitoes, blackflies/midges, horseflies,
  biting midges).** Especially important for Siberia and the Urals, but
  reported for any route. The complex is not one species, so the plan
  reports each group separately from the weather plugin's hourly data and
  the route's terrain:
  - *Mosquitoes* depend on standing water (OSM `natural=wetland|water`,
    `waterway=*` slow reaches near the route) and warm, calm air; worst
    around dawn and dusk.
  - *Blackflies/midges* are tied to running water (streams and rivers
    within a few hundred metres) and can stay active until the first
    autumn cold, in places outnumbering mosquitoes.
  - *Horseflies* peak in the hottest, sunny hours (roughly 12:00-16:00
    local), not at dusk.
  - Wind speed, humidity, light and temperature all modulate activity;
    stronger wind and cold suppress it, calm humid warm air favours it.
  The output is a per-hour risk band (low/moderate/high) per group and a
  short list of what to do (repellent, head net, clothing, avoid stopping
  near still water at dusk, choose windy ridges for rests). Thresholds
  are heuristics kept in a config table, not measurements; they are
  labelled `derived`, and regional facts (season start and peak for the
  route's region) are added from `facts.json` (`web-sourced`). The
  heuristic table needs checking against regional sources during
  implementation.
- Animals (bears, wild boar, wolves, snakes, stray dogs, hunting season
  and hunting-area closures): from `facts.json` only, `web-sourced`.

### mountain
Reported only when the route is in the mountains, decided from the
elevation data the planning skill stores in `route.geojson`
(`elevation/`): maximum elevation at or above 600 m, **or** relief
(max minus min elevation) of at least 300 m. If the archive has no
elevation data the section is `no-data`, never guessed.

Tiers by maximum elevation:
- **From 600 m (or relief >= 300 m):** slips and falls (steepest
  gradients from the elevation profile, OSM `sac_scale` T1-T6,
  `via_ferrata_scale`, `trail_visibility`, `natural=scree|cliff|
  bare_rock`, `hazard=*` on or near the track); rockfall, landslide and
  mudflow risk after rain (a `derived` estimate from slope, recent rainfall
  via Open-Meteo `past_days`, and scree/cliff features; the NASA LHASA
  landslide nowcast is linked as a reference, not queried, because it is
  gridded files without a point API); fast weather change and thunderstorms
  on ridges; fog and whiteout navigation; cold (about 6.5 C per km of
  height gained relative to the valley, hypothermia even in summer);
  river crossings, flash floods in narrow valleys and afternoon
  snowmelt rises; late-lying snow patches and ice where the freezing
  level is below the route's high point; shading by ridges making sunset
  earlier than the computed value; slower pace and harder rescue.
- **From 1500 m:** stronger warnings for cold, wind, UV (higher with
  altitude), dehydration and sunburn, and aggravation of existing
  medical conditions.
- **From 2500 m:** acute mountain sickness: unacclimatized people can
  develop symptoms about 4-12 hours after arriving, some at lower
  altitude; advice on acclimatization, and to descend if symptoms
  appear. Oxygen shortage is *not* reported below this tier.
- **Avalanche and glaciers, only where applicable:** avalanche danger
  level from EAWS bulletins (CAAML v6, published for Austria, France,
  Switzerland, Italy, Germany/Bavaria, Norway, Slovenia and others) for
  the route's region and date when a bulletin exists; for regions without
  a public bulletin (including Russia) the section says so and links what
  exists. Glacier and crevasse warnings when OSM `natural=glacier` is
  within reach of the track. Snow cornices in spring where snow is
  reported.

Weather inputs come from the weather plugin. Open-Meteo applies no
elevation correction to wind, so ridge gusts are likely underestimated;
the plan states this. Whether Open-Meteo offers freezing level height,
CAPE and lightning potential as hourly variables is verified at
implementation time; if not, thunderstorm risk uses weather codes and
temperature/humidity heuristics, labelled `derived`. Confidence:
`tag-backed` (OSM tags, EAWS), `derived` (models and thresholds).

### people_hazards
Only verifiable, sourced items: conflict-zone or access restrictions,
border zones requiring permits (for example parts of Russia), known
problem sections, and official travel advisories for the region. No
generalizations about populations. Without a source: `no-data`.
`web-sourced`.

### air
- **Pollen:** Open-Meteo Air Quality pollen variables. The CAMS Europe
  domain reaches roughly 45 E; beyond it the section is `no-data` with a
  link to Yandex Weather's pollen map (the Yandex Weather API is
  key-gated and does not list pollen; nothing is scraped). The exact
  domain edge is verified by a live request during implementation.
- **Pollution:** PM2.5, PM10, ozone, NO2, SO2, dust from Open-Meteo Air
  Quality.
- **Emissions:** industrial objects from OSM (`landuse=industrial`,
  `power=plant`, `man_made=chimney|works`) within about 10 km, with a
  "route is downwind" estimate from the hourly wind direction. `derived`.

### radiation
Static registry `data/radiation_zones.json`: each entry has geometry
(polygon or circle), contamination type (Cs-137, Sr-90, Pu, etc.), event
and year, a note on current status, and a source URL. Intersection of the
track and points with zones, plus a proximity margin. On any hit the plan
carries a `danger` warning:

- do not pick mushrooms or berries there;
- springs and other natural water may be contaminated: do not drink or
  collect water;
- avoid dust, and open fires on the zone's soil;
- consider wind and wildfire resuspension.

Scope: Eurasia except China, Mongolia and the far east outside Russia; all
of Europe and Russia; western and northern Kazakhstan (Semipalatinsk, Azgir).
Every registry entry must be backed by a cited source before inclusion.
Verified so far: East Urals Radioactive Trace (Chelyabinsk, Sverdlovsk,
Tyumen), Techa-Iset river system, Lake Karachay, Mayak, Bryansk/Kaluga/
Tula/Orel Chernobyl trace, Chernobyl Exclusion Zone, Polesie reserve
(Belarus), Semipalatinsk, Sellafield. To research and verify before adding:
Totskoye, Novaya Zemlya, Soviet peaceful underground explosions (Perm,
Arkhangelsk, Yakutia), Krasnoyarsk-26/Zheleznogorsk, Seversk, Andreeva
Bay, Wismut (Saxony/Thuringia), Jachymov, La Hague, Scandinavian and
Bavarian Chernobyl hotspots, Balkan depleted-uranium sites, Zaporizhzhia
NPP as a current-risk area. The registry build is its own implementation
task.

Confidence: `tag-backed` where the registry cites an official or
scientific source, `web-sourced` otherwise. No live dose-rate feed is used
(no open API for Russia; EURDEP has no simple API).

### fire
- Own Fire Weather Index (Canadian FWI) computed in stdlib from Open-Meteo
  daily data, spun up with `past_days` because moisture codes carry over
  from previous weeks. For Russia, also the Nesterov index and the
  Rosleskhoz weather fire-danger class (KPO 1-5, order No. 287 of
  2011-07-05).
- Cross-check against EFFIS (Copernicus) fire-danger forecast via its WMS
  (no key; layer name and `GetFeatureInfo` format verified at
  implementation time). In Europe, EFFIS wins over the own estimate when
  both exist and are shown side by side.
- Russia: link to the ISDM-Rosleskhoz map (no API).
- Active fires near the route: NASA FIRMS, optional user key
  (`OSM_DAY_ROUTE_FIRMS_KEY`); without it, `no-data` with a link.
- Legal restrictions (forest access bans, open fire bans by region and
  season): web search, `web-sourced`.
- Output: hourly danger level, wind (direction fire/smoke would carry),
  and an explicit recommendation to postpone at extreme class.

### cell_coverage
Mobile masts from OSM (`man_made=mast|tower` with `communication:mobile_phone`
or `tower:type=communication`) near the route via Overpass, distance from
each track segment to the nearest mast, and a terrain-aware estimate of
segments with likely weak or no signal (long distance from masts,
enclosed valleys, dense forest; thresholds in a config table by terrain
type, using the elevation data the planning skill already stores). Links
to operator coverage maps for the region and to nPerf/OpenCellID.
Advice: download offline maps and GPX, tell someone the route, carry a
power bank, 112. The absence of masts in OSM does not mean no coverage;
the plan says so. Masts: `tag-backed`; weak-coverage segments: `derived`.

### summary
Collects every plugin's warnings, sorts by severity, lists the top 3-5 at
the top of the file. Also lists which sections are `no-data`.

## Integration into `osm-day-route-show`

Changes are confined to `render_map.py` and its tests.

- At render time, read every `day-plan-*.md` in the route folder,
  convert each with the existing `markdown_to_html` (tables and lists are
  supported), and embed both HTML and raw Markdown in the page. No
  external file is needed to view the plans, so `map.html` is
  self-contained with respect to plan data and all planned dates.
- **Sidebar block "Day plan"**, placed after Points of interest and before
  Export (sidebar order becomes: title, route, getting there, points of
  interest, day plan, export). It contains a date selector when more than
  one plan exists (default: the nearest upcoming date, otherwise the
  latest), the plan's Summary section (found by heading aliases in seven
  languages), and an "Open full plan" button. With no plan files it shows
  the same placeholder style as the other blocks.
- **Full plan panel**: an overlay covering the page (also on phones) with
  the rendered plan, its fetched-at time, a "date has passed" marker for
  past dates, a "Download .md" button, a "Print / PDF" button, and close
  on Esc or the close button.
- **Download .md**: a `data:text/markdown` link with `download`
  attribute, filename `<route>-day-plan-<date>.md`, updated when the date
  selector changes (same mechanism as the GPX export).
- **PDF**: the button calls `window.print()`; `@media print` CSS hides the
  map, sidebar and buttons and prints only the plan (wrapping tables,
  avoiding page breaks inside rows). No dependencies.
- New `UI_STRINGS` keys for en/ru/es/fr/de/pt/it: block title, open full
  plan, download, print/PDF, no plan, forecast fetched, date passed.
- The generated content is escaped like GeoJSON (`</` inside inline
  script) and Markdown passes through the existing escaping in
  `_inline_markdown`.
- The map still loads Leaflet and tiles from the internet as before;
  plans and the sidebar work without a network, the base map does not.
- After writing a new plan, the day-plan skill offers to re-render
  `map.html` and states which dates it contains. A map is a snapshot: a
  plan added later does not appear until the map is re-rendered.

## Privacy

Plans record the departure point only at city, station or stop level,
never a street address, because the map file is meant to be forwarded.
If the person gives a precise address, it may be used for transit
recommendations in that session but is not written to disk.

## Data sources and keys

| Source | Key | Used by |
|---|---|---|
| Open-Meteo Forecast and Archive | none | weather, fire, bio_hazards, mountain |
| EAWS avalanche bulletins (CAAML v6) | none | mountain |
| Open-Meteo Air Quality | none | air |
| Overpass (OSM) | none | transit, poi_hours, air, cell_coverage, bio_hazards, mountain |
| EFFIS WMS (Copernicus) | none | fire |
| NASA FIRMS | optional `OSM_DAY_ROUTE_FIRMS_KEY` | fire |
| Web search / Claude in Chrome | n/a | facts.json sections |
| Static registries (radiation zones, fire-season notes) | n/a | radiation, fire |

## Testing

- Network providers are tested against recorded fixtures; tests never
  use the live network.
- Dedicated tests: NOAA sunrise/sunset against known dates and
  latitudes (including polar day/night edge cases), FWI against
  reference values, the `opening_hours` evaluator (including `PH` and
  unparseable input), registry intersection with a track, orchestrator
  survival when a plugin raises, `facts.json` merging, section-heading
  alias matching for the summary, `map.html` embedding of several plans,
  and the download/print markup.
- Archive validation (`archive_validate.py`) is extended to accept
  optional `day-plan-*.md` files without requiring them.

## Risks and limitations

- Forecasts change; the plan states when it was fetched, and the map
  flags plans whose date has passed.
- Pollen coverage ends near 45 E; Urals and Siberia get `no-data`.
- Cell-coverage and weak-signal estimates are terrain models, not
  measurements.
- Hazard sections that depend on web search are only as good as their
  sources; each item carries its source and tier, and an item without a
  source is omitted rather than asserted.
- The radiation registry is curated by hand and will be incomplete; the
  plan says "no registry entry" rather than "safe" when nothing matches.
- Yandex pollen, ISDM-Rosleskhoz and operator coverage maps are not
  accessible programmatically; they appear as links.
