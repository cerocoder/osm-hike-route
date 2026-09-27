# osm-day-route-planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `osm-day-route-planning` skill — a preference-weighted, multi-mode (walk/bike), rельеф-aware one-day route planner with a budget-constrained waypoint selector, a plugin-based elevation module, and iteration support.

**Architecture:** Port the existing `route_graph.py`/`overpass_query.py` from `init-raw-source/osm-hike-route-planning` into `skills/osm-day-route-planning/scripts/`, then extend them: a directed, gradient-aware graph driven by JSON presets (not hardcoded tags/weights), a standalone `elevation/` plugin package with automatic failover across four HTTP providers, and small single-purpose modules for presets, weights persistence, the request log, restricted-zone/budget waypoint selection, and duration estimation. `osm-day-route-show` (separate plan) consumes this skill's `route.geojson` output — this plan does not touch `show`.

**Tech Stack:** Python 3.10+, standard library only at runtime (`urllib.request`, `json`, `heapq`, `math`, `pathlib`) — no `requests`, no `pyyaml`. Tests use `pytest` (dev-only) with `unittest.mock` for HTTP calls; no live network access in the automated suite.

**Spec:** `docs/superpowers/specs/2026-09-28-osm-day-route-planning-show-design.md`

## Global Constraints

- Zero external runtime dependencies — stdlib only, including `urllib.request` instead of `requests` (spec §3.6, matches existing `overpass_query.py`/`route_graph.py`).
- `weights.json` and presets are **JSON**, not YAML — no `pyyaml` dependency (spec §3.6).
- The `routes/` archive path is always resolved relative to the current working directory at runtime, never hardcoded (existing convention, carried over unchanged).
- Overpass requests need an explicit, descriptive `User-Agent` (the default/browser UA gets 406'd) and a radius-limited query to avoid timeouts (existing convention in `overpass_query.py`, unchanged).
- Access/restricted-zone exclusion is **hard**, not weighted — a way or waypoint inside a restricted polygon is dropped/rejected entirely, never just penalized (spec §3.4).
- Never fabricate a "no-data" interest layer as fact — confidence tiers (`tag-backed`/`web-sourced`/`derived`/`no-data`) are preserved as-is from the existing skill.
- Ask the user explicitly for mode/style, loop-vs-point-to-point, and the distance/duration budget when not stated in their request — never pick a default silently (spec §3.2, §3.3, §3.5). This rule is a `SKILL.md` instruction, not something a unit test can check; Task 20 documents it.
- `weights.json` holds **inputs** needed to reproduce a run (mode, style, preference weights, tag rules, budget). `route.geojson` `LineString` properties hold **computed outputs** (distance, duration, elevation gain/loss, warnings, skipped points). Never duplicate a value between the two (spec §3.11).
- Presets under `presets/*.json` are read-only reference data — a run writes its own merged copy to `routes/<slug>-<date>/weights.json`, never back to the preset file.

## Review Focus

- A user-supplied interest point that falls inside a restricted zone (`access=private|no|military`, `landuse=military`, or an enclosed `barrier=fence|wall` ring) must produce an explicit rejection with a reason, never a silent "no path found" surfaced later from the router (spec §3.4). Covered in Task 15.
- All four elevation providers failing for a batch of points must not crash route building — affected edges simply get no gradient penalty, with a warning printed, not an exception (spec §3.8 step 4). Covered in Task 13.
- A route built from mandatory waypoints alone (access points + user-given interest points) that already exceeds the user's stated budget must surface as an explicit conflict for the user to resolve, never a silently-oversized route (spec §3.5 step 2). Covered in Task 16.
- Revising one field of an existing route's `weights.json` (e.g. swapping one interest point) must leave every other previously-set field — mode, style, preferences, budget — untouched unless the new request explicitly mentions them (spec §4 step 3). Covered in Task 4.
- After `build_graph` is changed to produce directed edges (needed for oneway support and asymmetric uphill/downhill cost), a plain two-way path segment with no `oneway` tag must remain traversable in both directions for both `walk` and `bike` — the switch to directed edges must not accidentally turn every segment one-way. Covered in Task 7.

---

## Task 1: Scaffold the skill directory and port `overpass_query.py`

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `skills/osm-day-route-planning/scripts/overpass_query.py` (ported verbatim from `init-raw-source/osm-hike-route-planning/scripts/overpass_query.py`)
- Create: `skills/osm-day-route-planning/tests/conftest.py`
- Test: `skills/osm-day-route-planning/tests/test_overpass_query.py`

**Interfaces:**
- Produces: `overpass_query.query_overpass(ql: str) -> dict`, `overpass_query.haversine(lat1, lon1, lat2, lon2) -> float` (unchanged signatures, used by every later task in this plan).

- [ ] **Step 1: Create the plugin manifest and directory skeleton**

```bash
mkdir -p /mnt/data/pavel/work/osm-hike-route/.claude-plugin
mkdir -p /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/scripts
mkdir -p /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/presets
mkdir -p /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/tests
```

Write `.claude-plugin/plugin.json`:

```json
{
  "name": "osm-day-route",
  "description": "Plan and visualize one-day walking/cycling routes using OpenStreetMap data.",
  "version": "0.1.0"
}
```

- [ ] **Step 2: Copy `overpass_query.py` into the new location unmodified**

```bash
cp /mnt/data/pavel/work/osm-hike-route/init-raw-source/osm-hike-route-planning/scripts/overpass_query.py \
   /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/scripts/overpass_query.py
```

Read the copied file and confirm it still has no third-party imports (only `json`, `math`, `sys`, `time`, `urllib.request`, `urllib.parse`).

- [ ] **Step 3: Add `conftest.py` so tests can `import` scripts by module name**

```python
# skills/osm-day-route-planning/tests/conftest.py
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
```

- [ ] **Step 4: Write a failing sanity test for the ported module**

```python
# skills/osm-day-route-planning/tests/test_overpass_query.py
from overpass_query import haversine


def test_haversine_zero_distance_for_identical_points():
    assert haversine(55.75, 37.61, 55.75, 37.61) == 0.0


def test_haversine_known_distance_moscow_spb():
    # Moscow to Saint Petersburg is roughly 635 km great-circle distance.
    km = haversine(55.7558, 37.6173, 59.9343, 30.3351) / 1000
    assert 620 <= km <= 650
```

- [ ] **Step 5: Run the test and confirm it passes (the module was only copied, not written)**

Run: `cd /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning && python3 -m pytest tests/test_overpass_query.py -v`
Expected: PASS (2 tests) — this step exists to catch a bad copy, not to drive new code.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json skills/osm-day-route-planning/scripts/overpass_query.py \
        skills/osm-day-route-planning/tests/conftest.py skills/osm-day-route-planning/tests/test_overpass_query.py
git commit -m "Scaffold osm-day-route-planning skill and port overpass_query.py"
```

---

## Task 2: Preset loader and the three preset files

**Files:**
- Create: `skills/osm-day-route-planning/scripts/presets.py`
- Create: `skills/osm-day-route-planning/presets/walk.json`
- Create: `skills/osm-day-route-planning/presets/bike-leisure.json`
- Create: `skills/osm-day-route-planning/presets/bike-sport.json`
- Test: `skills/osm-day-route-planning/tests/test_presets.py`

**Interfaces:**
- Produces: `presets.PRESETS_DIR: Path`, `presets.load_preset(mode: str, style: str | None = None) -> dict`, `presets.PresetNotFoundError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# skills/osm-day-route-planning/tests/test_presets.py
import pytest
from presets import load_preset, PresetNotFoundError

REQUIRED_KEYS = {
    "mode", "routable_highway", "hard_exclude_tags",
    "exclude_highway_without_infra", "blocking_barrier_tags", "buffers_m",
    "preferences", "gradient_threshold_pct", "pace_kmh",
    "ascent_minutes_per_100m", "duration_warning_hours",
}


def test_load_walk_preset_has_all_required_keys():
    preset = load_preset("walk")
    assert REQUIRED_KEYS.issubset(preset.keys())
    assert preset["mode"] == "walk"
    assert "style" not in preset


@pytest.mark.parametrize("style", ["leisure", "sport"])
def test_load_bike_preset_has_all_required_keys(style):
    preset = load_preset("bike", style=style)
    assert REQUIRED_KEYS.issubset(preset.keys())
    assert preset["mode"] == "bike"
    assert preset["style"] == style


def test_bike_without_style_raises():
    with pytest.raises(PresetNotFoundError):
        load_preset("bike")


def test_unknown_mode_raises():
    with pytest.raises(PresetNotFoundError):
        load_preset("ski")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'presets'`

- [ ] **Step 3: Write the preset JSON files**

```json
// skills/osm-day-route-planning/presets/walk.json
{
  "mode": "walk",
  "routable_highway": ["path", "footway", "track", "residential", "living_street"],
  "hard_exclude_tags": { "foot": ["no"] },
  "exclude_highway_without_infra": [],
  "blocking_barrier_tags": [],
  "buffers_m": { "highway": 50, "water": 30 },
  "preferences": {
    "prefer_forest": 1.5,
    "avoid_open_field": 2.0,
    "avoid_near_highway": 3.0,
    "avoid_near_water": 2.0,
    "avoid_steep_gradient": 2.0
  },
  "gradient_threshold_pct": 12,
  "pace_kmh": 4.5,
  "ascent_minutes_per_100m": 12,
  "duration_warning_hours": 10
}
```

```json
// skills/osm-day-route-planning/presets/bike-leisure.json
{
  "mode": "bike",
  "style": "leisure",
  "routable_highway": ["path", "footway", "track", "cycleway", "residential", "living_street"],
  "hard_exclude_tags": { "bicycle": ["no", "dismount"], "highway": ["steps"] },
  "exclude_highway_without_infra": ["trunk", "primary"],
  "blocking_barrier_tags": ["cycle_barrier", "turnstile"],
  "buffers_m": { "highway": 60, "water": 30 },
  "preferences": {
    "prefer_forest": 1.4,
    "avoid_open_field": 1.6,
    "avoid_near_highway": 3.0,
    "avoid_near_water": 1.8,
    "avoid_steep_gradient": 2.5
  },
  "gradient_threshold_pct": 8,
  "pace_kmh": 15,
  "ascent_minutes_per_100m": 10,
  "duration_warning_hours": 8
}
```

```json
// skills/osm-day-route-planning/presets/bike-sport.json
{
  "mode": "bike",
  "style": "sport",
  "routable_highway": ["path", "footway", "track", "cycleway", "residential", "living_street", "secondary"],
  "hard_exclude_tags": { "bicycle": ["no", "dismount"], "highway": ["steps"] },
  "exclude_highway_without_infra": ["trunk", "primary"],
  "blocking_barrier_tags": ["cycle_barrier", "turnstile"],
  "buffers_m": { "highway": 30, "water": 20 },
  "preferences": {
    "prefer_forest": 1.0,
    "avoid_open_field": 1.0,
    "avoid_near_highway": 3.0,
    "avoid_near_water": 1.0,
    "avoid_steep_gradient": 1.5
  },
  "gradient_threshold_pct": 8,
  "pace_kmh": 22,
  "ascent_minutes_per_100m": 7,
  "duration_warning_hours": 6
}
```

- [ ] **Step 4: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/presets.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-planning/scripts/presets.py skills/osm-day-route-planning/presets/*.json \
        skills/osm-day-route-planning/tests/test_presets.py
git commit -m "Add preset loader and walk/bike-leisure/bike-sport presets"
```

---

## Task 3: `build_weights` — merge a preset with user overrides and the budget

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/presets.py`
- Test: `skills/osm-day-route-planning/tests/test_presets.py`

**Interfaces:**
- Consumes: `presets.load_preset` (Task 2).
- Produces: `presets.build_weights(preset: dict, preference_overrides: dict | None = None, max_distance_km: float | None = None, max_duration_hours: float | None = None) -> dict` — a deep copy of `preset` with `preferences` merged (override wins per-key) and `max_distance_km`/`max_duration_hours` added.

- [ ] **Step 1: Write the failing test**

```python
def test_build_weights_merges_preference_overrides_without_mutating_preset():
    preset = load_preset("walk")
    original_prefer_forest = preset["preferences"]["prefer_forest"]

    weights = build_weights(preset, preference_overrides={"prefer_forest": 3.0})

    assert weights["preferences"]["prefer_forest"] == 3.0
    assert weights["preferences"]["avoid_open_field"] == preset["preferences"]["avoid_open_field"]
    assert preset["preferences"]["prefer_forest"] == original_prefer_forest  # preset untouched


def test_build_weights_defaults_budget_to_none():
    weights = build_weights(load_preset("walk"))
    assert weights["max_distance_km"] is None
    assert weights["max_duration_hours"] is None


def test_build_weights_sets_given_budget():
    weights = build_weights(load_preset("walk"), max_distance_km=10.0)
    assert weights["max_distance_km"] == 10.0
    assert weights["max_duration_hours"] is None
```

Add `from presets import load_preset, build_weights, PresetNotFoundError` to the top of the test file (replacing the earlier import line).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_weights'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to skills/osm-day-route-planning/scripts/presets.py
import copy


def build_weights(preset: dict, preference_overrides: dict | None = None,
                   max_distance_km: float | None = None,
                   max_duration_hours: float | None = None) -> dict:
    weights = copy.deepcopy(preset)
    if preference_overrides:
        weights["preferences"].update(preference_overrides)
    weights["max_distance_km"] = max_distance_km
    weights["max_duration_hours"] = max_duration_hours
    return weights
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/presets.py skills/osm-day-route-planning/tests/test_presets.py
git commit -m "Add build_weights: merge preset with user overrides and budget"
```

---

## Task 4: `revise_weights` — partial-update merge for iteration requests

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/presets.py`
- Test: `skills/osm-day-route-planning/tests/test_presets.py`

**Interfaces:**
- Produces: `presets.revise_weights(existing: dict, changes: dict) -> dict` — returns a new dict equal to `existing` except for keys present in `changes`; a `preferences` key in `changes` merges into the existing `preferences` dict rather than replacing it wholesale.

This task directly covers **Review Focus** item 4: an iteration that only mentions one field must not reset the rest.

- [ ] **Step 1: Write the failing test**

```python
def test_revise_weights_changes_only_named_top_level_fields():
    existing = build_weights(load_preset("bike", style="leisure"), max_distance_km=12.0)

    revised = revise_weights(existing, {"max_distance_km": 18.0})

    assert revised["max_distance_km"] == 18.0
    assert revised["max_duration_hours"] == existing["max_duration_hours"]
    assert revised["mode"] == "bike"
    assert revised["style"] == "leisure"
    assert revised["preferences"] == existing["preferences"]


def test_revise_weights_merges_preferences_key_instead_of_replacing():
    existing = build_weights(load_preset("walk"))

    revised = revise_weights(existing, {"preferences": {"avoid_near_water": 5.0}})

    assert revised["preferences"]["avoid_near_water"] == 5.0
    # Untouched preference keys survive the partial preferences update.
    assert revised["preferences"]["prefer_forest"] == existing["preferences"]["prefer_forest"]


def test_revise_weights_does_not_mutate_existing_argument():
    existing = build_weights(load_preset("walk"))
    frozen_copy = copy.deepcopy(existing)

    revise_weights(existing, {"max_distance_km": 5.0})

    assert existing == frozen_copy
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: FAIL with `ImportError: cannot import name 'revise_weights'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to skills/osm-day-route-planning/scripts/presets.py
def revise_weights(existing: dict, changes: dict) -> dict:
    revised = copy.deepcopy(existing)
    for key, value in changes.items():
        if key == "preferences" and isinstance(value, dict):
            revised["preferences"].update(value)
        else:
            revised[key] = value
    return revised
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_presets.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/presets.py skills/osm-day-route-planning/tests/test_presets.py
git commit -m "Add revise_weights for partial iteration updates (Review Focus #4)"
```

---

## Task 5: `weights_io` — save/load `weights.json`

**Files:**
- Create: `skills/osm-day-route-planning/scripts/weights_io.py`
- Test: `skills/osm-day-route-planning/tests/test_weights_io.py`

**Interfaces:**
- Produces: `weights_io.save_weights(route_dir: Path, weights: dict) -> None`, `weights_io.load_weights(route_dir: Path) -> dict | None` (`None` when no `weights.json` exists yet).

- [ ] **Step 1: Write the failing test**

```python
# skills/osm-day-route-planning/tests/test_weights_io.py
import json
from weights_io import save_weights, load_weights


def test_load_weights_returns_none_when_file_missing(tmp_path):
    assert load_weights(tmp_path) is None


def test_save_then_load_round_trips(tmp_path):
    weights = {"mode": "walk", "preferences": {"prefer_forest": 1.5}, "max_distance_km": None}

    save_weights(tmp_path, weights)
    loaded = load_weights(tmp_path)

    assert loaded == weights
    assert json.loads((tmp_path / "weights.json").read_text(encoding="utf-8")) == weights


def test_save_weights_creates_route_dir_if_missing(tmp_path):
    route_dir = tmp_path / "encinar-de-boadilla-2026-09-28"
    save_weights(route_dir, {"mode": "walk"})
    assert (route_dir / "weights.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_weights_io.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'weights_io'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/weights_io.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_weights_io.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/weights_io.py skills/osm-day-route-planning/tests/test_weights_io.py
git commit -m "Add weights_io save/load for weights.json"
```

---

## Task 6: `requests_log` — the `requests.md` iteration journal

**Files:**
- Create: `skills/osm-day-route-planning/scripts/requests_log.py`
- Test: `skills/osm-day-route-planning/tests/test_requests_log.py`

**Interfaces:**
- Produces: `requests_log.append_request(route_dir: Path, request_text: str, summary: str) -> int` (returns the new iteration number), `requests_log.read_requests(route_dir: Path) -> list[dict]` (each dict: `{"iteration": int, "timestamp": str, "request": str, "summary": str}`).

- [ ] **Step 1: Write the failing test**

```python
# skills/osm-day-route-planning/tests/test_requests_log.py
from requests_log import append_request, read_requests


def test_read_requests_returns_empty_list_when_no_log(tmp_path):
    assert read_requests(tmp_path) == []


def test_append_request_returns_incrementing_iteration_numbers(tmp_path):
    first = append_request(tmp_path, "Маршрут у Бажуково, 10 км, кольцевой", "первая версия маршрута")
    second = append_request(tmp_path, "Замени точку А на музей", "заменена точка интереса")

    assert first == 1
    assert second == 2


def test_appended_requests_are_stored_verbatim_and_in_order(tmp_path):
    append_request(tmp_path, "Маршрут «у реки», ~5 часов", "построен маршрут")
    append_request(tmp_path, "Сделай его короче", "уменьшен бюджет до 8 км")

    entries = read_requests(tmp_path)

    assert len(entries) == 2
    assert entries[0]["iteration"] == 1
    assert entries[0]["request"] == "Маршрут «у реки», ~5 часов"
    assert entries[1]["iteration"] == 2
    assert entries[1]["request"] == "Сделай его короче"
    assert entries[1]["summary"] == "уменьшен бюджет до 8 км"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_requests_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'requests_log'`

- [ ] **Step 3: Write the minimal implementation**

Store one JSON object per line in `requests.md` inside a fenced block per entry — human-readable (headings + verbatim quote) while staying trivially parseable, instead of inventing a bespoke markdown grammar to parse back.

```python
# skills/osm-day-route-planning/scripts/requests_log.py
"""Journal of verbatim user requests per route, one entry per planning
iteration (spec §3.1). Read at the start of any revision so a later
session/agent sees the full accumulated context, not just the last ask."""
import json
from datetime import datetime, timezone
from pathlib import Path

_ENTRY_MARKER = "<!-- requests_log entry: "


def append_request(route_dir: Path, request_text: str, summary: str) -> int:
    route_dir = Path(route_dir)
    route_dir.mkdir(parents=True, exist_ok=True)
    path = route_dir / "requests.md"
    existing = read_requests(route_dir)
    iteration = len(existing) + 1
    entry = {
        "iteration": iteration,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": request_text,
        "summary": summary,
    }
    block = (
        f"\n## Итерация {iteration} ({entry['timestamp']})\n\n"
        f"> {request_text}\n\n"
        f"Изменения: {summary}\n\n"
        f"{_ENTRY_MARKER}{json.dumps(entry, ensure_ascii=False)} -->\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(block)
    return iteration


def read_requests(route_dir: Path) -> list[dict]:
    path = Path(route_dir) / "requests.md"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(_ENTRY_MARKER):
            raw_json = line[len(_ENTRY_MARKER):].rsplit("-->", 1)[0].strip()
            entries.append(json.loads(raw_json))
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_requests_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/requests_log.py skills/osm-day-route-planning/tests/test_requests_log.py
git commit -m "Add requests_log for the requests.md iteration journal"
```

---

## Task 7: Directed graph with oneway support (Review Focus #5)

**Files:**
- Create: `skills/osm-day-route-planning/scripts/route_graph.py` (ported and modified from `init-raw-source/osm-hike-route-planning/scripts/route_graph.py`)
- Test: `skills/osm-day-route-planning/tests/test_route_graph.py`

**Interfaces:**
- Consumes: `overpass_query.haversine` (Task 1).
- Produces: `route_graph.build_graph(walkable_ways: list[dict], barrier_nodes: list[dict] | None = None, blocking_barrier_tags: list[str] | None = None, respect_oneway: bool = False) -> tuple[dict, dict]`. The graph is `{node_id: [[neighbor_id, length_m, tags_dict], ...]}` — directed: a two-way segment appends an entry to **both** `graph[a]` and `graph[b]`; a `oneway=yes` segment (when `respect_oneway=True`) appends only the forward entry.

- [ ] **Step 1: Copy the existing file as a starting point**

```bash
cp /mnt/data/pavel/work/osm-hike-route/init-raw-source/osm-hike-route-planning/scripts/route_graph.py \
   /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/scripts/route_graph.py
```

- [ ] **Step 2: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_route_graph.py
from route_graph import build_graph


def _two_node_way(node_a=1, node_b=2, tags=None):
    return [{
        "nodes": [node_a, node_b],
        "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}],
        "tags": tags or {},
    }]


def test_two_way_segment_is_traversable_in_both_directions_by_default():
    graph, _ = build_graph(_two_node_way())

    neighbors_of_1 = [edge[0] for edge in graph[1]]
    neighbors_of_2 = [edge[0] for edge in graph[2]]

    assert 2 in neighbors_of_1
    assert 1 in neighbors_of_2


def test_oneway_segment_is_forward_only_when_respect_oneway_true():
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 not in [edge[0] for edge in graph.get(2, [])]


def test_oneway_ignored_when_respect_oneway_false():
    """walk mode: oneway restrictions never apply, even if the tag is present."""
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=False)

    assert 1 in [edge[0] for edge in graph.get(2, [])]


