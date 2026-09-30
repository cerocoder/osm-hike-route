---
name: osm-day-route-day-plan
description: Use when the user wants a briefing for a specific date for a route already saved by osm-day-route-planning (a routes/<slug>-<date>/ folder with route.geojson) — sunrise/sunset and daylight, hourly weather (wind speed and direction, precipitation, temperature, cloud/fog, snow cover), how to get to the access points and whether the buses/metro run and the points of interest are open on that date (weekday, weekend, public holiday) — or asks "what will the weather/daylight be on <date>", "до скольки ходит автобус", "открыт ли музей", "план на день", "когда рассвет и закат", "погода по часам".
---

# OSM Day Route Day Plan

## Overview

Turns a saved route plus a date into `day-plan-<YYYY-MM-DD>.md` in the route
folder. `osm-day-route-show` embeds every such file into `map.html` (sidebar
summary, full-plan panel, `.md` download, print to PDF), so the single map
file can be forwarded with all planned days inside.

Design: `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`.
The plan has these sections, always in this order:

1. **Summary** — the highest-severity warnings of every section.
2. **Daylight** — sunrise, sunset, day length, margin to the route's finish.
3. **Weather by hour** — Open-Meteo, with wind speed, direction and gusts.
4. **Getting there** — the kind of day (weekday / weekend / public holiday),
   the access points and their OSM hours on the date, the public-transport
   lines serving them (OSM), and — from `facts.json` — timetables and
   directions from the departure point.
5. **Points of interest** — open or closed on the date (OSM hours), notes
   from the route archive, and — from `facts.json` — opening days and special
   features.

Hazards (ticks, biting insects, mountains, air, radiation, fire) and mobile
coverage are separate follow-up plans; until they exist the plan simply has
no such sections — never invent them by hand.

Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
keys, same rule as the other two skills. Sources: Open-Meteo (weather),
Overpass (lines through the access points; mirrors and one retry, because the
public servers answer 429/504 under load), Nominatim (the route's country,
asked once per route and remembered) and Nager.Date (public holidays).

## When to Use

- A route exists in `routes/` and the user names a date (or asks about
  "tomorrow", "Saturday" — convert to `YYYY-MM-DD` first).
- The user asks for sunrise/sunset, day length, hourly weather, how to reach
  the start, whether the last bus/metro fits the return, or whether a point of
  interest is open.

**Not for:** planning or changing the route (osm-day-route-planning),
showing it on a map (osm-day-route-show), astronomical events (not covered),
live navigation, multi-day plans.

## How to Use

1. Find the route folder and the date. Ask if either is unclear.
2. **Departure point:** ask only if it is not already in the conversation or
   the route's `notes.md`. Write it at **city / station / stop level** — the
   plan is embedded in `map.html`, a file meant to be forwarded, so never a
   street address. The script drops any `--departure` containing digits and
   says so on stderr.
3. Optional `--start HH:MM` if the person gave a start time; without it the
   plan reports the latest start that still ends 60 minutes before sunset, and
   no return-time checks against buses or opening hours are made (they need
   the estimated finish).
