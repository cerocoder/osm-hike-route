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


class LengthRequiredError(Exception):
    pass


def resolve_length_range(min_km=None, max_km=None, min_h=None, max_h=None) -> dict:
    """The range the route must fit. One given value is the maximum; its minimum is half of it (the planner sets
    it by itself, it does not ask). Nothing given, or a minimum without its maximum: LengthRequiredError (the
    planner then asks the user)."""
    if (min_km is not None and max_km is None) or (min_h is not None and max_h is None) \
            or (max_km is None and max_h is None):
        raise LengthRequiredError(
            "Не задана длина или время маршрута. Спросите пользователя: максимум (км или часы) "
            "и, если он хочет, минимум.")
    if min_km is None and max_km is not None:
        min_km = max_km / 2
    if min_h is None and max_h is not None:
        min_h = max_h / 2
    if (min_km is not None and min_km > max_km) or (min_h is not None and min_h > max_h):
        raise ValueError("Минимум длины или времени больше максимума.")
    return {"min_distance_km": min_km, "max_distance_km": max_km,
            "min_duration_hours": min_h, "max_duration_hours": max_h}


def build_weights(preset: dict, preference_overrides: dict | None = None,
                   max_distance_km: float | None = None,
                   max_duration_hours: float | None = None,
                   min_distance_km: float | None = None,
                   min_duration_hours: float | None = None) -> dict:
    weights = copy.deepcopy(preset)
    if preference_overrides:
        weights["preferences"].update(preference_overrides)
    weights["max_distance_km"] = max_distance_km
    weights["max_duration_hours"] = max_duration_hours
    weights["min_distance_km"] = min_distance_km
    weights["min_duration_hours"] = min_duration_hours
    return weights


def revise_weights(existing: dict, changes: dict) -> dict:
    revised = copy.deepcopy(existing)
    for key, value in changes.items():
        if key == "preferences" and isinstance(value, dict):
            revised["preferences"].update(value)
        else:
            revised[key] = value
    return revised


MAIN_ROADS = ("trunk", "primary")


def allow_main_roads(weights: dict) -> dict:
    """Weights that let the route use trunk and primary roads without cycle infrastructure, as a last resort
    (fallback ways cost `fallback_way_cost` times more). Call it only after the user agreed (TODO 12). It keeps the
    other fields, and the user's own additions to the lists."""
    allowed = copy.deepcopy(weights)
    for key in ("routable_highway", "fallback_highway"):
        allowed[key] = list(allowed.get(key) or [])
        allowed[key] += [h for h in MAIN_ROADS if h not in allowed[key]]
    allowed["exclude_highway_without_infra"] = [
        h for h in allowed.get("exclude_highway_without_infra") or [] if h not in MAIN_ROADS]
    allowed["main_roads_allowed"] = True
    return allowed


def allow_protected_zones(weights: dict) -> dict:
    """Weights that record the user's permission to cross nature reserves and protected areas (TODO 13). The planner
    then leaves those zones out of the restricted polygons (route_graph.split_protected). Military zones, private
    areas and fences stay closed. Call it only after the user agreed."""
    allowed = copy.deepcopy(weights)
    allowed["protected_zones_allowed"] = True
    return allowed