def test_oneway_bicycle_no_reopens_reverse_direction():
    way = _two_node_way(tags={"oneway": "yes", "oneway:bicycle": "no"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 in [edge[0] for edge in graph.get(2, [])]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: FAIL — `test_oneway_segment_is_forward_only_when_respect_oneway_true` and `test_oneway_bicycle_no_reopens_reverse_direction` fail because the copied `build_graph` always adds both directions and has no `respect_oneway` parameter.

- [ ] **Step 4: Modify `build_graph` to support directed edges**

Replace the existing `build_graph` function body in `route_graph.py`:

```python
def build_graph(walkable_ways, barrier_nodes=None, blocking_barrier_tags=None, respect_oneway=False):
    """Returns (graph, node_coords). graph: {node_id: [[neighbor_id, length_m, tags], ...]}
    Directed: each physical segment gets its own forward/reverse entries so
    oneway restrictions (bike) and asymmetric uphill/downhill cost (any mode,
    once elevation is tagged) can differ per direction — see spec §3.7.
    barrier_nodes: list of Overpass node elements with a 'barrier' tag — an
    edge touching one whose tag is in `blocking_barrier_tags`, or that
    independently fails the existing hardcoded lock check, is dropped."""
    blocking_ids = {
        n["id"] for n in (barrier_nodes or [])
        if _blocks_passage(n.get("tags", {}), blocking_barrier_tags or [])
    }
    graph = {}
    node_coords = {}
    for way in walkable_ways:
        ids = way.get("nodes")
        geom = way.get("geometry")
        tags = way.get("tags", {})
        if not ids or not geom or len(ids) != len(geom):
            continue
        for node_id, pt in zip(ids, geom):
            node_coords[node_id] = (pt["lat"], pt["lon"])

        forward_allowed, reverse_allowed = _direction_allowed(tags, respect_oneway)

        for i in range(len(ids) - 1):
            a, b = ids[i], ids[i + 1]
            if a in blocking_ids or b in blocking_ids:
                continue
            lat1, lon1 = node_coords[a]
            lat2, lon2 = node_coords[b]
            length = haversine(lat1, lon1, lat2, lon2)
            graph.setdefault(a, [])
            graph.setdefault(b, [])
            if forward_allowed:
                graph[a].append([b, length, {}])
            if reverse_allowed:
                graph[b].append([a, length, {}])
    return graph, node_coords


def _direction_allowed(tags: dict, respect_oneway: bool) -> tuple[bool, bool]:
    """(forward_allowed, reverse_allowed) for a way's own tag direction.
    Ignored entirely (both True) unless respect_oneway (bike) — walk never
    respects oneway. `oneway:bicycle=no` or a `cycleway=opposite*` tag
    reopens the reverse direction for a bicycle even on a oneway street."""
    if not respect_oneway or tags.get("oneway") != "yes":
        return True, True
    if tags.get("oneway:bicycle") == "no":
        return True, True
    if str(tags.get("cycleway", "")).startswith("opposite"):
        return True, True
    return True, False


def _blocks_passage(tags: dict, blocking_barrier_tags: list[str]) -> bool:
    """A barrier node blocks routing through it if it's actually locked
    (existing conservative rule), or if this mode's preset explicitly
    lists its barrier type as blocking (e.g. cycle_barrier for bike)."""
    if tags.get("access") in ("private", "no"):
        return True
    if tags.get("locked") == "yes":
        return True
    if tags.get("barrier") == "wall":
        return True
    if tags.get("barrier") in blocking_barrier_tags:
        return True
    return False
```

This replaces both the old `build_graph` and the old `_blocks_passage` (which previously took only `tags` — now also takes `blocking_barrier_tags`, so update any other in-file caller of `_blocks_passage` accordingly; at this point in the port there are none yet since `filter_excluded_ways`/`fetch_area_data` calls come in Task 8).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-planning/scripts/route_graph.py skills/osm-day-route-planning/tests/test_route_graph.py
git commit -m "Make build_graph directed with oneway support (Review Focus #5)"
```

---

## Task 8: Preset-driven hard exclusion

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/route_graph.py`
- Test: `skills/osm-day-route-planning/tests/test_route_graph.py`

**Interfaces:**
- Consumes: preset dict shape from Task 2 (`hard_exclude_tags`, `exclude_highway_without_infra`).
- Produces: `route_graph.filter_excluded_ways(walkable_ways: list[dict], restricted_polygons: list, hard_exclude_tags: dict[str, list[str]] | None = None, exclude_highway_without_infra: list[str] | None = None) -> list[dict]`, and exports `route_graph.point_in_ring` (renamed from the existing private `_point_in_ring`, kept importable for Task 15).

- [ ] **Step 1: Write the failing tests**

```python
def _way_with_tags(tags, way_id=1):
    return {
        "id": way_id,
        "nodes": [1, 2],
        "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}],
        "tags": tags,
    }


def test_filter_excluded_ways_drops_hard_excluded_tag_for_bike():
    ways = [_way_with_tags({"highway": "path"}), _way_with_tags({"highway": "steps"}, way_id=2)]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 hard_exclude_tags={"highway": ["steps"]})

    assert [w["id"] for w in kept] == [1]


def test_filter_excluded_ways_drops_trunk_without_cycle_infra_for_bike():
    ways = [
        _way_with_tags({"highway": "trunk"}, way_id=1),
        _way_with_tags({"highway": "trunk", "cycleway": "track"}, way_id=2),
    ]

    kept = filter_excluded_ways(ways, restricted_polygons=[],
                                 exclude_highway_without_infra=["trunk"])

    assert [w["id"] for w in kept] == [2]


def test_filter_excluded_ways_keeps_everything_for_walk_with_no_rules():
    ways = [_way_with_tags({"highway": "trunk"}), _way_with_tags({"highway": "steps"}, way_id=2)]

    kept = filter_excluded_ways(ways, restricted_polygons=[])

    assert len(kept) == 2
```

Add `filter_excluded_ways` to the test file's `from route_graph import ...` line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: FAIL — `TypeError: filter_excluded_ways() got an unexpected keyword argument 'hard_exclude_tags'` (the ported function doesn't accept these params yet).

- [ ] **Step 3: Replace `filter_excluded_ways` and rename `_point_in_ring`**

```python
def point_in_ring(lat, lon, ring):
    """Ray-casting point-in-polygon. ring: list of (lat, lon). Flat-plane
    approximation — fine at city/park scale, not for large-area GIS work.
    Exported (not `_`-prefixed) so waypoints.py can reuse it — see spec §3.4."""
    inside = False
    n = len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        if ((lon1 > lon) != (lon2 > lon)) and \
           (lat < (lat2 - lat1) * (lon - lon1) / (lon2 - lon1 + 1e-15) + lat1):
            inside = not inside
    return inside


def _has_hard_excluded_tag(tags: dict, hard_exclude_tags: dict) -> bool:
    return any(tags.get(key) in values for key, values in hard_exclude_tags.items())


def _lacks_required_cycle_infra(tags: dict, exclude_highway_without_infra: list) -> bool:
    if tags.get("highway") not in exclude_highway_without_infra:
        return False
    return "cycleway" not in tags


def filter_excluded_ways(walkable_ways, restricted_polygons,
                          hard_exclude_tags: dict | None = None,
                          exclude_highway_without_infra: list | None = None):
    """Hard-excludes a way whose midpoint falls inside a restricted polygon
    (unchanged from the walk-only version), OR whose tags match this mode's
    preset-supplied hard-exclusion rules (spec §3.6) — never a weighted
    penalty, a full drop, same as the restricted-zone case."""
    hard_exclude_tags = hard_exclude_tags or {}
    exclude_highway_without_infra = exclude_highway_without_infra or []
    kept = []
    for way in walkable_ways:
        geom = way.get("geometry")
        if not geom:
            continue
        tags = way.get("tags", {})
        if _has_hard_excluded_tag(tags, hard_exclude_tags):
            continue
        if _lacks_required_cycle_infra(tags, exclude_highway_without_infra):
            continue
        mid = geom[len(geom) // 2]
        if any(point_in_ring(mid["lat"], mid["lon"], ring) for ring in restricted_polygons):
            continue
        kept.append(way)
    return kept
```

Delete the old `_point_in_ring` definition (now `point_in_ring`) and update the two other in-file call sites (`build_restricted_polygons`'s caller doesn't call it, but `tag_edges` does via `_point_in_ring` for forest/field lookup) — rename those call sites from `_point_in_ring(...)` to `point_in_ring(...)` as well.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/route_graph.py skills/osm-day-route-planning/tests/test_route_graph.py
git commit -m "Drive hard-exclusion rules from preset data instead of hardcoding per mode"
```

---

## Task 9: Gradient-aware, asymmetric edge cost

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/route_graph.py`
- Test: `skills/osm-day-route-planning/tests/test_route_graph.py`

**Interfaces:**
- Produces: `route_graph.tag_grades(graph: dict, node_coords: dict, elevations: dict[int, float]) -> None` (mutates edge tags in place, adding `"grade_pct"`), and an extended `route_graph._edge_cost(length_m, tags, preferences)` that reads `tags["grade_pct"]` and applies `preferences["avoid_steep_gradient"]` above `preferences.get("gradient_threshold_pct", 8)`.

- [ ] **Step 1: Write the failing tests**

```python
from route_graph import tag_grades, _edge_cost, weighted_shortest_path


def test_tag_grades_computes_signed_percent_grade():
    graph = {1: [[2, 100.0, {}]], 2: [[1, 100.0, {}]]}
    node_coords = {1: (55.0, 37.0), 2: (55.001, 37.0)}
    elevations = {1: 200.0, 2: 210.0}  # +10m over a 100m edge => +10%

    tag_grades(graph, node_coords, elevations)

    assert graph[1][0][2]["grade_pct"] == pytest.approx(10.0)
    assert graph[2][0][2]["grade_pct"] == pytest.approx(-10.0)


def test_edge_cost_penalizes_uphill_more_than_downhill_above_threshold():
    preferences = {"avoid_steep_gradient": 2.0, "gradient_threshold_pct": 8}

    uphill_cost = _edge_cost(100.0, {"grade_pct": 15.0}, preferences)
    downhill_cost = _edge_cost(100.0, {"grade_pct": -15.0}, preferences)
    flat_cost = _edge_cost(100.0, {"grade_pct": 2.0}, preferences)

    assert uphill_cost > flat_cost
    assert flat_cost <= downhill_cost < uphill_cost


def test_weighted_shortest_path_prefers_gentler_route_when_steep_is_penalized():
    # Two parallel paths from 1 to 3: a short steep one (1->2->3) and a
    # longer flat one (1->4->3).
    graph = {
        1: [[2, 50.0, {"grade_pct": 20.0}], [4, 60.0, {"grade_pct": 0.0}]],
        2: [[3, 50.0, {"grade_pct": 20.0}]],
        4: [[3, 60.0, {"grade_pct": 0.0}]],
        3: [],
    }
    preferences = {"avoid_steep_gradient": 5.0, "gradient_threshold_pct": 8}

    path, cost = weighted_shortest_path(graph, 1, 3, preferences)

    assert path == [1, 4, 3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: FAIL with `ImportError: cannot import name 'tag_grades'`

- [ ] **Step 3: Add `tag_grades` and extend `_edge_cost`**

```python
def tag_grades(graph, node_coords, elevations):
    """Mutates graph in place: each directed edge's tags get `grade_pct`,
    the signed percent grade climbing FROM this edge's origin node TOWARD
    its neighbor. Missing elevation for either endpoint leaves grade_pct
    at 0.0 (no penalty) rather than raising — see spec §3.8 point 4."""
    for node_id, edges in graph.items():
        for edge in edges:
            neighbor_id, length_m, tags = edge
            elev_a = elevations.get(node_id)
            elev_b = elevations.get(neighbor_id)
            if elev_a is None or elev_b is None or length_m == 0:
                tags["grade_pct"] = 0.0
                continue
            tags["grade_pct"] = (elev_b - elev_a) / length_m * 100.0
```

Replace `_edge_cost`:

```python
def _edge_cost(length_m, tags, preferences):
    cost = length_m
    if tags.get("landcover") == "forest":
        cost /= preferences.get("prefer_forest", 1.0)
    if tags.get("landcover") == "field":
        cost *= preferences.get("avoid_open_field", 1.0)
    if tags.get("near_highway"):
        cost *= preferences.get("avoid_near_highway", 1.0)
    if tags.get("near_water"):
        cost *= preferences.get("avoid_near_water", 1.0)
    grade_pct = tags.get("grade_pct", 0.0)
    threshold = preferences.get("gradient_threshold_pct", 8)
    if grade_pct > threshold:
        cost *= preferences.get("avoid_steep_gradient", 1.0)
    return cost
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_route_graph.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/route_graph.py skills/osm-day-route-planning/tests/test_route_graph.py
git commit -m "Add gradient-aware, asymmetric edge cost from tagged grades"
```

---

## Task 10: Elevation provider base + Open-Topo-Data

**Files:**
- Create: `skills/osm-day-route-planning/scripts/elevation/__init__.py` (empty for now, filled in Task 13)
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/__init__.py` (empty)
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/base.py`
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/open_topo_data.py`
- Test: `skills/osm-day-route-planning/tests/test_elevation_providers.py`

**Interfaces:**
- Produces: `elevation.providers.base.ElevationProvider` (ABC with `provider_id: str`, `max_batch: int`, `rate_limit_per_sec: float`, `fetch(self, locations: list[tuple[float, float]]) -> list[float | None]`), `elevation.providers.open_topo_data.OpenTopoDataProvider(ElevationProvider)`.

- [ ] **Step 1: Write the failing test**

```python
# skills/osm-day-route-planning/tests/test_elevation_providers.py
import json
from unittest.mock import patch, MagicMock

from elevation.providers.open_topo_data import OpenTopoDataProvider


def _mock_response(payload: dict):
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_provider_id_and_batch_size():
    provider = OpenTopoDataProvider()
    assert provider.provider_id == "open_topo_data"
    assert provider.max_batch == 100


def test_fetch_returns_elevations_in_request_order():
    payload = {
        "status": "OK",
        "results": [
            {"elevation": 100.0, "location": {"lat": 55.0, "lng": 37.0}},
            {"elevation": 120.5, "location": {"lat": 55.1, "lng": 37.1}},
        ],
    }
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [100.0, 120.5]


def test_fetch_returns_none_per_point_on_http_error():
    import urllib.error
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [None, None]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_elevation_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'elevation'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/elevation/providers/base.py
"""Common interface every elevation plugin implements — one source, one
file, see spec §3.8. ElevationService (Task 13) only talks to this
interface, never to a provider's own HTTP details."""
from abc import ABC, abstractmethod


class ElevationProvider(ABC):
    provider_id: str
    max_batch: int
    rate_limit_per_sec: float

    @abstractmethod
    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        """Returns one elevation (meters) per input (lat, lon), same order.
        A point this provider couldn't resolve is None, not a raised
        error — a raised error means the whole batch failed (see callers)."""
        raise NotImplementedError
```

```python
# skills/osm-day-route-planning/scripts/elevation/providers/open_topo_data.py
import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenTopoDataProvider(ElevationProvider):
    provider_id = "open_topo_data"
    max_batch = 100
    rate_limit_per_sec = 1.0
    dataset = "srtm90m"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        locations_param = "|".join(f"{lat},{lon}" for lat, lon in locations)
        url = f"https://api.opentopodata.org/v1/{self.dataset}?locations={locations_param}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return [None] * len(locations)
        return [r.get("elevation") for r in data.get("results", [])]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_elevation_providers.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/elevation skills/osm-day-route-planning/tests/test_elevation_providers.py
git commit -m "Add ElevationProvider interface and Open-Topo-Data plugin"
```

---

## Task 11: Remaining elevation providers (Open-Meteo, Elevation-API.eu, Open-Elevation)

**Files:**
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/open_meteo.py`
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/elevation_api_eu.py`
- Create: `skills/osm-day-route-planning/scripts/elevation/providers/open_elevation.py`
- Modify: `skills/osm-day-route-planning/tests/test_elevation_providers.py`

**Interfaces:**
- Produces: `OpenMeteoProvider`, `ElevationApiEuProvider`, `OpenElevationProvider` — same `ElevationProvider` shape as Task 10.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-planning/tests/test_elevation_providers.py
from elevation.providers.open_meteo import OpenMeteoProvider
from elevation.providers.elevation_api_eu import ElevationApiEuProvider
from elevation.providers.open_elevation import OpenElevationProvider


def test_open_meteo_fetch_returns_elevations_in_order():
    payload = {"elevation": [38.0, 41.5]}
    provider = OpenMeteoProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(52.5, 13.4), (48.85, 2.35)])

    assert result == [38.0, 41.5]
    assert provider.provider_id == "open_meteo"
    assert provider.max_batch == 100


