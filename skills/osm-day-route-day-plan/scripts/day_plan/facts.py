"""facts.json: web-sourced material Claude gathered by searching and
recorded for the plan (spec, "Skill boundary"). Shape:

    {"<YYYY-MM-DD>" or "all": {"<plugin_id>": {
        "markdown": "...", "confidence": "web-sourced",
        "sources": ["https://..."]}}}

A date-specific entry wins over an "all" entry."""
import json
from pathlib import Path


def load_facts(route_dir) -> dict:
    path = Path(route_dir) / "facts.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def lookup(facts: dict, date_iso: str, plugin_id: str) -> dict | None:
    for scope in (date_iso, "all"):
        plugins = facts.get(scope)
        if not isinstance(plugins, dict):
            continue
        entry = plugins.get(plugin_id)
        if isinstance(entry, dict) and entry.get("markdown"):
            return entry
    return None
