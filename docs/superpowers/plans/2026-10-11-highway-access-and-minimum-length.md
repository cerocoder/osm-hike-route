# Highway Access and Minimum Route Length Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TODO 9 (highway types for bike and walk presets) and TODO 10 (minimum route length and questions to the user).

**Architecture:** Presets get new keys. The graph marks edges that are "fallback" ways and raises their cost by a large factor, so the router uses them only when no other link exists. Steps get a cost penalty for bikes. A new length-range resolver and two checks in `waypoints.py` stop a too-short route. `archive_validate` rejects a saved route shorter than the minimum stored in `weights.json`.

**Tech Stack:** Python 3 standard library, pytest. All code is in `skills/osm-day-route-planning/`.

**Spec:** TODO items 9 and 10 in `/TODO`; `docs/research/2026-10-11-highway-types-and-access.md`; `docs/superpowers/specs/2026-09-28-osm-day-route-planning-show-design.md` (§3.5, §3.6 are updated by Task 7).

## Global Constraints

- Specs and plans in English (ASD-STE100). User-facing runtime messages stay in Russian, as in the existing code.
- Version: new feature -> raise the middle part (0.2.1 -> 0.3.0) in `.claude-plugin/plugin.json`; add a line to `Changelog` before any push.
- `pytest` in `skills/osm-day-route-planning` passes (477 tests at start).
- Old archives (no `min_distance_km` in `weights.json`) must still validate.

## Review Focus

- A bike route over a `service` way when a normal way exists: the router must take the normal way.
- A `footway` with `bicycle=yes` must be a normal way, without it a fallback way.
- `steps` with `bicycle=dismount` must stay in the graph for bikes (a rider pushes the bike); `bicycle=no` still drops it.
- A request with only a maximum gives a minimum of half of it; no length at all raises an error.
- Archive without the minimum keys in `weights.json` still passes.

---

### Task 1: Fallback ways, steps and explicit-bicycle rule in the graph

**Files:**
- Modify: `scripts/route_graph.py` (`filter_excluded_ways`, `build_graph`, `_edge_cost`, new `special_segments`)
- Test: `tests/test_route_graph.py`

**Interfaces:**
- Produces: `build_graph(..., fallback_highway=(), bicycle_explicit_highway=())`; edge tag `fallback: bool`; way description key `"fallback": True`; `_edge_cost` reads preferences `fallback_way_cost` (default 1.0) and `steps_cost` (default 1.0); `special_segments(way_segments) -> {"steps": [...], "fallback": [...]}`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_route_graph.py`)

```python
def _edge_tags(graph, a, b):
    return next(e[2] for e in graph[a] if e[0] == b)


def test_fallback_highway_marks_edge_and_description():
    graph, _ = build_graph(_two_node_way(tags={"highway": "service"}), fallback_highway=("service", "road"))
    tags = _edge_tags(graph, 1, 2)
    assert tags["fallback"] is True
    assert tags["way"]["fallback"] is True


def test_other_highway_is_not_fallback():
    graph, _ = build_graph(_two_node_way(tags={"highway": "track"}), fallback_highway=("service",))
    assert _edge_tags(graph, 1, 2)["fallback"] is False
    assert "fallback" not in _edge_tags(graph, 1, 2)["way"]


@pytest.mark.parametrize("bicycle,fallback", [("yes", False), ("designated", False), (None, True), ("permissive", True)])
def test_footway_needs_explicit_bicycle_tag(bicycle, fallback):
    tags = {"highway": "footway"}
    if bicycle:
        tags["bicycle"] = bicycle
    graph, _ = build_graph(_two_node_way(tags=tags), bicycle_explicit_highway=("footway", "pedestrian"))
    assert _edge_tags(graph, 1, 2)["fallback"] is fallback


def test_router_takes_the_normal_way_over_a_shorter_fallback_way():
    # 1 -> 2 direct by service (100 m), 1 -> 3 -> 2 by track (150 m)
    graph = {1: [[2, 100.0, {"fallback": True}], [3, 75.0, {}]], 2: [], 3: [[2, 75.0, {}]]}
    path, _ = route_graph.weighted_shortest_path(graph, 1, 2, {"fallback_way_cost": 1000})
    assert path == [1, 3, 2]