def test_elevation_api_eu_fetch_returns_elevations_in_order():
    payload = [120.3, None, 88.0]
    provider = ElevationApiEuProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (0.0, 0.0), (46.5, 6.6)])

    assert result == [120.3, None, 88.0]
    assert provider.provider_id == "elevation_api_eu"
    assert provider.rate_limit_per_sec == 10.0


def test_open_elevation_fetch_returns_elevations_in_order():
    payload = {"results": [{"elevation": 300.0}, {"elevation": 305.5}]}
    provider = OpenElevationProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [300.0, 305.5]
    assert provider.provider_id == "open_elevation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elevation_providers.py -v`
Expected: FAIL with `ModuleNotFoundError` for each new provider module.

- [ ] **Step 3: Write the minimal implementations**

```python
# skills/osm-day-route-planning/scripts/elevation/providers/open_meteo.py
import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenMeteoProvider(ElevationProvider):
    provider_id = "open_meteo"
    max_batch = 100
    rate_limit_per_sec = 5.0
    dataset = "copernicus_glo90"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        lats = ",".join(str(lat) for lat, _ in locations)
        lons = ",".join(str(lon) for _, lon in locations)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return [None] * len(locations)
        return list(data.get("elevation", [None] * len(locations)))
```

```python
# skills/osm-day-route-planning/scripts/elevation/providers/elevation_api_eu.py
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class ElevationApiEuProvider(ElevationProvider):
    provider_id = "elevation_api_eu"
    max_batch = 100  # not documented by the provider — treated conservatively, see spec §3.8
    rate_limit_per_sec = 10.0
    dataset = "copernicus"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        pts = json.dumps([[lat, lon] for lat, lon in locations])
        url = "https://www.elevation-api.eu/v1/elevation?" + urllib.parse.urlencode({"pts": pts})
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return [None] * len(locations)
        return list(data)
```

