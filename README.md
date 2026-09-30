# osm-hike-route

Plan a one-day walking or cycling route around a place you name, then see it on an interactive map — all by chatting with Claude Code.

Repository: <https://github.com/cerocoder/osm-hike-route>
(clone: `git clone https://github.com/cerocoder/osm-hike-route.git`)

## What it does

You describe the day you want ("a loop in Casa de Campo, mostly trees, no big roads, 15 km, start from a metro station"). Claude builds a route from OpenStreetMap data, shaped by your preferences rather than just "shortest path", and saves it in a folder you can reuse and tweak later. A second step turns that folder into a self-contained map page you open in your browser, with a GPX file you can load into Wikiloc or a Garmin device.

The project is a Claude Code plugin made of three skills: two that work as a pair (plan a route, show it), and a third that briefs you on a specific day for a saved route.

## Architecture at a glance

```
 your request ──▶ osm-day-route-planning ──▶ routes/<place>-<date>/ ──▶ osm-day-route-show ──▶ map.html + GPX
                  (builds the route)          route.geojson, notes.md,     (draws it, with
                                              weights.json, requests.md,    every day plan inside)
                                              day-plan-<date>.md  ▲
                                                                  │
                                      a date ──▶ osm-day-route-day-plan
                                                 (daylight, weather by hour)
```

| Skill | Purpose |
|---|---|
| `osm-day-route-planning` | Turns your request into a route and saves it in an archive folder. |
| `osm-day-route-show` | Renders a saved route as an interactive map page. Needs a route from the planning skill. |
| `osm-day-route-day-plan` | For a saved route and a date, writes a day plan: sunrise, sunset, daylight, hourly weather, how to get to the access points, and whether the lines and points of interest work that day. Needs a route from the planning skill. |

The archive folder is the hand-off between them, and it is also your history: every request you made is logged, so you can come back and say "swap that viewpoint for a café" instead of starting over.

## Skill: osm-day-route-planning

**Use it when** you want a one-day walk or bike route near a named place, with preferences, required stops, or a way to get to the start.

What you can ask for:
- **Mode:** walking, or cycling (relaxed "leisure" or fast "sport" style). Claude asks if you don't say.
- **Loop or point-to-point.** Claude suggests a loop by default and asks.
- **Terrain preferences:** avoid main roads, prefer forest, avoid open fields, avoid water, avoid steep climbs.
- **Required stops:** a shop, a drinking fountain, a museum, or anything you care about, including things OSM doesn't tag (a viewpoint, good radio reception, foraging).
- **An access point:** a station, bus stop, or car park to start from. Claude suggests how to get there from where you are.
- **A budget:** maximum distance and/or hours. Claude asks if you don't say.

What it does with that:
- Finds routable paths and the surrounding terrain from OpenStreetMap, and excludes closed areas (military zones, private land, nature reserves, locked gates). It tells you plainly if a point you asked for falls inside one.
- Weights the route by your preferences, respects one-way rules and bike-blocking barriers for cycling, and accounts for climbs using elevation data.
- Adds optional points of interest only while there is budget left, and lists any it skipped.
- Estimates duration and warns if the day may not fit in daylight.
- Labels every claim about a place by how sure it is: `tag-backed` (OSM says so), `web-sourced` (found online, unverified in person), `derived` (an estimate), `no-data` (nothing found). It does not invent answers.
- Checks the saved archive is complete before showing you the result.

Revising: refer to an existing route ("change the start point", "make it a bike route") and it updates the same folder rather than creating a new one.

Not for: live turn-by-turn navigation, multi-day treks, driving routes, ski touring.

## Skill: osm-day-route-day-plan

**Use it when** you have a saved route and know the day you will go: "what will the weather and daylight be on Saturday?"

What you get, as `day-plan-<YYYY-MM-DD>.md` in the route folder:
- **Summary:** the most important warnings first (thunderstorm, strong gusts, finish after sunset, fog, cold, heavy rain).
- **Daylight:** sunrise, sunset and day length, and how much daylight is left after the route's estimated finish (or the latest start that still finishes an hour before sunset).
- **Weather by hour:** temperature and feels-like, precipitation and its probability, cloud cover, visibility, **wind speed and the direction it blows from**, gusts, snow cover, and a plain-language sky description.
- **Getting there:** what kind of day it is (weekday, weekend, public holiday), the opening hours of your access points on that date, the bus / train / metro lines that stop there (from OpenStreetMap, which rarely has schedules), and — when Claude has looked them up on the web and recorded them with sources — timetables and directions from where you start. If the last departure home is before your estimated return, or the return point closes before it, the summary says so; both checks need a start time (`--start`) and a route duration.
- **Points of interest:** whether each one is open on that date (from its OpenStreetMap opening hours), your notes, and web-sourced opening days and special features when recorded.