def test_router_uses_a_fallback_way_when_it_is_the_only_link():
    graph = {1: [[2, 100.0, {"fallback": True}]], 2: []}
    path, _ = route_graph.weighted_shortest_path(graph, 1, 2, {"fallback_way_cost": 1000})
    assert path == [1, 2]


def test_steps_cost_factor_applies_only_to_steps():
    prefs = {"steps_cost": 5.0}
    assert route_graph._edge_cost(10.0, {"way": {"highway": "steps"}}, prefs) == 50.0
    assert route_graph._edge_cost(10.0, {"way": {"highway": "path"}}, prefs) == 10.0


def test_bike_steps_with_dismount_stay_but_bicycle_no_is_dropped():
    exclude = {"bicycle": ["no", "dismount"]}
    ways = [_way_with_tags({"highway": "steps", "bicycle": "dismount"}, way_id=1),
            _way_with_tags({"highway": "steps", "bicycle": "no"}, way_id=2),
            _way_with_tags({"highway": "path", "bicycle": "dismount"}, way_id=3)]
    kept = filter_excluded_ways(ways, [], hard_exclude_tags=exclude)
    assert [w["id"] for w in kept] == [1]


def test_special_segments_lists_steps_and_fallback_runs():
    segments = [{"from": 0, "to": 1, "highway": "track"},
                {"from": 1, "to": 2, "highway": "steps"},
                {"from": 2, "to": 3, "highway": "service", "fallback": True}]
    found = route_graph.special_segments(segments)
    assert found["steps"] == [segments[1]]
    assert found["fallback"] == [segments[2]]
```

(`filter_excluded_ways` and `_way_with_tags` are already imported/defined in that test file; check `_way_with_tags` returns a dict with `id`.)

- [ ] **Step 2:** `python3 -m pytest tests/test_route_graph.py -q` -> new tests FAIL.

- [ ] **Step 3: Implement** in `route_graph.py`:

`filter_excluded_ways`: replace the `_has_hard_excluded_tag(tags, hard_exclude_tags)` call by `_is_hard_excluded(tags, hard_exclude_tags)`:

```python
def _is_hard_excluded(tags: dict, hard_exclude_tags: dict) -> bool:
    """steps with bicycle=dismount stay: a rider pushes the bicycle up the steps. bicycle=no on steps still drops them."""
    if tags.get("highway") == "steps" and tags.get("bicycle") == "dismount":
        tags = {k: v for k, v in tags.items() if k != "bicycle"}
    return _has_hard_excluded_tag(tags, hard_exclude_tags)
```

`build_graph(..., fallback_highway=(), bicycle_explicit_highway=())`, per way:

```python
fallback = _is_fallback_way(tags, fallback_highway, bicycle_explicit_highway)
description = _way_description(way)
if fallback:
    description["fallback"] = True
...
graph[a].append([b, length, {"way": description, "fallback": fallback}])   # both directions
```

```python
def _is_fallback_way(tags, fallback_highway, bicycle_explicit_highway) -> bool:
    """A way the router may use only to restore connectivity: a highway type the preset lists as fallback, or a
    footway/pedestrian way without an explicit bicycle=yes|designated."""
    highway = tags.get("highway")
    if highway in fallback_highway:
        return True
    return highway in bicycle_explicit_highway and tags.get("bicycle") not in ("yes", "designated")
```

`_edge_cost`, before the return:

```python
    if tags.get("fallback"):
        cost *= preferences.get("fallback_way_cost", 1.0)
    if tags.get("way", {}).get("highway") == "steps":
        cost *= preferences.get("steps_cost", 1.0)
```

```python
def special_segments(way_segments):
    """Runs of a route that need a note: steps (a rider pushes the bicycle) and fallback ways."""
    return {"steps": [s for s in way_segments if s.get("highway") == "steps"],
            "fallback": [s for s in way_segments if s.get("fallback")]}