```python
# skills/osm-day-route-planning/scripts/elevation/providers/open_elevation.py
import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenElevationProvider(ElevationProvider):
    """Least reliable of the four (known public-instance outages) — kept
    last in ElevationService's failover order, see spec §3.8."""
    provider_id = "open_elevation"
    max_batch = 100
    rate_limit_per_sec = 1.0
    dataset = "srtm"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        body = json.dumps({
            "locations": [{"latitude": lat, "longitude": lon} for lat, lon in locations]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.open-elevation.com/api/v1/lookup",
            data=body,
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return [None] * len(locations)
        return [r.get("elevation") for r in data.get("results", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_elevation_providers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/elevation skills/osm-day-route-planning/tests/test_elevation_providers.py
git commit -m "Add Open-Meteo, Elevation-API.eu, and Open-Elevation providers"
```

---

## Task 12: Elevation cache

**Files:**
- Create: `skills/osm-day-route-planning/scripts/elevation/cache.py`
- Test: `skills/osm-day-route-planning/tests/test_elevation_cache.py`

**Interfaces:**
- Produces: `elevation.cache.cache_key(lat: float, lon: float, dataset: str) -> str`, `elevation.cache.load_cache(path: Path) -> dict`, `elevation.cache.save_entry(path: Path, cache: dict, key: str, elevation: float, provider_id: str, dataset: str) -> None` (writes the whole cache dict to `path` immediately — the "incremental write" spec requirement, see spec §3.8).

