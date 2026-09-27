"""Loads read-only routing presets shipped with the skill. See spec
§3.6 — presets carry routing tag rules AND weights, not just weights,
so a new mode (e.g. a future ski preset) needs no code changes here."""
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