```

Update the module docstring typical flow to pass `fallback_highway=weights.get("fallback_highway", ())`, `bicycle_explicit_highway=weights.get("bicycle_explicit_highway", ())`.

- [ ] **Step 4:** run the test file -> PASS. Run the full suite.
- [ ] **Step 5:** commit `route graph: fallback ways, steps cost, explicit bicycle rule`.

### Task 2: Anchored Overpass regex for walkable ways

**Files:** Modify `scripts/route_graph.py` (`fetch_area_data`); Test `tests/test_route_graph.py`.

- [ ] **Step 1:** Change the helper `_walkable_clause_values` in the tests to strip `^(` and `)$`, and add:

```python
def test_walkable_pattern_is_anchored_so_link_values_stay_out():
    captured = []
    with patch.object(route_graph, "query_overpass", side_effect=_capture_ql(captured)):
        fetch_area_data(55.0, 37.0, routable_highway=["tertiary", "primary"])
    match = re.search(r'way\["highway"~"([^"]+)"\]', captured[0])
    assert match.group(1).startswith("^(") and match.group(1).endswith(")$")
    assert "tertiary_link" not in _walkable_clause_values(captured[0])
```

- [ ] **Step 2:** run -> FAIL. **Step 3:** in `fetch_area_data` set `walkable_pattern = "^(" + "|".join(values) + ")$"`. Leave the `.highways` avoidance clause unanchored on purpose (links near the route are still something to avoid); add a one-line comment.
- [ ] **Step 4:** tests pass. **Step 5:** commit `overpass: anchor walkable highway regex`.

### Task 3: Presets

**Files:** Modify `presets/bike-leisure.json`, `presets/bike-sport.json`, `presets/walk.json`; `scripts/presets.py` untouched; Test `tests/test_presets.py`.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("style", ["leisure", "sport"])
def test_bike_presets_allow_the_extra_highway_types(style):
    preset = load_preset("bike", style=style)
    for value in ("tertiary", "unclassified", "service", "road", "steps", "corridor", "footway", "pedestrian", "bridleway"):
        assert value in preset["routable_highway"], value
    assert "steps" not in preset["hard_exclude_tags"].get("highway", [])
    assert set(preset["fallback_highway"]) == {"service", "road"}
    assert set(preset["bicycle_explicit_highway"]) == {"footway", "pedestrian"}
    assert preset["preferences"]["fallback_way_cost"] >= 100
    assert preset["preferences"]["steps_cost"] > 1


def test_walk_preset_allows_bridleway():
    assert "bridleway" in load_preset("walk")["routable_highway"]
```

- [ ] **Step 2:** FAIL. **Step 3:** edit presets.
  - bike (both): `routable_highway` add `tertiary, unclassified, service, road, steps, corridor, pedestrian, bridleway` (sport keeps `secondary`); `hard_exclude_tags` -> `{ "bicycle": ["no", "dismount"] }`; add `"fallback_highway": ["service", "road"]`, `"bicycle_explicit_highway": ["footway", "pedestrian"]`; preferences add `"fallback_way_cost": 1000`, `"steps_cost": 5`.
  - walk: add `bridleway`.
  - Existing tests that assert `steps` in bike hard-exclude: fix them.
- [ ] **Step 4:** pass. **Step 5:** commit.

### Task 4: SKILL, reference, README and spec for TODO 9

**Files:** `SKILL.md` (step 7, step 11 build_graph call, table near line 770, line ~393), `reference.md:188`, `README.md`, spec §3.6.

- [ ] Pass `fallback_highway=weights.get("fallback_highway", ())` and `bicycle_explicit_highway=weights.get("bicycle_explicit_highway", ())` in both `build_graph` examples in SKILL.md (step 11 and the Core Pattern code at ~line 463+).
- [ ] Describe the three rules (fallback ways; footway/pedestrian need `bicycle=yes|designated`; steps and `bicycle=dismount`) in step 11 and in the tag table; update the bike hard-exclude row (no `steps`).
- [ ] Step 17: tell the planner to call `route_graph.special_segments(way_segments)` and write one note per steps run ("push the bike") and a note listing the fallback ways used, under the "Route reasoning" section.
- [ ] Update README preset description and spec §3.6 and the research document's final section (decisions taken: `road` is fallback; `*_link` are no longer fetched).
- [ ] Commit.

### Task 5: Length range resolver and weights

**Files:** Modify `scripts/presets.py`; Test `tests/test_presets.py`.

**Interfaces:** `LengthRequiredError`; `resolve_length_range(min_km=None, max_km=None, min_h=None, max_h=None) -> dict` with keys `min_distance_km, max_distance_km, min_duration_hours, max_duration_hours`; `build_weights(..., min_distance_km=None, min_duration_hours=None)` stores them.

- [ ] **Step 1: Failing tests**