- [ ] **Step 1: Write the failing test**

```python
# skills/osm-day-route-planning/tests/test_elevation_cache.py
import json
from elevation.cache import cache_key, load_cache, save_entry


def test_cache_key_rounds_coordinates_consistently():
    key_a = cache_key(55.123456, 37.654321, "srtm90m")
    key_b = cache_key(55.123459, 37.654328, "srtm90m")  # rounds to the same key
    key_c = cache_key(55.999999, 37.654321, "srtm90m")

    assert key_a == key_b
    assert key_a != key_c


def test_load_cache_returns_empty_dict_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "elevation.json") == {}


def test_save_entry_persists_immediately_and_is_reloadable(tmp_path):
    path = tmp_path / "elevation.json"
    cache = load_cache(path)

    save_entry(path, cache, cache_key(55.0, 37.0, "srtm90m"), 123.4, "open_topo_data", "srtm90m")

    reloaded = load_cache(path)
    key = cache_key(55.0, 37.0, "srtm90m")
    assert reloaded[key] == {
        "lat": 55.0, "lon": 37.0, "elevation": 123.4,
        "provider_id": "open_topo_data", "dataset": "srtm90m",
    }
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert key in on_disk


def test_save_entry_does_not_lose_previously_saved_entries(tmp_path):
    path = tmp_path / "elevation.json"
    cache = load_cache(path)
    save_entry(path, cache, "key-a", 1.0, "open_topo_data", "srtm90m")

    cache_reloaded = load_cache(path)
    save_entry(path, cache_reloaded, "key-b", 2.0, "open_meteo", "copernicus_glo90")

    final = load_cache(path)
    assert set(final.keys()) == {"key-a", "key-b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_elevation_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'elevation.cache'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/elevation/cache.py
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


def save_entry(path: Path, cache: dict, key: str, elevation: float,
               provider_id: str, dataset: str) -> None:
    lat_str, lon_str, _ = key.split("|")
    cache[key] = {
        "lat": float(lat_str), "lon": float(lon_str), "elevation": elevation,
        "provider_id": provider_id, "dataset": dataset,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_elevation_cache.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/elevation/cache.py skills/osm-day-route-planning/tests/test_elevation_cache.py
git commit -m "Add shared elevation cache keyed by rounded coordinates + dataset"
```

---

## Task 13: `ElevationService` — failover, batching, rate limiting (Review Focus #2)

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/elevation/__init__.py`
- Test: `skills/osm-day-route-planning/tests/test_elevation_service.py`

**Interfaces:**
- Consumes: `elevation.providers.base.ElevationProvider` (Task 10), `elevation.cache.{cache_key,load_cache,save_entry}` (Task 12).
- Produces: `elevation.ElevationService(providers: list[ElevationProvider], cache_path: Path, dataset: str = "srtm90m")` with `.get_elevations(locations: list[tuple[float, float]]) -> list[float | None]`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_elevation_service.py
from elevation import ElevationService
from elevation.providers.base import ElevationProvider


class _FakeProvider(ElevationProvider):
    def __init__(self, provider_id, max_batch=100, rate_limit_per_sec=100.0, responses=None, fail=False):
        self.provider_id = provider_id
        self.max_batch = max_batch
        self.rate_limit_per_sec = rate_limit_per_sec
        self._responses = responses or {}
        self.fail = fail
        self.calls = []

    def fetch(self, locations):
        self.calls.append(list(locations))
        if self.fail:
            return [None] * len(locations)
        return [self._responses.get(loc) for loc in locations]


def test_get_elevations_returns_values_from_first_working_provider(tmp_path):
    provider = _FakeProvider("p1", responses={(55.0, 37.0): 100.0})
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [100.0]


def test_get_elevations_fails_over_to_next_provider_for_unresolved_points(tmp_path):
    failing = _FakeProvider("p1", fail=True)
    working = _FakeProvider("p2", responses={(55.0, 37.0): 200.0})
    service = ElevationService([failing, working], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [200.0]
    assert working.calls == [[(55.0, 37.0)]]


def test_get_elevations_returns_none_when_all_providers_fail(tmp_path):
    """Review Focus #2: no crash, no exception — just None for that point."""
    service = ElevationService(
        [_FakeProvider("p1", fail=True), _FakeProvider("p2", fail=True)],
        cache_path=tmp_path / "elevation.json",
    )

    result = service.get_elevations([(55.0, 37.0), (56.0, 38.0)])

    assert result == [None, None]


def test_get_elevations_uses_cache_and_does_not_call_provider_again(tmp_path):
    provider = _FakeProvider("p1", responses={(55.0, 37.0): 100.0})
    cache_path = tmp_path / "elevation.json"

    ElevationService([provider], cache_path=cache_path).get_elevations([(55.0, 37.0)])
    provider.calls.clear()
    second_service = ElevationService([provider], cache_path=cache_path)
    result = second_service.get_elevations([(55.0, 37.0)])

    assert result == [100.0]
    assert provider.calls == []


def test_get_elevations_splits_requests_into_max_batch_chunks(tmp_path):
    provider = _FakeProvider("p1", max_batch=2, responses={
        (1.0, 1.0): 1.0, (2.0, 2.0): 2.0, (3.0, 3.0): 3.0,
    })
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)])

    assert result == [1.0, 2.0, 3.0]
    assert len(provider.calls) == 2
    assert len(provider.calls[0]) == 2
    assert len(provider.calls[1]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elevation_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'ElevationService'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/elevation/__init__.py
"""Public entry point for elevation lookups — the only thing the rest of
the skill imports from this package (spec §3.8). Orchestrates cache,
batching, per-provider rate limiting, and failover across providers."""
import time
from pathlib import Path

from .cache import cache_key, load_cache, save_entry

DEFAULT_DATASET = "srtm90m"


class ElevationService:
    def __init__(self, providers: list, cache_path: Path, dataset: str = DEFAULT_DATASET):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._dataset = dataset
        self._cache = load_cache(self._cache_path)
        self._last_call_time: dict[str, float] = {}

    def get_elevations(self, locations: list[tuple[float, float]]) -> list[float | None]:
        results: list[float | None] = [None] * len(locations)
        pending_indices = []
        for i, (lat, lon) in enumerate(locations):
            key = cache_key(lat, lon, self._dataset)
            if key in self._cache:
                results[i] = self._cache[key]["elevation"]
            else:
                pending_indices.append(i)

        for provider in self._providers:
            if not pending_indices:
                break
            still_pending = []
            for batch_indices in self._chunk(pending_indices, provider.max_batch):
                batch_locations = [locations[i] for i in batch_indices]
                self._respect_rate_limit(provider)
                batch_results = provider.fetch(batch_locations)
                for idx, elevation in zip(batch_indices, batch_results):
                    if elevation is None:
                        still_pending.append(idx)
                        continue
                    results[idx] = elevation
                    lat, lon = locations[idx]
                    key = cache_key(lat, lon, self._dataset)
                    save_entry(self._cache_path, self._cache, key, elevation,
                               provider.provider_id, self._dataset)
            pending_indices = still_pending

        return results

    def _respect_rate_limit(self, provider) -> None:
        min_interval = 1.0 / provider.rate_limit_per_sec
        last = self._last_call_time.get(provider.provider_id, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time[provider.provider_id] = time.monotonic()

    @staticmethod
    def _chunk(indices: list[int], size: int):
        for i in range(0, len(indices), size):
            yield indices[i:i + size]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_elevation_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/elevation/__init__.py skills/osm-day-route-planning/tests/test_elevation_service.py
git commit -m "Add ElevationService: cache-first, batched, rate-limited failover (Review Focus #2)"
```

---

## Task 14: Path sampling and elevation interpolation

**Files:**
- Create: `skills/osm-day-route-planning/scripts/elevation/resample.py`
- Test: `skills/osm-day-route-planning/tests/test_resample.py`

**Interfaces:**
- Consumes: `overpass_query.haversine` (Task 1).
- Produces: `elevation.resample.cumulative_distances(coords: list[tuple[float, float]]) -> list[float]`, `elevation.resample.sample_positions(coords: list[tuple[float, float]], interval_m: float = 150.0) -> list[tuple[float, float, float]]` (each item `(lat, lon, dist_m)`), `elevation.resample.interpolate_at_distances(sample_dists: list[float], sample_elevations: list[float], target_dists: list[float]) -> list[float]`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_resample.py
import pytest
from elevation.resample import cumulative_distances, sample_positions, interpolate_at_distances


def test_cumulative_distances_starts_at_zero_and_is_nondecreasing():
    coords = [(55.0, 37.0), (55.001, 37.0), (55.002, 37.0)]
    dists = cumulative_distances(coords)

    assert dists[0] == 0.0
    assert dists[1] < dists[2]


def test_sample_positions_always_includes_start_and_end():
    coords = [(55.0, 37.0), (55.01, 37.0)]  # roughly 1.1 km

    samples = sample_positions(coords, interval_m=150.0)

    assert samples[0][2] == pytest.approx(0.0)
    total = cumulative_distances(coords)[-1]
    assert samples[-1][2] == pytest.approx(total)


