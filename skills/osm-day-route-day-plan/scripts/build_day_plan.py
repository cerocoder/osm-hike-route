#!/usr/bin/env python3
"""Build day-plan-<YYYY-MM-DD>.md for a saved route.

Standard-library only. Usage:
    python3 build_day_plan.py <route_dir> <YYYY-MM-DD>
        [--lang <ISO 639-1>] [--departure "<city or station>"] [--start HH:MM]

--departure is written into the file, and the file is meant to be forwarded
(it is embedded in map.html), so pass a city, station or stop — never a street
address. A value containing digits is treated as a possible address and is
NOT written.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

from day_plan import calendar_info
from day_plan.context import build_context
from day_plan.facts import lookup
from day_plan.http import get_json, get_text
from day_plan.osm_features import OsmFeaturesPlugin
from day_plan.plugins.air import AirPlugin
from day_plan.plugins.bio_hazards import BioHazardsPlugin, TICK_MONTHS, in_season
from day_plan.plugins.cell_coverage import CellCoveragePlugin
from day_plan.plugins.fire import FirePlugin
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.mountain import (
    MOUNTAIN_MIN_ELEVATION_M, MOUNTAIN_MIN_RELIEF_M, MountainPlugin, elevation_stats,
)
from day_plan.plugins.people_hazards import PeopleHazardsPlugin
from day_plan.plugins.poi_hours import PoiHoursPlugin
from day_plan.plugins.radiation import RadiationPlugin
from day_plan.plugins.snow_history import SnowHistoryPlugin
from day_plan.plugins.trail_passability import TrailPassabilityPlugin
from day_plan.plugins.transit import TransitPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import build_plan


def default_plugins() -> list:
    # the order inside the Hazards group is the registration order: radiation first, it matters most, then the
    # passability of trails and roads
    return [WeatherPlugin(), LightPlugin(), OsmFeaturesPlugin(), RadiationPlugin(), SnowHistoryPlugin(),
            TrailPassabilityPlugin(), TransitPlugin(), PoiHoursPlugin(), MountainPlugin(), FirePlugin(),
            BioHazardsPlugin(), AirPlugin(), PeopleHazardsPlugin(), CellCoveragePlugin()]


def missing_web_facts(ctx) -> list:
    """Plugin ids whose web-sourced facts Claude has not recorded yet for this date."""
    wanted = ["transit"] + (["poi_hours"] if ctx.interest_points else [])
    missing = [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]
    if calendar_info.country_code(ctx) == "RU":
        fact = lookup(ctx.facts, ctx.date_iso, "calendar", allow_all=False)
        if not (fact and fact.get("day_type")):
            missing.append("calendar")
    return missing


def optional_hazard_facts(ctx, result=None) -> list:
    """Hazard plugins whose regional web facts would improve this plan and are not recorded yet: fire
    restrictions always, mountain notes for mountain routes, insect/animal notes in the tick season, and reports of
    the current season on trails and roads when the passability section applies (`result` is the built plan)."""
    wanted = ["fire"]
    stats = elevation_stats(ctx.coords)
    if stats and (stats[1] >= MOUNTAIN_MIN_ELEVATION_M or stats[2] >= MOUNTAIN_MIN_RELIEF_M):
        wanted.append("mountain")
    if in_season(ctx.date.month, TICK_MONTHS, ctx.centroid[0]):
        wanted.append("bio_hazards")
    if result is not None and any(s.shared.get("trail_applies") for s in result.sections):
        wanted.append("trail_conditions")
    wanted.append("people_hazards")
    return [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]


def coarse_departure(text: str | None) -> tuple[str | None, bool]:
    """(value_to_write, was_dropped). Digits suggest a street address."""
    if not text:
        return None, False
    if re.search(r"\d", text):
        return None, True
    return text.strip(), False


def main(argv=None, http=get_json, now=None, plugins=None, http_text=get_text) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route_dir")
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--departure", default=None)
    parser.add_argument("--start", default=None, help="planned start time HH:MM")
    args = parser.parse_args(argv)

    route_dir = Path(args.route_dir)
    if not (route_dir / "route.geojson").exists():
        print(f"error: {route_dir / 'route.geojson'} not found", file=sys.stderr)
        return 1
    try:
        date = datetime.date.fromisoformat(args.date)
        start = datetime.time.fromisoformat(args.start) if args.start else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    departure, dropped = coarse_departure(args.departure)
    if dropped:
        print("warning: --departure looks like a street address (contains digits); it was NOT "
              "written to the plan. Pass a city, station or stop.", file=sys.stderr)

    ctx = build_context(route_dir, date, lang=args.lang, departure=departure, start_time=start,
                        http=http, http_text=http_text, now=now)
    result = build_plan(ctx, plugins if plugins is not None else default_plugins())
    out = route_dir / f"day-plan-{date.isoformat()}.md"
    out.write_text(result.markdown, encoding="utf-8")
    print(f"wrote {out.resolve()}")
    for plugin_id, reason in result.failures:
        print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
    try:
        missing = missing_web_facts(ctx)
    except Exception:  # noqa: BLE001 — a hint must never turn a written plan into a failure
        missing = []
    if missing:
        print(f"hint: no web-sourced facts recorded for {', '.join(missing)} on {date.isoformat()}: search the "
              f"web (timetables, directions from the departure point, opening days), record what you find with "
              f"record_fact.py, then run this command again"
              + (". calendar: check in the official calendar whether the date is a public holiday, a "
                 "transferred day off or a working Saturday, and record it with --plugin calendar "
                 "--day-type ..." if "calendar" in missing else ""))
    try:
        optional = optional_hazard_facts(ctx, result)
    except Exception:  # noqa: BLE001 — a hint must never turn a written plan into a failure
        optional = []
    if optional:
        print(f"hint (optional): regional facts would improve the hazard sections: {', '.join(optional)} — "
              f"fire: forest-access and open-fire restrictions; mountain: avalanche bulletin, closed huts or passes; "
              f"bio_hazards: insect season and peaks, animals (bears, snakes, boar) and hunting; trail_conditions: "
              f"reports of the current season (forums, clubs, park administrations) on snow clearing, grooming, ice "
              f"and closed sections; people_hazards: official travel advisories, permit or border-zone rules and "
              f"access restrictions; record them with record_fact.py --plugin <name>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