Good to know:
- Forecasts reach about 15 days ahead. For a later date you get the average of that date over the last five years, clearly labelled as *not a forecast*. Dates older than a week use recorded weather; the last week uses model data.
- Ask for a plan for several dates: each gets its own file, and re-running a date overwrites only that date.
- The plan records where you start from only as a city or station, never a street address, because the file is embedded in `map.html`, which is meant to be forwarded.
- Everything that comes from the web rather than from OpenStreetMap is labelled *web-sourced* and carries its sources; a fact without a source is refused. For Russia and its neighbours, Claude checks the date against the official calendar, because the free holiday list is incomplete for Russia: it misses 8 January and the transferred days off (for example 9 March and 11 May 2026). The script reminds Claude to record such a date as a `calendar` fact (per date; `holiday` for any official day off including transferred ones, `workday` for working days including working Saturdays).
- Hazards (ticks, mosquitoes, mountains, air, radiation, fire) and mobile coverage are planned next.

## Skill: osm-day-route-show

**Use it when** you want to see a planned route in a browser.

What you get:
- **`map.html`**, one file, opens in any browser. Route line with direction arrows, and a marker for every point with a popup (name, type, confidence).
- **A side panel** on the right, always in the same order: title, route (mode, distance, elevation, time), how to get there, points of interest, day plan, export. Sections that come from your `notes.md` show "not in notes.md" if the notes have no matching heading. Use headings such as `## How to get there` and `## Points of interest`.
- **A layer switcher** at the top left to change the base map. Esri Street and Esri Satellite are always offered. CyclOSM (cycling) and IGN España (Spanish topographic maps) appear only where they have coverage for your route.
- **Day plan:** if the route folder has `day-plan-<date>.md` files, every one is embedded in the page. The side panel shows a date picker and the plan's summary; "Open full plan" shows the whole plan (with the hourly weather table), and you can download it as `.md` or print it / save it as PDF from your browser. Because everything is inside the one HTML file, you can send `map.html` to someone and they get all planned days. Re-render the map after adding a new date.
- **Export:** a GPX download (with elevation), plus links to open the area in Google Maps and OpenStreetMap.
- **Place info:** links to Wikipedia, Wikidata, Wikimedia Commons and, optionally, OpenTripMap for each point.
- **Your language:** the page's own labels follow the language you write in (English, Russian, Spanish, French, German, Portuguese, Italian). Place names stay as they are on the map.

Two ways to get the map: as a local file you open yourself (`local`), or published as a Claude Artifact (`claude`). Claude asks which one you want.

## What must be installed on your machine

- **Claude Code**, with the plugin loaded (see below).
- **Python 3.10 or newer.** The skills use only Python's standard library, so there is nothing to `pip install`.
- **An internet connection.** Routes and maps are built from live services: OpenStreetMap (Overpass API), several public elevation services, Wikipedia/Wikidata/Wikimedia Commons, and map tile servers. The map page loads Leaflet and the map tiles from the internet when you open it.
- **A web browser** to open `map.html`.
- **Optional:** a free [OpenTripMap](https://opentripmap.io) API key, exposed as the `OSM_DAY_ROUTE_OPENTRIPMAP_KEY` environment variable. Without it that one source is simply skipped.
- **Optional:** the Claude in Chrome extension, used only if you explicitly ask Claude to look something up in the browser.
- **Only for development:** `pytest`, to run the tests.

Install the plugin by cloning the repository and pointing Claude Code at it:

```bash
git clone https://github.com/cerocoder/osm-hike-route.git
claude --plugin-dir ./osm-hike-route
```

## Where your routes are saved

Each route gets its own folder, `routes/<place>-<date>/`:

| File | What it is |
|---|---|
| `route.geojson` | The route and all points, with distance, elevation and duration. |
| `notes.md` | Human-readable summary: how to get there, points of interest, caveats. |
| `weights.json` | Your preferences and budget as they were used. |
| `requests.md` | Every request you made for this route, in order. |
| `day-plan-<YYYY-MM-DD>.md` | A day plan for one date (daylight, hourly weather, transport, opening hours). One file per planned date. |
| `facts.json` | Web-sourced facts Claude recorded for your day plans (timetables, directions, opening days), each with its sources. |
| `map.html` | The rendered map (after the show step); contains every day plan. |

## Usage examples

The examples use Casa de Campo, the large park in Madrid.

**1. Plan a loop**
> Plan me a one-day walk in Casa de Campo, Madrid. I'm coming from central Madrid by metro. I want a loop of about 15 km, mostly through trees, staying away from the big roads.

Claude will ask whether you want walking or cycling and confirm the loop if you haven't said, then suggest metro or bus stops as the starting point.

**2. Add required stops and a time limit**
> Walk in Casa de Campo, loop, 5 hours max. It must pass a drinking fountain and a good viewpoint over the city, and I'd like to finish near a café.

Stops OSM doesn't tag (like "a good viewpoint") are searched for online and labelled `web-sourced`, so you know they're unverified.

**3. A bike route**
> Leisure bike ride in Casa de Campo, about 25 km, avoid roads without a bike lane, start from the Lago metro station.

**4. Revise an existing route**
> In the Casa de Campo route, drop the second viewpoint and end at a different station.

Claude updates the same folder and keeps the history in `requests.md`.

**5. Show it on a map**
> Show the Casa de Campo route on a map, as a local file.

Claude generates `map.html`, gives you the path and a clickable link, and you open it in your browser. To publish it as a Claude Artifact instead, say "publish it as an artifact". For a Spanish-language page, write to Claude in Spanish.

**6. Force a base map**
> Show it with the satellite layer active.

You can also switch layers yourself at any time with the button at the top left of the map.

## License

See [LICENSE](LICENSE).