def test_sample_positions_spacing_is_close_to_requested_interval():
    coords = [(55.0, 37.0), (55.01, 37.0)]

    samples = sample_positions(coords, interval_m=150.0)
    gaps = [b[2] - a[2] for a, b in zip(samples, samples[1:])]

    assert all(gap <= 200.0 for gap in gaps)  # generous tolerance around 150m


def test_interpolate_at_distances_is_linear_between_samples():
    sample_dists = [0.0, 100.0, 200.0]
    sample_elevations = [10.0, 20.0, 10.0]

    result = interpolate_at_distances(sample_dists, sample_elevations, [0.0, 50.0, 100.0, 150.0, 200.0])

    assert result == pytest.approx([10.0, 15.0, 20.0, 15.0, 10.0])


def test_interpolate_clamps_targets_outside_sample_range():
    result = interpolate_at_distances([0.0, 100.0], [5.0, 15.0], [-10.0, 110.0])
    assert result == pytest.approx([5.0, 15.0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_resample.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'elevation.resample'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/elevation/resample.py
"""Samples a path's geometry at ~150m intervals for elevation lookups
instead of every graph node (5-20m apart — finer than any elevation
dataset's own 30-90m resolution, see spec §3.8), then interpolates back
to each original node's position."""
from overpass_query import haversine


def cumulative_distances(coords: list[tuple[float, float]]) -> list[float]:
    dists = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
        dists.append(dists[-1] + haversine(lat1, lon1, lat2, lon2))
    return dists


def sample_positions(coords: list[tuple[float, float]], interval_m: float = 150.0):
    """Returns [(lat, lon, dist_m), ...] including both endpoints."""
    cum = cumulative_distances(coords)
    total = cum[-1]
    if total == 0.0:
        lat, lon = coords[0]
        return [(lat, lon, 0.0)]

    target_dists = [0.0]
    d = interval_m
    while d < total:
        target_dists.append(d)
        d += interval_m
    if target_dists[-1] != total:
        target_dists.append(total)

    samples = []
    seg = 0
    for target in target_dists:
        while seg < len(cum) - 2 and cum[seg + 1] < target:
            seg += 1
        lat1, lon1 = coords[seg]
        lat2, lon2 = coords[seg + 1]
        seg_len = cum[seg + 1] - cum[seg]
        frac = 0.0 if seg_len == 0 else (target - cum[seg]) / seg_len
        lat = lat1 + (lat2 - lat1) * frac
        lon = lon1 + (lon2 - lon1) * frac
        samples.append((lat, lon, target))
    return samples


def interpolate_at_distances(sample_dists: list[float], sample_elevations: list[float],
                              target_dists: list[float]) -> list[float]:
    """Linear interpolation of elevation at arbitrary distances-along-path,
    given known elevations at sample_dists. Targets outside the sampled
    range clamp to the nearest endpoint rather than extrapolating."""
    results = []
    for target in target_dists:
        if target <= sample_dists[0]:
            results.append(sample_elevations[0])
            continue
        if target >= sample_dists[-1]:
            results.append(sample_elevations[-1])
            continue
        i = 0
        while sample_dists[i + 1] < target:
            i += 1
        d0, d1 = sample_dists[i], sample_dists[i + 1]
        e0, e1 = sample_elevations[i], sample_elevations[i + 1]
        frac = 0.0 if d1 == d0 else (target - d0) / (d1 - d0)
        results.append(e0 + (e1 - e0) * frac)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_resample.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/elevation/resample.py skills/osm-day-route-planning/tests/test_resample.py
git commit -m "Add path sampling and elevation interpolation"
```

---

## Task 15: Restricted-zone waypoint validation (Review Focus #1)

**Files:**
- Create: `skills/osm-day-route-planning/scripts/waypoints.py`
- Test: `skills/osm-day-route-planning/tests/test_waypoints.py`

**Interfaces:**
- Consumes: `route_graph.point_in_ring` (Task 8).
- Produces: `waypoints.is_point_restricted(lat: float, lon: float, restricted_polygons: list) -> bool`, `waypoints.RestrictedWaypointError(Exception)`, `waypoints.validate_user_waypoint(lat: float, lon: float, name: str, restricted_polygons: list) -> None` (raises `RestrictedWaypointError` with a human-readable message when inside a restricted zone; returns `None` otherwise).

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_waypoints.py
import pytest
from waypoints import is_point_restricted, validate_user_waypoint, RestrictedWaypointError

_SQUARE_RING = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]


def test_is_point_restricted_true_when_inside_polygon():
    assert is_point_restricted(0.5, 0.5, [_SQUARE_RING]) is True


def test_is_point_restricted_false_when_outside_all_polygons():
    assert is_point_restricted(5.0, 5.0, [_SQUARE_RING]) is False


def test_is_point_restricted_false_when_no_polygons():
    assert is_point_restricted(0.5, 0.5, []) is False


def test_validate_user_waypoint_raises_with_point_name_in_message():
    with pytest.raises(RestrictedWaypointError) as exc_info:
        validate_user_waypoint(0.5, 0.5, "Военная часть", [_SQUARE_RING])

    assert "Военная часть" in str(exc_info.value)


def test_validate_user_waypoint_passes_silently_when_outside():
    validate_user_waypoint(5.0, 5.0, "Смотровая площадка", [_SQUARE_RING])  # no exception
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_waypoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'waypoints'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/waypoints.py
"""Waypoint-level checks that run BEFORE the graph is built (spec §3.4):
a restricted-zone hit here must become an explicit message, never a
silent 'no path found' surfaced later from the router."""
from route_graph import point_in_ring


class RestrictedWaypointError(Exception):
    pass


def is_point_restricted(lat: float, lon: float, restricted_polygons: list) -> bool:
    return any(point_in_ring(lat, lon, ring) for ring in restricted_polygons)


def validate_user_waypoint(lat: float, lon: float, name: str, restricted_polygons: list) -> None:
    """Raises for a USER-supplied point (spec §3.4: 'скилл прямо сообщает
    пользователю, что не может построить маршрут через эту точку, и
    почему'). A skill-CHOSEN candidate should be filtered out with
    is_point_restricted before ever reaching this function — see SKILL.md."""
    if is_point_restricted(lat, lon, restricted_polygons):
        raise RestrictedWaypointError(
            f"Не могу построить маршрут через точку «{name}» — она находится "
            "в закрытой/охраняемой зоне (военный объект, частная территория "
            "или огороженный периметр)."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_waypoints.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/waypoints.py skills/osm-day-route-planning/tests/test_waypoints.py
git commit -m "Add restricted-zone waypoint validation (Review Focus #1)"
```

---

## Task 16: Budget-constrained optional-point selection (Review Focus #3)

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/waypoints.py`
- Test: `skills/osm-day-route-planning/tests/test_waypoints.py`

**Interfaces:**
- Consumes: `route_graph.weighted_shortest_path` (existing), `route_graph.route_through_waypoints` (existing).
- Produces: `waypoints.BudgetExceededError(Exception)`, `waypoints.check_mandatory_budget(mandatory_cost_km: float, max_distance_km: float | None) -> None` (raises when the mandatory-only route alone exceeds the budget), `waypoints.select_optional_points(graph: dict, mandatory_path: list[int], mandatory_cost_km: float, candidates: list[dict], preferences: dict, max_distance_km: float | None) -> tuple[list[dict], list[str]]` — returns `(included, skipped_names)`; each candidate dict has `"node_id"`, `"name"`, `"tier"` keys.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-planning/tests/test_waypoints.py
from waypoints import BudgetExceededError, check_mandatory_budget, select_optional_points


def test_check_mandatory_budget_raises_when_already_over_budget():
    with pytest.raises(BudgetExceededError):
        check_mandatory_budget(mandatory_cost_km=12.0, max_distance_km=10.0)


def test_check_mandatory_budget_passes_when_no_budget_set():
    check_mandatory_budget(mandatory_cost_km=999.0, max_distance_km=None)  # no exception


def test_check_mandatory_budget_passes_when_within_budget():
    check_mandatory_budget(mandatory_cost_km=8.0, max_distance_km=10.0)  # no exception


def _linear_graph():
    """1 -- 2 -- 3 is the mandatory path (2km total); node 4 sits 0.1km
    off node 2, node 5 sits 5km off node 3 (too far to afford)."""
    return {
        1: [[2, 1000.0, {}]], 2: [[1, 1000.0, {}], [3, 1000.0, {}], [4, 100.0, {}]],
        3: [[2, 1000.0, {}], [5, 5000.0, {}]], 4: [[2, 100.0, {}]], 5: [[3, 5000.0, {}]],
    }


def test_select_optional_points_includes_cheap_candidate_within_budget():
    graph = _linear_graph()
    candidates = [{"node_id": 4, "name": "Родник", "tier": "tag-backed"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=2.5,
    )

    assert [c["name"] for c in included] == ["Родник"]
    assert skipped == []


def test_select_optional_points_skips_candidate_that_would_exceed_budget():
    graph = _linear_graph()
    candidates = [{"node_id": 5, "name": "Дальний вид", "tier": "web-sourced"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=3.0,
    )

    assert included == []
    assert skipped == ["Дальний вид"]


def test_select_optional_points_prefers_tag_backed_on_tied_cost():
    graph = _linear_graph()
    candidates = [
        {"node_id": 4, "name": "Веб-точка", "tier": "web-sourced"},
    ]
    # Only one affordable slot conceptually tested via budget; tie-break
    # ordering itself is exercised by sorting two equal-cost candidates.
    graph[2].append([6, 100.0, {}])
    graph[6] = [[2, 100.0, {}]]
    candidates.append({"node_id": 6, "name": "OSM-точка", "tier": "tag-backed"})

    included, skipped = select_optional_points(
        graph, mandatory_path=[1, 2, 3], mandatory_cost_km=2.0,
        candidates=candidates, preferences={}, max_distance_km=2.25,
    )

    # Budget only fits one 0.2km round-trip detour; tag-backed wins the tie.
    assert [c["name"] for c in included] == ["OSM-точка"]


def test_select_optional_points_handles_single_node_mandatory_path():
    """A bare loop with no mandatory point besides the access point yet —
    the only possible insertion is a there-and-back detour."""
    graph = {1: [[2, 100.0, {}]], 2: [[1, 100.0, {}]]}
    candidates = [{"node_id": 2, "name": "Рядом", "tier": "tag-backed"}]

    included, skipped = select_optional_points(
        graph, mandatory_path=[1], mandatory_cost_km=0.0,
        candidates=candidates, preferences={}, max_distance_km=1.0,
    )

    assert [c["name"] for c in included] == ["Рядом"]
    assert skipped == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_waypoints.py -v`
Expected: FAIL with `ImportError: cannot import name 'BudgetExceededError'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to skills/osm-day-route-planning/scripts/waypoints.py
from route_graph import weighted_shortest_path

_TIER_RANK = {"tag-backed": 0, "web-sourced": 1, "derived": 2, "no-data": 3}


class BudgetExceededError(Exception):
    pass


def check_mandatory_budget(mandatory_cost_km: float, max_distance_km: float | None) -> None:
    if max_distance_km is not None and mandatory_cost_km > max_distance_km:
        raise BudgetExceededError(
            f"Маршрут только по обязательным точкам уже {mandatory_cost_km:.1f} км — "
            f"это больше заданного ограничения {max_distance_km:.1f} км. "
            "Увеличьте бюджет или откажитесь от одной из обязательных точек."
        )


def _cheapest_insertion_cost_km(graph, path: list[int], candidate_node: int, preferences: dict) -> float:
    """Cost (km) of visiting candidate_node via the cheapest detour between
    any two consecutive nodes already in `path`. When `path` has a single
    node (a bare loop with no other mandatory point yet), the only
    'insertion' possible is a there-and-back detour off that one node."""
    if len(path) == 1:
        _, there = weighted_shortest_path(graph, path[0], candidate_node, preferences)
        return None if there is None else 2 * there / 1000.0

    best = None
    for a, b in zip(path, path[1:]):
        _, cost_to = weighted_shortest_path(graph, a, candidate_node, preferences)
        _, cost_from = weighted_shortest_path(graph, candidate_node, b, preferences)
        _, direct = weighted_shortest_path(graph, a, b, preferences)
        if cost_to is None or cost_from is None:
            continue
        direct = direct or 0.0
        detour = (cost_to + cost_from - direct) / 1000.0
        if best is None or detour < best:
            best = detour
    return best


def select_optional_points(graph, mandatory_path: list[int], mandatory_cost_km: float,
                            candidates: list[dict], preferences: dict,
                            max_distance_km: float | None):
    """Greedy cheapest-insertion selection under a distance budget (spec
    §3.5 step 3). Candidates unreachable from the mandatory path are
    treated as skipped, same as ones that don't fit the budget."""
    if max_distance_km is None:
        remaining_budget = float("inf")
    else:
        remaining_budget = max_distance_km - mandatory_cost_km

    scored = []
    for candidate in candidates:
        cost_km = _cheapest_insertion_cost_km(graph, mandatory_path, candidate["node_id"], preferences)
        if cost_km is not None:
            scored.append((cost_km, _TIER_RANK.get(candidate.get("tier"), 99), candidate))
    scored.sort(key=lambda item: (item[0], item[1]))

    included, skipped = [], []
    for cost_km, _rank, candidate in scored:
        if cost_km <= remaining_budget:
            included.append(candidate)
            remaining_budget -= cost_km
        else:
            skipped.append(candidate["name"])
    unreachable = {c["name"] for c in candidates} - {c["name"] for c in included} - set(skipped)
    skipped.extend(sorted(unreachable))
    return included, skipped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_waypoints.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/waypoints.py skills/osm-day-route-planning/tests/test_waypoints.py
git commit -m "Add budget-constrained optional-point selection (Review Focus #3)"
```

---

## Task 17: Duration estimate and the soft daylight warning

**Files:**
- Create: `skills/osm-day-route-planning/scripts/duration.py`
- Test: `skills/osm-day-route-planning/tests/test_duration.py`

**Interfaces:**
- Produces: `duration.estimate_duration_hours(distance_km: float, elevation_gain_m: float, pace_kmh: float, ascent_minutes_per_100m: float) -> float`, `duration.duration_warning(estimated_hours: float, duration_warning_hours: float) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_duration.py
import pytest
from duration import estimate_duration_hours, duration_warning


def test_estimate_duration_flat_route_uses_pace_only():
    hours = estimate_duration_hours(distance_km=10.0, elevation_gain_m=0.0,
                                     pace_kmh=5.0, ascent_minutes_per_100m=10.0)
    assert hours == pytest.approx(2.0)


def test_estimate_duration_adds_ascent_penalty():
    flat = estimate_duration_hours(10.0, 0.0, pace_kmh=5.0, ascent_minutes_per_100m=10.0)
    with_climb = estimate_duration_hours(10.0, 500.0, pace_kmh=5.0, ascent_minutes_per_100m=10.0)

    # 500m of ascent at 10 min/100m = 50 extra minutes = 0.833h
    assert with_climb - flat == pytest.approx(50 / 60, rel=1e-3)


def test_duration_warning_none_when_under_threshold():
    assert duration_warning(estimated_hours=5.0, duration_warning_hours=10.0) is None


def test_duration_warning_present_when_over_threshold():
    message = duration_warning(estimated_hours=13.0, duration_warning_hours=10.0)
    assert message is not None
    assert "световой день" in message


def test_duration_warning_present_even_when_over_24_hours():
    """Spec §3.9: still just a soft warning, never a hard block."""
    message = duration_warning(estimated_hours=30.0, duration_warning_hours=10.0)
    assert message is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_duration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'duration'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/duration.py
"""Duration estimate (pace + Naismith-style ascent penalty, spec §3.9) and
the soft daylight-fit warning. The warning is heuristic and never blocks
route construction — a precise seasonal check is osm-day-route-prepare's
job, not this skill's."""


def estimate_duration_hours(distance_km: float, elevation_gain_m: float,
                             pace_kmh: float, ascent_minutes_per_100m: float) -> float:
    base_hours = distance_km / pace_kmh
    ascent_hours = (elevation_gain_m / 100.0) * ascent_minutes_per_100m / 60.0
    return base_hours + ascent_hours


def duration_warning(estimated_hours: float, duration_warning_hours: float) -> str | None:
    if estimated_hours <= duration_warning_hours:
        return None
    return (
        f"Оценка времени в пути (~{estimated_hours:.1f} ч) превышает {duration_warning_hours:.0f} ч — "
        "маршрут может не влезть в световой день в зависимости от сезона и широты. "
        "Для точной проверки по конкретной дате используйте osm-day-route-prepare."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_duration.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/duration.py skills/osm-day-route-planning/tests/test_duration.py
git commit -m "Add duration estimate and soft daylight-fit warning"
```

---

## Task 18: Curated-route counter

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/overpass_query.py`
- Test: `skills/osm-day-route-planning/tests/test_overpass_query.py`

**Interfaces:**
- Produces: `overpass_query.build_curated_routes_query(lat: float, lon: float, radius_m: int, route_tags: list[str]) -> str`, `overpass_query.count_curated_routes(result: dict) -> int` (counts `relation` elements in an Overpass JSON result — kept separate from the network call so it's testable without mocking HTTP).

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-planning/tests/test_overpass_query.py
from overpass_query import build_curated_routes_query, count_curated_routes


def test_build_curated_routes_query_includes_tags_and_radius():
    ql = build_curated_routes_query(55.0, 37.0, radius_m=2000, route_tags=["hiking", "foot"])

    assert "hiking|foot" in ql
    assert "2000" in ql
    assert "relation" in ql


def test_count_curated_routes_counts_relation_elements_only():
    result = {"elements": [
        {"type": "relation", "id": 1}, {"type": "relation", "id": 2}, {"type": "way", "id": 3},
    ]}

    assert count_curated_routes(result) == 2


def test_count_curated_routes_zero_when_no_elements():
    assert count_curated_routes({"elements": []}) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_overpass_query.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_curated_routes_query'`

- [ ] **Step 3: Write the minimal implementation**

```python
# append to skills/osm-day-route-planning/scripts/overpass_query.py
def build_curated_routes_query(lat: float, lon: float, radius_m: int, route_tags: list[str]) -> str:
    """spec §3.10 — walk passes route_tags=['hiking','foot'], bike passes
    ['bicycle','mtb']. Geometry is never used, only the count, so this
    query only asks Overpass to count, not to return full geometry."""
    tags_pattern = "|".join(route_tags)
    return f"""
    [out:json][timeout:25];
    relation["route"~"{tags_pattern}"](around:{radius_m},{lat},{lon});
    out count;
    """


def count_curated_routes(result: dict) -> int:
    return sum(1 for el in result.get("elements", []) if el.get("type") == "relation")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_overpass_query.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/overpass_query.py skills/osm-day-route-planning/tests/test_overpass_query.py
git commit -m "Add curated-route counter query and counting helper"
```

---

## Task 19: `route_output` — assemble the `route.geojson` with all new properties

**Files:**
- Create: `skills/osm-day-route-planning/scripts/route_output.py`
- Test: `skills/osm-day-route-planning/tests/test_route_output.py`

**Interfaces:**
- Produces: `route_output.build_geojson(path_coords: list[tuple[float, float, float]], route_name: str, mode: str, style: str | None, distance_km: float, elevation_gain_m: float, elevation_loss_m: float, duration_estimate_hours: float, duration_warning: str | None, curated_routes_count: int, is_loop: bool, skipped_interest_points: list[str], point_features: list[dict]) -> dict`. Each item of `point_features` is `{"lon": float, "lat": float, "ele": float | None, "name": str, "type": str, "tier": str | None, "role": str | None, "note": str | None, "source": str | None, "osm_id": str | None, "wikidata": str | None, "wikipedia": str | None, "search_names": dict | None, "opening_hours": str | None, "access_notes": str | None}` — only non-`None` optional keys are written into the feature's `properties`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-planning/tests/test_route_output.py
from route_output import build_geojson


def _sample_call(**overrides):
    kwargs = dict(
        path_coords=[(37.0, 55.0, 100.0), (37.001, 55.001, 110.0)],
        route_name="Тестовый маршрут",
        mode="bike", style="leisure",
        distance_km=5.2, elevation_gain_m=10.0, elevation_loss_m=0.0,
        duration_estimate_hours=1.1, duration_warning=None,
        curated_routes_count=3, is_loop=True,
        skipped_interest_points=["Дальняя точка"],
        point_features=[{
            "lon": 37.0005, "lat": 55.0005, "ele": 105.0,
            "name": "Родник", "type": "spring", "tier": "tag-backed",
            "role": None, "note": None, "source": None, "osm_id": "node/1",
            "wikidata": None, "wikipedia": None, "search_names": None,
            "opening_hours": None, "access_notes": None,
        }],
    )
    kwargs.update(overrides)
    return build_geojson(**kwargs)


def test_linestring_coordinates_are_3d():
    result = _sample_call()
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert line["geometry"]["coordinates"] == [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0]]


def test_linestring_carries_all_computed_properties():
    result = _sample_call()
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    props = line["properties"]

    assert props["name"] == "Тестовый маршрут"
    assert props["mode"] == "bike"
    assert props["style"] == "leisure"
    assert props["distance_km"] == 5.2
    assert props["elevation_gain_m"] == 10.0
    assert props["elevation_loss_m"] == 0.0
    assert props["duration_estimate_hours"] == 1.1
    assert props["duration_warning"] is None
    assert props["curated_routes_count"] == 3
    assert props["is_loop"] is True
    assert props["skipped_interest_points"] == ["Дальняя точка"]


def test_point_feature_omits_none_optional_properties():
    result = _sample_call()
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")

    assert point["geometry"]["coordinates"] == [37.0005, 55.0005, 105.0]
    assert point["properties"]["name"] == "Родник"
    assert point["properties"]["osm_id"] == "node/1"
    assert "wikidata" not in point["properties"]
    assert "opening_hours" not in point["properties"]


def test_access_point_keeps_opening_hours_and_access_notes_when_present():
    result = _sample_call(point_features=[{
        "lon": 37.0, "lat": 55.0, "ele": None,
        "name": "Станция Бажуково", "type": "access", "tier": None,
        "role": "start", "note": None, "source": None, "osm_id": "node/2",
        "wikidata": None, "wikipedia": None, "search_names": None,
        "opening_hours": "Mo-Su 06:00-23:00", "access_notes": "Билеты у кондуктора.",
    }])
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")

    assert point["properties"]["opening_hours"] == "Mo-Su 06:00-23:00"
    assert point["properties"]["access_notes"] == "Билеты у кондуктора."
    assert point["geometry"]["coordinates"] == [37.0, 55.0]  # no ele known for this point
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_route_output.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'route_output'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-planning/scripts/route_output.py
"""Assembles route.geojson per the extended schema in spec §3.11: 3D
coordinates, and LineString properties that hold computed OUTPUTS only
(never duplicating weights.json's inputs)."""

_OPTIONAL_POINT_KEYS = (
    "note", "source", "osm_id", "wikidata", "wikipedia", "search_names",
    "opening_hours", "access_notes",
)


def _point_feature(pf: dict) -> dict:
    coords = [pf["lon"], pf["lat"]]
    if pf.get("ele") is not None:
        coords.append(pf["ele"])
    properties = {"name": pf["name"], "type": pf["type"]}
    if pf.get("tier") is not None:
        properties["tier"] = pf["tier"]
    if pf.get("role") is not None:
        properties["role"] = pf["role"]
    for key in _OPTIONAL_POINT_KEYS:
        if pf.get(key) is not None:
            properties[key] = pf[key]
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": coords}, "properties": properties}


def build_geojson(path_coords, route_name, mode, style, distance_km, elevation_gain_m,
                   elevation_loss_m, duration_estimate_hours, duration_warning,
                   curated_routes_count, is_loop, skipped_interest_points, point_features):
    line_feature = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat, ele] for lon, lat, ele in path_coords],
        },
        "properties": {
            "name": route_name,
            "mode": mode,
            "style": style,
            "distance_km": distance_km,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "duration_estimate_hours": duration_estimate_hours,
            "duration_warning": duration_warning,
            "curated_routes_count": curated_routes_count,
            "is_loop": is_loop,
            "skipped_interest_points": skipped_interest_points,
        },
    }
    features = [line_feature] + [_point_feature(pf) for pf in point_features]
    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_route_output.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/route_output.py skills/osm-day-route-planning/tests/test_route_output.py