4. Run (from this skill's `scripts/` directory):
   ```bash
   python3 build_day_plan.py <route_dir> <YYYY-MM-DD> \
       --lang <ISO 639-1 of the person's language> \
       [--departure "<city or station>"] [--start HH:MM]
   ```
   Re-running for the same date overwrites that date's file; other dates are
   kept. Network results are cached in `<route_dir>/day_plan_cache.json`
   (forecasts 3 hours, Overpass lines 7 days, holiday lists 30 days, the
   route's country for good).
5. **Web facts.** The script ends with a `hint:` line for every section that
   has no web-sourced facts for the date. Then search the web for what OSM
   cannot tell (see **Recording facts** below), record each finding with
   `record_fact.py`, and run step 4 again. Skip only what the person did not
   ask about; a section without facts says so plainly, which is honest.
6. Report the file path and read the **Summary** section back to the person.
   If the plan shows the route does not fit the day (finish after sunset,
   thunderstorm, last bus before the return, a point closed), say so and offer
   to go back to osm-day-route-planning — this skill never changes the route.
7. Offer to re-render the map so the new date is inside it:
   `python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang <code>`.
   A `map.html` is a snapshot; a plan added later does not appear until it is
   re-rendered. Tell the person which dates the map will contain.

## Recording facts

Web-sourced material goes into `<route_dir>/facts.json` through the helper —
never by hand-editing JSON:

```bash
python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar> \
    --markdown "text" | --markdown-file note.md \
    --source https://... [--source https://...] \
    [--last-departure HH:MM] [--first-departure HH:MM] \
    [--warning caution:"text"] [--day-type holiday|weekend|workday]
```

`--last-departure`, `--first-departure` and `--warning` belong to `transit`
(`--warning` also to `poi_hours`); `--day-type` belongs to `calendar`. The
helper refuses an option the plugin would ignore.

- `--plugin transit`: timetables and **directions from the departure point**
  (which train/metro/bus, how long, where to change), frequencies on that
  weekday/holiday. `--last-departure` is the last bus/train/metro *back from
  the route's end point*, as local `HH:MM` (a departure after midnight, like
  `00:20`, is read as the night after the date): the plan compares it with the
  estimated return and warns (danger if the return is later, caution if the
  margin is under 30 minutes). The same return check, and the warning that the
  return point closes before the return, need `--start` and a route duration
  (`duration_estimate_hours` in the route file); without them nothing is
  compared. `--first-departure` is stored but not compared. Use `--warning
  severity:text` (`danger|caution|info`) for anything the person must see in
  the Summary (works, replacement buses, closed stations).
- `--plugin poi_hours`: opening days and special features of the points of
  interest for that date (closed for an event, free days, reservations).
- `--plugin calendar` with `--day-type` (`--markdown` is optional then): the
  real kind of day when the free holiday list is wrong. A calendar fact needs
  a specific date. `holiday` is any official day off, transferred ones
  included; `workday` is a working day, working Saturdays included; `weekend`
  only marks Saturday/Sunday and leaves the public-holiday rule undecided.
  **For Russia and neighbouring countries always check the date** (official
  calendar, `consultant.ru` or similar): the free list is incomplete for
  Russia: it misses 8 January and the transferred days off (for example
  9 March and 11 May 2026), and working Saturdays are not marked. For a
  Russian route the script's `hint:` line asks for this fact until one is
  recorded for the date. It overrides the list and feeds the opening-hours
  rules (`PH`).
- Every fact needs at least one `http(s)` source, or it is refused (and, if
  found in the file, ignored). Say only what the source says.
- **Privacy:** facts end up in `day-plan-<date>.md`, embedded in a `map.html`
  meant to be forwarded. Places at city, station or stop level only — never a
  street address, phone number or anything personal.
- `--date all` applies to every date without a dated entry; a dated entry wins.
  It does not apply to `calendar` facts: those need a specific date and
  `record_fact.py` refuses `--plugin calendar --date all`.

## Confidence and honesty

Sections carry a tier like the rest of the project. Light and weather are
`derived` (computed / model output). Hours and lines taken from OSM are
`tag-backed`; anything from `facts.json` is `web-sourced` (unverified in
person) and is labelled as such in the text, with its sources. A section that
could not be built says `no data`. OSM rarely carries schedules: lines through
a stop usually have no `interval` or `opening_hours`, so expect "not stated in
OSM" and rely on recorded web facts for timetables. If Overpass fails for
some access points only, the lines table is followed by the note "Lines for
some access points could not be loaded"; run the command again later.

A forecast is only as good as its horizon: beyond 15 days the weather table is
a **climatology** (average of the same date over five previous years) and says
so in the file.

`opening_hours` is read for the syntax real data uses (weekday lists and
ranges, several time ranges, overnight ranges, `24:00`, `19:30+`, `off`,
`24/7`, `PH`, months, `sunrise`/`sunset`). Anything else (`SH`, `week`,
point dates like `Jan 01`, quoted comments) is shown verbatim as "not read" —
never guessed. Public-holiday rules (`PH`) are marked "depends on the
public-holiday rule" when the holiday status is unknown.

## Limitations

- Body text of the sections is translated for English and Russian; other
  languages get English body text (headings, metadata and severity labels are
  localized in all seven languages).
- Open-Meteo applies no elevation correction to wind: ridge gusts are likely
  underestimated.
- Weekends are Saturday and Sunday; countries with another weekend are not
  handled.
- Pollen, radiation, fire danger, insects, mountain hazards and mobile
  coverage are not in this version.

## Common Mistakes

- Writing a street address as the departure point or in a fact (it ends up in
  a forwarded file).
- Trusting the holiday list for Russia without checking the date.
- Recording a fact without reading its source, or a last departure for the
  wrong direction (it must be the departure *back* from the end point).
- Editing `day-plan-*.md` by hand and forgetting that re-running the script
  overwrites the file.
- Editing `facts.json` by hand (use `record_fact.py`: it validates, refuses
  source-less facts and never overwrites a file it cannot parse).
- Forgetting to re-render `map.html` after adding a plan.
