# skills/osm-day-route-show/scripts/place_info/cache.py
"""One shared place_info.json per route (spec §5) — used by every plugin,
for both interest points and access points. Written immediately on each
new result, same incremental-write reasoning as wiki_links.json before it."""
import json
from dataclasses import asdict
from pathlib import Path


def cache_key(provider_id: str, identity: str, lat: float, lon: float) -> str:
    return f"{provider_id}|{identity}|{round(lat, 5)}|{round(lon, 5)}"


def load_cache(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_entry(path: Path, cache: dict, key: str, result_dict: dict) -> None:
    cache[key] = result_dict
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
