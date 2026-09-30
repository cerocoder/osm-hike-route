"""facts.json: web-sourced material Claude gathered by searching and recorded
for the plan (spec, "Skill boundary"). Shape:

    {"<YYYY-MM-DD>" or "all": {"<plugin_id>": {
        "markdown": "...",                         # required unless day_type is given
        "sources": ["https://..."],                # required: an entry without a source is dropped
        "last_departure_local": "HH:MM",           # optional, transit: compared with the estimated return
        "first_departure_local": "HH:MM",          # optional, transit
        "warnings": [{"severity": "danger|caution|info", "text": "..."}],   # optional, reach the Summary
        "day_type": "holiday|weekend|workday"      # optional, plugin id "calendar": overrides the holiday source
    }}}

A date-specific entry wins over an "all" entry. Everything read back is
validated by normalize_entry: a malformed or source-less entry is ignored
(never shown), the rest of the file keeps working. The text ends up in
day-plan-<date>.md, a file meant to be forwarded: keep places at city,
station or stop level, never a street address or anything personal."""
import json
import re
from pathlib import Path

from .base import SEVERITIES

DAY_TYPES = ("holiday", "weekend", "workday")
_TIME = re.compile(r"^\d{1,2}:[0-5]\d$")
_HEADING = re.compile(r"^ {0,3}#{1,6} +(\S.*?)\s*$", re.MULTILINE)


def load_facts(route_dir) -> dict:
    path = Path(route_dir) / "facts.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_time(value) -> bool:
    return isinstance(value, str) and bool(_TIME.match(value)) and int(value.split(":")[0]) <= 29


def normalize_entry(entry) -> dict | None:
    """Validated copy of a facts entry, or None when it must not be used."""
    if not isinstance(entry, dict):
        return None
    sources = [s.strip() for s in (entry.get("sources") or []) if isinstance(s, str)
               and s.strip().lower().startswith(("http://", "https://"))] if isinstance(entry.get("sources"), list) else []
    if not sources:
        return None
    markdown = entry.get("markdown")
    markdown = markdown.strip() if isinstance(markdown, str) else ""
    markdown = _HEADING.sub(r"**\1**", markdown)      # fact text must never open a real section
    day_type = entry.get("day_type") if entry.get("day_type") in DAY_TYPES else None
    if not markdown and not day_type:
        return None
    clean = {"markdown": markdown, "sources": sources}
    if day_type:
        clean["day_type"] = day_type
    for key in ("last_departure_local", "first_departure_local"):
        if _valid_time(entry.get(key)):
            clean[key] = entry[key]
    warnings = []
    for item in entry.get("warnings") if isinstance(entry.get("warnings"), list) else []:
        if (isinstance(item, dict) and item.get("severity") in SEVERITIES
                and isinstance(item.get("text"), str) and item["text"].strip()):
            warnings.append({"severity": item["severity"], "text": " ".join(item["text"].split())})
    if warnings:
        clean["warnings"] = warnings
    return clean


def lookup(facts: dict, date_iso: str, plugin_id: str, allow_all: bool = True) -> dict | None:
    """The usable entry for this date and plugin: the dated one if it is valid,
    else the "all" one (unless allow_all is False), else None."""
    for scope in ((date_iso, "all") if allow_all else (date_iso,)):
        plugins = facts.get(scope)
        if not isinstance(plugins, dict):
            continue
        entry = normalize_entry(plugins.get(plugin_id))
        if entry is not None:
            return entry
    return None
