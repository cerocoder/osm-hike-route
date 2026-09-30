#!/usr/bin/env python3
"""Record one web-sourced fact for a day plan in <route_dir>/facts.json.

Standard-library only. Usage:
    python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar>
        (--markdown TEXT | --markdown-file PATH) --source URL [--source URL ...]
        [--last-departure HH:MM] [--first-departure HH:MM]
        [--warning danger|caution|info:TEXT ...] [--day-type holiday|weekend|workday]

Every fact needs at least one http(s) source: an entry without one is refused
(and would be ignored when the plan is built). The text ends up in
day-plan-<date>.md, which is embedded in map.html and meant to be forwarded:
write places at city, station or stop level, never a street address, phone
number or anything personal. The file is replaced atomically; a facts.json
that is not valid JSON is never overwritten."""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from day_plan.base import SEVERITIES
from day_plan.facts import DAY_TYPES, normalize_entry

PLUGINS = ("transit", "poi_hours", "calendar", "fire", "mountain", "bio_hazards", "air")
WARNING_PLUGINS = ("transit", "poi_hours", "fire", "mountain", "bio_hazards", "air")


def record(route_dir, date: str, plugin: str, markdown: str, sources: list, last_departure: str | None = None,
           first_departure: str | None = None, warnings: list | None = None, day_type: str | None = None) -> dict:
    """Validates and stores the fact; returns the stored entry. Raises ValueError with a readable reason,
    or OSError when the file cannot be written."""
    if plugin not in PLUGINS:
        raise ValueError(f"unknown plugin {plugin!r} (use one of: {', '.join(PLUGINS)})")
    if date != "all":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise ValueError(f"bad date {date!r}: use YYYY-MM-DD or 'all'")
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ValueError(f"bad date {date!r}: use YYYY-MM-DD or 'all'") from None
    if plugin == "calendar" and date == "all":
        raise ValueError("a calendar fact needs a specific date (--date YYYY-MM-DD), not 'all'")
    for option, value, uses in (("--day-type", day_type, ("calendar",)),
                                ("--last-departure", last_departure, ("transit",)),
                                ("--first-departure", first_departure, ("transit",)),
                                ("--warning", warnings, WARNING_PLUGINS)):
        if value and plugin not in uses:
            raise ValueError(f"the {plugin} plugin does not use {option} (only: {', '.join(uses)})")
    entry = {"markdown": markdown, "sources": sources}
    for key, value in (("last_departure_local", last_departure), ("first_departure_local", first_departure),
                       ("day_type", day_type)):
        if value is not None:
            entry[key] = value
    if warnings:
        entry["warnings"] = warnings
    clean = normalize_entry(entry)
    if clean is None:
        raise ValueError("refused: a fact needs a non-empty text (or --day-type) and at least one http(s) --source")
    for key in ("last_departure_local", "first_departure_local"):
        if key in entry and key not in clean:
            raise ValueError(f"bad {key}: use HH:MM")
    if day_type is not None and "day_type" not in clean:
        raise ValueError(f"bad day type {day_type!r}: use one of {', '.join(DAY_TYPES)}")
    if warnings and len(clean.get("warnings", [])) != len(warnings):
        raise ValueError("bad warning: use severity:text with severity one of " + ", ".join(SEVERITIES))

    path = Path(route_dir) / "facts.json"
    facts = {}
    if path.exists():
        try:
            facts = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix or remove it first — it was not changed") from None
        if not isinstance(facts, dict):
            raise ValueError(f"{path} does not hold a JSON object; fix or remove it first — it was not changed")
    scope = facts.get(date)
    if not isinstance(scope, dict):
        scope = facts[date] = {}
    scope[plugin] = clean
    fd, tmp = tempfile.mkstemp(dir=str(Path(route_dir)), prefix=".facts-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(facts, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return clean


def _parse_warning(text: str) -> dict:
    severity, _, body = text.partition(":")
    return {"severity": severity.strip(), "text": body.strip()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("route_dir")
    parser.add_argument("--date", required=True)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--markdown", default=None)
    parser.add_argument("--markdown-file", default=None)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--last-departure", default=None)
    parser.add_argument("--first-departure", default=None)
    parser.add_argument("--warning", action="append", default=[])
    parser.add_argument("--day-type", default=None)
    args = parser.parse_args(argv)
    if not Path(args.route_dir).is_dir():
        print(f"error: {args.route_dir} is not a directory", file=sys.stderr)
        return 1
    if args.markdown is not None and args.markdown_file is not None:
        print("error: use --markdown or --markdown-file, not both", file=sys.stderr)
        return 1
    try:
        markdown = args.markdown if args.markdown is not None else (
            Path(args.markdown_file).read_text(encoding="utf-8") if args.markdown_file else "")
        record(args.route_dir, args.date, args.plugin, markdown, args.source, args.last_departure,
               args.first_departure, [_parse_warning(w) for w in args.warning], args.day_type)
    except (ValueError, OSError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"recorded {args.plugin} for {args.date} ({len(args.source)} source(s)) in "
          f"{Path(args.route_dir).resolve() / 'facts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
