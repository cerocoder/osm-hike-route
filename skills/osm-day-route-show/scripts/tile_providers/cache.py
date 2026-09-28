"""tile_coverage.json — one cache file per route, separate from
place_info.json (different semantics: boolean coverage per provider per
point-set, not a per-provider/per-point result object). Mirrors
place_info/cache.py's incremental-write pattern: a slow/rate-limited
probe run that gets killed by an outer timeout must not lose probes it
already completed."""
import json
from pathlib import Path


def cache_key(provider_id: str, points: list[tuple[float, float]], url_template: str) -> str:
    """Includes the provider's tile URL template so that changing a
    provider's URL (e.g. fixing a broken hostname) naturally invalidates
    any stale cached entries for it, instead of leaving a wrong cached
    True/False around forever."""
    coords = ",".join(f"{round(lat, 5)}:{round(lon, 5)}" for lat, lon in sorted(points))
    return f"{provider_id}|{url_template}|{coords}"


def load_cache(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_entry(path: Path, cache: dict, key: str, covers: bool) -> None:
    cache[key] = covers
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
