"""Shared, cross-route elevation cache (spec §3.8: routes/.cache/elevation.json,
NOT per-route — elevation is fetched before a route folder exists, and one
area is reused across routes). Written after every successful batch, not
just at the end, so a killed run doesn't lose already-resolved points."""
import json
from pathlib import Path


def cache_key(lat: float, lon: float, dataset: str) -> str:
    return f"{round(lat, 4)}|{round(lon, 4)}|{dataset}"


def load_cache(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def update_entry(cache: dict, key: str, lat: float, lon: float, elevation: float,
                  provider_id: str, dataset: str) -> None:
    """Mutates cache in memory only — does not touch disk. Pair with
    write_cache() to persist several updates in one write instead of
    rewriting the whole file once per entry."""
    cache[key] = {
        "lat": lat, "lon": lon, "elevation": elevation,
        "provider_id": provider_id, "dataset": dataset,
    }


def write_cache(path: Path, cache: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def save_entry(path: Path, cache: dict, key: str, lat: float, lon: float,
               elevation: float, provider_id: str, dataset: str) -> None:
    """Single-entry convenience: update + immediate write. In a loop over
    many points, prefer update_entry() per point plus one write_cache()
    call per batch instead — see ElevationService.get_elevations, and
    spec §3.8 ('written after every successful batch, not every point')."""
    update_entry(cache, key, lat, lon, elevation, provider_id, dataset)
    write_cache(path, cache)