git commit -m "Add route_output.build_geojson with the extended §3.11 schema"
```

---

## Task 20: `SKILL.md` and `reference.md` for `osm-day-route-planning`

**Files:**
- Create: `skills/osm-day-route-planning/SKILL.md` (adapted from `init-raw-source/osm-hike-route-planning/SKILL.md`)
- Create: `skills/osm-day-route-planning/reference.md` (copied from `init-raw-source/osm-hike-route-planning/reference.md`, tag tables updated for bike)

This task has no automated test — a `SKILL.md` is read by Claude, not executed. The "test" is a documentation completeness checklist run by hand.

- [ ] **Step 1: Copy `reference.md` as a starting point**

```bash
cp /mnt/data/pavel/work/osm-hike-route/init-raw-source/osm-hike-route-planning/reference.md \
   /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-planning/reference.md
```

- [ ] **Step 2: Write `SKILL.md`, adapting the existing pipeline to this plan's modules**

Base it on `init-raw-source/osm-hike-route-planning/SKILL.md`, keeping its structure (Overview, When to Use, Pipeline, Interest-Layer Confidence Tiers, Access Exclusion, Core Pattern, Archive, Output Format, Quick Reference, Common Mistakes) and updating it to fold in every module built in Tasks 1-19:

- Frontmatter `name: osm-day-route-planning`, `description:` mentioning both walking and cycling, required stops, access points ("точки заброски"), and a distance/duration budget.
- **Pipeline** section: add explicit steps for (a) saving the verbatim request via `requests_log.append_request` before anything else, (b) asking mode/style (`presets.load_preset`) when not stated, (c) asking loop-vs-point-to-point when not stated, (d) resolving access points, (e) resolving interest points (skill-chosen and/or user-given) with a location-research web-search pass keyed to the user's stated interests, (f) validating every waypoint with `waypoints.validate_user_waypoint`/`waypoints.is_point_restricted` before building the graph, (g) asking for the distance/duration budget when not stated, (h) building the directed graph (`route_graph.build_graph` with the chosen preset's tag rules), (i) fetching elevation via `elevation.ElevationService`, sampling via `elevation.resample`, tagging grades via `route_graph.tag_grades`, (j) solving the mandatory-only route and checking `waypoints.check_mandatory_budget`, (k) adding optional points via `waypoints.select_optional_points`, (l) computing `duration.estimate_duration_hours`/`duration.duration_warning`, (m) counting curated routes via `overpass_query.count_curated_routes`, (n) writing the archive: `weights_io.save_weights`, `route_output.build_geojson`, `notes.md`.
- **Revising an existing route** section (new): when a request refers to an existing archive, load its `weights.json`, call `presets.revise_weights` with only the changed fields, append the new request via `requests_log.append_request`, and re-run only the affected steps — cite spec §4.
- **Core Pattern** code example: update the import list to include `presets`, `waypoints`, `elevation`, `duration`, `route_output` alongside the existing `overpass_query`/`route_graph` imports, and show `build_graph(..., respect_oneway=(mode == "bike"))`. Include the elevation-to-graph wiring explicitly, since it is the one place three separately-tested modules (Tasks 12-14) combine into something none of them tests end-to-end on its own:

  ```python
  from elevation import ElevationService
  from elevation.resample import sample_positions, cumulative_distances, interpolate_at_distances
  from elevation.providers.open_topo_data import OpenTopoDataProvider
  from elevation.providers.open_meteo import OpenMeteoProvider
  from elevation.providers.elevation_api_eu import ElevationApiEuProvider
  from elevation.providers.open_elevation import OpenElevationProvider

  service = ElevationService(
      [OpenTopoDataProvider(), OpenMeteoProvider(), ElevationApiEuProvider(), OpenElevationProvider()],
      cache_path=Path("routes/.cache/elevation.json"),
  )

  def compute_node_elevations(ways: list[dict]) -> dict[int, float]:
      """One dict entry per OSM node id touched by any way, interpolated
      from ~150m samples along that way (spec §3.8) — never a per-node
      elevation lookup."""
      node_elevations: dict[int, float] = {}
      for way in ways:
          ids, geom = way["nodes"], way["geometry"]
          coords = [(pt["lat"], pt["lon"]) for pt in geom]
          samples = sample_positions(coords, interval_m=150.0)
          sample_elevations = service.get_elevations([(lat, lon) for lat, lon, _ in samples])
          sample_dists = [dist for _, _, dist in samples]
          node_dists = cumulative_distances(coords)
          # A sample with no elevation from any provider (Review Focus #2)
          # falls back to 0.0 here — tag_grades then sees grade_pct=0.0,
          # i.e. no gradient penalty, not a crash.
          clean_elevations = [e if e is not None else 0.0 for e in sample_elevations]
          for node_id, elevation in zip(ids, interpolate_at_distances(sample_dists, clean_elevations, node_dists)):
              node_elevations[node_id] = elevation
      return node_elevations
  ```
- **Quick Reference** table: add the bike-specific rows (`cycleway`, `oneway:bicycle`, `bicycle=no|dismount`, `highway=steps` exclusion).
- **Common Mistakes**: add the five Review Focus items from this plan's header, phrased as mistakes to avoid (mirrors the existing file's own style).

- [ ] **Step 3: Read the finished `SKILL.md` back and check it against this plan's Global Constraints and Review Focus lists**

Confirm each Global Constraint and each Review Focus item from this plan's header has at least one corresponding sentence in `SKILL.md` — if one is missing, add it before moving on.

- [ ] **Step 4: Commit**

```bash
git add skills/osm-day-route-planning/SKILL.md skills/osm-day-route-planning/reference.md
git commit -m "Write SKILL.md and reference.md for osm-day-route-planning"
```

---

## Post-plan manual verification (not part of the automated suite)

These need live network access and human judgment, so they are not `pytest` steps — run them once after all 20 tasks are merged, the way the existing skill's Cuatro Vientos check was done:

1. Plan a real `walk` route near a location with a known restricted military zone (reproduce the existing Cuatro Vientos check) — confirm restricted ways are still hard-excluded and the directed-graph change didn't regress it.
2. Plan a real `bike` route (both `leisure` and `sport` style) somewhere with at least one `oneway` street and some elevation change — confirm the route doesn't route the wrong way down the one-way street, and that `elevation_gain_m`/`duration_estimate_hours` look plausible.
3. Confirm at least one of the four elevation providers is reachable from this environment (a fully offline sandbox would make `ElevationService` legitimately return all-`None`, which is correct behavior per Task 13 but worth knowing about ahead of time).

---

**Plan complete and saved to `docs/superpowers/plans/2026-09-28-osm-day-route-planning.md`.**
