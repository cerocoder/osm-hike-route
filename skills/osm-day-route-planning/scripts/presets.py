"""Loads read-only routing presets shipped with the skill. See spec
§3.6 — presets carry routing tag rules AND weights, not just weights,
so a new mode (e.g. a future ski preset) needs no code changes here."""
import copy
import json
from pathlib import Path

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"


class PresetNotFoundError(Exception):
    pass


def load_preset(mode: str, style: str | None = None) -> dict:
    filename = f"{mode}-{style}.json" if style else f"{mode}.json"
    path = PRESETS_DIR / filename
    if not path.exists():
        raise PresetNotFoundError(f"no preset for mode={mode!r} style={style!r} (looked for {path})")
    return json.loads(path.read_text(encoding="utf-8"))


def build_weights(preset: dict, preference_overrides: dict | None = None,
                   max_distance_km: float | None = None,
                   max_duration_hours: float | None = None) -> dict:
    weights = copy.deepcopy(preset)
    if preference_overrides:
        weights["preferences"].update(preference_overrides)
    weights["max_distance_km"] = max_distance_km
    weights["max_duration_hours"] = max_duration_hours
    return weights
