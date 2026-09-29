---
name: osm-day-route-day-plan
description: Use when the user wants a briefing for a specific date for a route already saved by osm-day-route-planning (a routes/<slug>-<date>/ folder with route.geojson) — sunrise/sunset and daylight, hourly weather (wind speed and direction, precipitation, temperature, cloud/fog, snow cover) — or asks "what will the weather/daylight be on <date>", "план на день", "когда рассвет и закат", "погода по часам".
---

# OSM Day Route Day Plan

## Overview

Turns a saved route plus a date into `day-plan-<YYYY-MM-DD>.md` in the route
folder. `osm-day-route-show` embeds every such file into `map.html` (sidebar
summary, full-plan panel, `.md` download, print to PDF), so the single map
file can be forwarded with all planned days inside.

Design: `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`.
This skill currently implements the **light** (sunrise, sunset, day length,
margin to the route's finish) and **weather** (hourly) sections and the
**summary**. Transit and opening hours, hazards (ticks, biting insects,
mountains, air, radiation, fire) and mobile coverage are separate follow-up
plans; until they exist the plan simply has no such sections — never invent
them by hand.

Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
keys, same rule as the other two skills.

## When to Use

- A route exists in `routes/` and the user names a date (or asks about
  "tomorrow", "Saturday" — convert to `YYYY-MM-DD` first).
- The user asks for sunrise/sunset, day length, or hourly weather for a route.

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
3. Optional `--start HH:MM` if the person gave a start time; otherwise the
   plan reports the latest start that still ends 60 minutes before sunset.
4. Run (from this skill's `scripts/` directory):
   ```bash
   python3 build_day_plan.py <route_dir> <YYYY-MM-DD> \
       --lang <ISO 639-1 of the person's language> \
       [--departure "<city or station>"] [--start HH:MM]
   ```
   Re-running for the same date overwrites that date's file; other dates are
   kept. Network results are cached in `<route_dir>/day_plan_cache.json`
   (forecasts for 3 hours).
5. Report the file path and read the **Summary** section back to the person.
   If the plan shows the route does not fit the day (finish after sunset,
   thunderstorm), say so and offer to go back to osm-day-route-planning —
   this skill never changes the route.
6. Offer to re-render the map so the new date is inside it:
   `python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang <code>`.
   A `map.html` is a snapshot; a plan added later does not appear until it is
   re-rendered. Tell the person which dates the map will contain.

## Confidence and honesty

Sections carry a tier like the rest of the project: light and weather are
`derived` (computed / model output). A forecast is only as good as its
horizon: beyond 15 days the weather table is a **climatology** (average of
the same date over five previous years) and says so in the file. A section
that could not be built says `no data` — report that plainly.

## Limitations

- Body text of the light/weather sections is translated for English and
  Russian; other languages get English body text (headings, metadata and
  severity labels are localized in all seven languages).
- Open-Meteo applies no elevation correction to wind: ridge gusts are likely
  underestimated.
- Pollen, radiation, fire danger, insects, mountain hazards, transit and
  mobile coverage are not in this version.

## Common Mistakes

- Writing a street address as the departure point (it ends up in a forwarded file).
- Editing `day-plan-*.md` by hand and forgetting that re-running the script
  overwrites the file.
- Forgetting to re-render `map.html` after adding a plan.
