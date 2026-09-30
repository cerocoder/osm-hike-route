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
from day_plan.http import get_json
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.poi_hours import PoiHoursPlugin
from day_plan.plugins.transit import TransitPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import build_plan


def default_plugins() -> list:
    return [WeatherPlugin(), LightPlugin(), TransitPlugin(), PoiHoursPlugin()]


def missing_web_facts(ctx) -> list:
    """Plugin ids whose web-sourced facts Claude has not recorded yet for this date."""
    wanted = ["transit"] + (["poi_hours"] if ctx.interest_points else [])
    missing = [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]
    if calendar_info.country_code(ctx) == "RU":
        fact = lookup(ctx.facts, ctx.date_iso, "calendar", allow_all=False)
        if not (fact and fact.get("day_type")):
            missing.append("calendar")
    return missing


def coarse_departure(text: str | None) -> tuple[str | None, bool]:
    """(value_to_write, was_dropped). Digits suggest a street address."""
    if not text:
        return None, False
    if re.search(r"\d", text):
        return None, True
    return text.strip(), False


def main(argv=None, http=get_json, now=None, plugins=None) -> int:
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
                        http=http, now=now)
    result = build_plan(ctx, plugins if plugins is not None else default_plugins())
    out = route_dir / f"day-plan-{date.isoformat()}.md"
    out.write_text(result.markdown, encoding="utf-8")
    print(f"wrote {out.resolve()}")
    for plugin_id, reason in result.failures:
        print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
    missing = missing_web_facts(ctx)
    if missing:
        print(f"hint: no web-sourced facts recorded for {', '.join(missing)} on {date.isoformat()}: search the "
              f"web (timetables, directions from the departure point, opening days), record what you find with "
              f"record_fact.py, then run this command again"
              + (". calendar: check in the official calendar whether the date is a public holiday, a "
                 "transferred day off or a working Saturday, and record it with --plugin calendar "
                 "--day-type ..." if "calendar" in missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
