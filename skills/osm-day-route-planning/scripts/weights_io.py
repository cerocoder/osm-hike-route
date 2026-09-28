"""Persists a route's weights.json — the merged preset+overrides+budget
that produced it (spec §3.6/§3.11: inputs live here, not in route.geojson)."""
import json
from pathlib import Path


def save_weights(route_dir: Path, weights: dict) -> None:
    route_dir = Path(route_dir)
    route_dir.mkdir(parents=True, exist_ok=True)
    (route_dir / "weights.json").write_text(
        json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_weights(route_dir: Path) -> dict | None:
    path = Path(route_dir) / "weights.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