```python
def test_only_a_maximum_gives_half_of_it_as_the_minimum():
    r = resolve_length_range(max_km=30)
    assert (r["min_distance_km"], r["max_distance_km"]) == (15, 30)
    assert r["min_duration_hours"] is None and r["max_duration_hours"] is None


def test_only_a_time_gives_half_of_it_as_the_minimum():
    r = resolve_length_range(max_h=4)
    assert (r["min_duration_hours"], r["max_duration_hours"]) == (2, 4)
    assert r["min_distance_km"] is None


def test_explicit_minimum_is_kept():
    assert resolve_length_range(min_km=10, max_km=30)["min_distance_km"] == 10


def test_no_length_raises():
    with pytest.raises(LengthRequiredError):
        resolve_length_range()


def test_a_minimum_without_a_maximum_raises():
    with pytest.raises(LengthRequiredError):
        resolve_length_range(min_km=10)


def test_minimum_above_maximum_raises_value_error():
    with pytest.raises(ValueError):
        resolve_length_range(min_km=40, max_km=30)


def test_build_weights_stores_the_minimums():
    w = build_weights(load_preset("walk"), max_distance_km=30, min_distance_km=15)
    assert w["min_distance_km"] == 15 and w["min_duration_hours"] is None
```

- [ ] **Step 2:** FAIL. **Step 3:** implement:

```python
class LengthRequiredError(Exception):
    pass


def resolve_length_range(min_km=None, max_km=None, min_h=None, max_h=None) -> dict:
    """The range the route must fit. One given value is the maximum; its minimum is half of it. Nothing given, or a
    minimum without its maximum: LengthRequiredError (the planner then asks the user)."""
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
```

`build_weights` gains the two keyword parameters and stores `weights["min_distance_km"]`, `weights["min_duration_hours"]`.
- [ ] **Step 4/5:** pass; commit.

### Task 6: Minimum-length and enough-points checks

**Files:** Modify `scripts/waypoints.py`; Test `tests/test_waypoints.py`.

**Interfaces:** `RouteTooShortError`, `check_minimum_length(distance_km, min_distance_km, duration_hours=None, min_duration_hours=None)`, `NotEnoughPointsError`, `check_enough_points(points, minimum=2)`.

- [ ] **Step 1: Failing tests**

```python
def test_route_below_minimum_distance_raises():
    with pytest.raises(RouteTooShortError) as e:
        check_minimum_length(0.16, 15.0)
    assert "0.2" in str(e.value) or "0.16" in str(e.value)


def test_route_at_or_above_minimum_passes():
    check_minimum_length(15.0, 15.0)
    check_minimum_length(1.0, None)


def test_route_below_minimum_duration_raises():
    with pytest.raises(RouteTooShortError):
        check_minimum_length(20.0, 15.0, duration_hours=1.0, min_duration_hours=2.0)


def test_points_without_real_interest_raise():
    with pytest.raises(NotEnoughPointsError):
        check_enough_points([{"name": "A", "kind": "start"}])
    with pytest.raises(NotEnoughPointsError):
        check_enough_points([{"name": "A", "kind": "start"}, {"name": "Магазин", "kind": "shop"}])


def test_enough_interest_points_pass():
    check_enough_points([{"name": "A", "kind": "start"}, {"name": "Вершина", "kind": "peak"},
                         {"name": "Родник", "kind": "water"}])
```

- [ ] **Step 2:** FAIL. **Step 3:** implement

```python
class RouteTooShortError(Exception):
    pass


def check_minimum_length(distance_km, min_distance_km, duration_hours=None, min_duration_hours=None) -> None:
    """Raises when the route is shorter than the minimum. The route must not be saved then (TODO 10c)."""
    if min_distance_km is not None and distance_km < min_distance_km:
        raise RouteTooShortError(
            f"Маршрут получился {distance_km:.1f} км, а минимум — {min_distance_km:.1f} км. "
            "Не сохраняйте его. Спросите пользователя, что изменить: диапазон длины, точку старта, "
            "радиус района или режим.")
    if min_duration_hours is not None and duration_hours is not None and duration_hours < min_duration_hours:
        raise RouteTooShortError(
            f"Маршрут займёт {duration_hours:.1f} ч, а минимум — {min_duration_hours:.1f} ч. "
            "Не сохраняйте его. Спросите пользователя, что изменить: диапазон времени, точку старта, "
            "радиус района или режим.")


class NotEnoughPointsError(Exception):
    pass


NON_INTEREST_KINDS = ("start", "access", "shop", "supermarket", "convenience")


def check_enough_points(points: list[dict], minimum: int = 2) -> None:
    """Raises when fewer than `minimum` points are real points of interest (not the start, an access point or a
    shop). The planner then asks the user what kind of places they like (TODO 10d, 10e)."""
    real = [p for p in points if p.get("kind") not in NON_INTEREST_KINDS]
    if len(real) < minimum:
        raise NotEnoughPointsError(
            f"Найдено мало мест для маршрута: {len(real)} из {minimum} нужных. "
            "Спросите пользователя, какие места он любит или какие знает. "
            "Не заполняйте маршрут только стартом или магазином.")
```
- [ ] **Step 4/5:** pass; commit.

### Task 7: Archive validation

**Files:** Modify `scripts/archive_validate.py`; Test `tests/test_archive_validate.py`.

- [ ] **Step 1: Failing tests**

```python
def test_route_shorter_than_minimum_is_rejected(tmp_path):
    _write_complete_archive(tmp_path)
    (tmp_path / "weights.json").write_text(json.dumps({"mode": "walk", "min_distance_km": 15.0}), encoding="utf-8")
    with pytest.raises(ArchiveIncompleteError) as e:
        validate_archive(tmp_path)           # distance_km is 5.2
    assert "min_distance_km" in str(e.value)


def test_route_shorter_than_minimum_duration_is_rejected(tmp_path):
    _write_complete_archive(tmp_path)
    (tmp_path / "weights.json").write_text(json.dumps({"mode": "walk", "min_duration_hours": 3.0}), encoding="utf-8")
    with pytest.raises(ArchiveIncompleteError):
        validate_archive(tmp_path)           # duration is 1.5


def test_route_at_minimum_and_old_archives_pass(tmp_path):
    _write_complete_archive(tmp_path)
    (tmp_path / "weights.json").write_text(json.dumps({"mode": "walk", "min_distance_km": 5.2}), encoding="utf-8")
    validate_archive(tmp_path)
```

- [ ] **Step 2:** FAIL. **Step 3:** after the weights check add

```python
    if isinstance(weights, dict) and geojson is not None:
        problems.extend(_validate_minimum(geojson, weights))
```
with
```python
def _validate_minimum(geojson: dict, weights: dict) -> list[str]:
    """The route must not be shorter than the minimum the planner stored in weights.json (absent in old archives)."""
    lines = [f for f in geojson.get("features") or [] if f.get("geometry", {}).get("type") == "LineString"]
    if len(lines) != 1:
        return []
    props = lines[0].get("properties", {})
    problems = []
    for weight_key, prop_key, unit in (("min_distance_km", "distance_km", "км"),
                                       ("min_duration_hours", "duration_estimate_hours", "ч")):
        minimum, value = weights.get(weight_key), props.get(prop_key)
        if isinstance(minimum, (int, float)) and isinstance(value, (int, float)) and value < minimum:
            problems.append(f"{prop_key}={value} {unit} меньше {weight_key}={minimum} {unit} из weights.json — "
                            "маршрут короче минимума, его нельзя сохранять")
    return problems
```
Update module docstring. Commit.

### Task 8: SKILL, spec, README, Changelog, version, TODO for TODO 10

- [ ] SKILL.md step 4a/10: ask for a length or time if missing; call `presets.resolve_length_range(...)`, pass `max_*` and `min_*` to `build_weights`. Say the default minimum is 1/2 of the only given value and the user is not asked for it.
- [ ] Step 6: when little is known about interests, ask; call `waypoints.check_enough_points` on the mandatory + included points; on `NotEnoughPointsError` ask.
- [ ] Step 15: after the duration, call `waypoints.check_minimum_length(distance_km, weights["min_distance_km"], duration_hours, weights["min_duration_hours"])`; on `RouteTooShortError` do not save, tell the user why and ask what to change.
- [ ] Spec §3.5 gets a "Minimum length" paragraph; README mentions the minimum.
- [ ] `plugin.json` 0.2.1 -> 0.3.0; Changelog line `0.3.0\t...` on top; mark TODO 9 and 10 `[done]` with a short result line.
- [ ] Full suite passes; commit.
