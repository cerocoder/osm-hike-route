# Hike conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The day plan shows a 24-hour forecast plus 4 hours after the end of the trip from a start the plan recommends (taking access-point hours and transport into account), warns about ticks only on forest and grass, and describes water within 500 m of the route and its points.

**Architecture:** A start resolver (`day_plan/start.py`) runs before the plugins and writes the recommended start into `ctx.start_time` (so `light`, `transit` and the weather window need no new input). `weather` builds a window of rows (24 h + 4 h after the finish, two cached per-day requests). Two new data-only plugins (`land_cover`, `water_near`) run their own Overpass `around` queries; `bio_hazards` consumes `land_cover`; a new `water` plugin consumes `water_near`, the Open-Meteo Marine API, an air-temperature history for an inland estimate, and a new `water` fact.

**Tech Stack:** Python 3 standard library only, pytest, Open-Meteo (forecast, archive, marine), Overpass.

**Spec:** `docs/superpowers/specs/2026-10-01-hike-conditions-design.md`

All commands run from `skills/osm-day-route-day-plan/` (the directory with `scripts/` and `tests/`). Baseline before any change: `python3 -m pytest -q` → `786 passed`.

## Global Constraints

- Standard library only; no new dependencies (the skill's scripts are stdlib-only).
- No test touches the network: tests pass a fake `http` through `build_context(..., http=...)`; `conftest.py` blocks the real one.
- Every user-visible string goes through `tr()`; English and Russian are complete, the other languages fall back to English (as the neighbouring plugins do), except `pl_*` plugin names which exist in all seven languages (`test_every_default_plugin_has_name_in_every_language`).
- Confidence tiers stay `tag-backed | web-sourced | derived | no-data`.
- Fact text and plan text never contain street addresses; places stay at city, station or stop level.
- Recommended start: the earliest feasible start, but not earlier than 07:00 (`PREFERRED_FROM_MIN = 420`); if that does not fit, the earliest feasible; sunset buffer 60 min; last-departure buffer 30 min.
- Ticks: below 5 % of the route on forest or open ground nothing is said about ticks (`TICK_MIN_COVER = 0.05`).
- Water radius 500 m (`RADIUS_M = 500`); the sea or ocean first, then the two largest other bodies in detail, then at most 15 listed lines.
- Cold-shock caution when the water is below 15 °C; ice possible at or below 4 °C.
- Deliberate deviations from the spec text (the spec is amended in Task 9): the weather forecast uses two cached per-day requests instead of one date-range request; polar day has no daylight limits and polar night gets no recommendation; regional `bio_hazards` facts are not hidden when ticks are not assessed (they also carry animal notes); pollution and hazards are one block under the water table (a fact is per plugin, not per water body).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A trip that ends after 20:00 so that finish + 4 h passes midnight, and the next-day request fails: the plan must still build, with the 24 h of the date only (Task 4).
- `--start` given by the user: the recommended start must never override it and must make no network request (Task 3).
- A route with very few vertices (a two-point line, 15 km long): land cover must sample along the distance, not per vertex (Task 5).
- Malformed Overpass geometry (an unclosed ring, a relation with no outer members, an inner ring only): no crash, the object is ignored (Task 5).
- Marine API with `null` temperatures at the coastal grid point, HTTP 400 beyond the horizon, or a last departure after midnight (`00:20`): the plan degrades to climatology or "no data" and never raises (Tasks 3 and 8).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/day_plan/start.py` (new) | `recommend_start` (pure), `resolve_start(ctx)`, `start_lines(ctx)` |
| `scripts/day_plan/i18n_conditions.py` (new) | all new strings (en, ru) and the new plugin names (7 languages); merged into `STRINGS` by `i18n.py` |
| `scripts/day_plan/plugins/land_cover.py` (new) | data-only: forest / open-ground share of the route |
| `scripts/day_plan/plugins/water_near.py` (new) | data-only: water within 500 m of the track and the points |
| `scripts/day_plan/marine.py` (new) | Open-Meteo Marine fetch, sea temperature, tide extrema |
| `scripts/day_plan/plugins/water.py` (new) | the "Water nearby" section |
| `scripts/day_plan/context.py` | `start_source`, `start_info` fields |
| `scripts/day_plan/service.py` | calls `resolve_start` before the plugin loop |
| `scripts/day_plan/plugins/weather.py` | per-day `_fetch`, window rows, after-finish marking, start line |
| `scripts/day_plan/plugins/light.py` | recommended-start lines |
| `scripts/day_plan/plugins/bio_hazards.py` | tick gating by `land_cover` |
| `scripts/day_plan/facts.py`, `scripts/record_fact.py` | `first_arrival_local`, plugin `water` |
| `scripts/build_day_plan.py` | registration, hints |
| `SKILL.md`, `README.md`, spec | docs |

---

### Task 1: Fact `first_arrival_local` and plugin id `water`

**Files:**
- Modify: `scripts/day_plan/facts.py` (docstring, `normalize_entry` key loop)
- Modify: `scripts/record_fact.py` (`PLUGINS`, `WARNING_PLUGINS`, `record`, `main`)
- Test: `tests/test_facts_and_points.py`, `tests/test_record_fact.py`

**Interfaces:**
- Produces: facts entry key `first_arrival_local` (`"HH:MM"`, validated like `last_departure_local`); `record(route_dir, date, plugin, markdown, sources, last_departure=None, first_departure=None, warnings=None, day_type=None, first_arrival=None)`; CLI `--first-arrival HH:MM` (transit only); plugin id `water` accepted by `record_fact.py` (with `--warning`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_facts_and_points.py`:

```python
def test_first_arrival_is_validated_like_the_other_times():
    entry = normalize_entry(_entry(first_arrival_local="8:40"))
    assert entry["first_arrival_local"] == "8:40"
    assert "first_arrival_local" not in normalize_entry(_entry(first_arrival_local="early"))
```

Append to `tests/test_record_fact.py`:

```python
def test_first_arrival_is_stored_for_transit_and_refused_elsewhere(tmp_path, capsys):
    assert _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "Bus 41 from 07:30.",
                "--source", URL, "--first-arrival", "08:40") == 0
    assert lookup(load_facts(tmp_path), "2026-06-27", "transit")["first_arrival_local"] == "08:40"
    capsys.readouterr()
    assert _run(tmp_path, "--date", "all", "--plugin", "fire", "--markdown", "x", "--source", URL,
                "--first-arrival", "08:40") == 1
    assert "does not use --first-arrival" in capsys.readouterr().err
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL,
                "--first-arrival", "soon") == 1
    assert "bad first_arrival_local" in capsys.readouterr().err


def test_water_facts_are_recorded_with_warnings(tmp_path):
    assert _run(tmp_path, "--date", "all", "--plugin", "water", "--markdown", "Bathing water quality: excellent.",
                "--source", URL, "--warning", "caution:Jellyfish season") == 0
    entry = lookup(load_facts(tmp_path), "2026-06-27", "water")
    assert entry["warnings"] == [{"severity": "caution", "text": "Jellyfish season"}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_facts_and_points.py tests/test_record_fact.py -q`
Expected: 3 FAIL (`first_arrival_local` missing; `unknown plugin 'water'`; unknown option `--first-arrival`).

- [ ] **Step 3: Implement**

In `scripts/day_plan/facts.py` change the two lines in the docstring and the loop:

```python
        "first_departure_local": "HH:MM",          # optional, transit
        "first_arrival_local": "HH:MM",            # optional, transit: the earliest time public transport brings one to the start point
```
```python
    for key in ("last_departure_local", "first_departure_local", "first_arrival_local"):
```

In `scripts/record_fact.py`:

```python
PLUGINS = ("transit", "poi_hours", "calendar", "fire", "mountain", "bio_hazards", "air", "people_hazards",
           "trail_conditions", "water")
WARNING_PLUGINS = ("transit", "poi_hours", "fire", "mountain", "bio_hazards", "air", "people_hazards",
                   "trail_conditions", "water")
```
Change the `record` signature and body:
```python
def record(route_dir, date: str, plugin: str, markdown: str, sources: list, last_departure: str | None = None,
           first_departure: str | None = None, warnings: list | None = None, day_type: str | None = None,
           first_arrival: str | None = None) -> dict:
```
In the option check tuple add `("--first-arrival", first_arrival, ("transit",)),`. Change the entry loop and the validation loop:
```python
    for key, value in (("last_departure_local", last_departure), ("first_departure_local", first_departure),
                       ("first_arrival_local", first_arrival), ("day_type", day_type)):
        if value is not None:
            entry[key] = value
```
```python
    for key in ("last_departure_local", "first_departure_local", "first_arrival_local"):
        if key in entry and key not in clean:
            raise ValueError(f"bad {key}: use HH:MM")
```
In `main` add `parser.add_argument("--first-arrival", default=None)` and pass it:
```python
        record(args.route_dir, args.date, args.plugin, markdown, args.source, args.last_departure,
               args.first_departure, [_parse_warning(w) for w in args.warning], args.day_type, args.first_arrival)
```
Also add `[--first-arrival HH:MM]` to the usage lines of the module docstring.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_facts_and_points.py tests/test_record_fact.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan/facts.py scripts/record_fact.py tests/test_facts_and_points.py tests/test_record_fact.py
git commit -m "Facts: first_arrival_local for transit, plugin id water

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The pure start recommendation

**Files:**
- Create: `scripts/day_plan/start.py`
- Test: `tests/test_start.py`

**Interfaces:**
- Produces:
  - `PREFERRED_FROM_MIN = 420`, `SUNSET_BUFFER_MIN = 60`, `LAST_DEPARTURE_BUFFER_MIN = 30`
  - `@dataclass StartRecommendation(status: str, start_min: int | None = None, earliest: int | None = None, earliest_limit: str | None = None, latest: int | None = None, latest_limit: str | None = None, missing: list = [])` where `status` is `"ok" | "empty_window" | "no_duration"`, limit names are `sunrise | start_open | first_arrival` (earliest) and `sunset | last_departure | end_close` (latest).
  - `recommend_start(duration_min, sunrise=None, sunset=None, start_open=None, first_arrival=None, last_departure=None, end_close=None, preferred_from=PREFERRED_FROM_MIN) -> StartRecommendation` (all times in minutes after local midnight; `last_departure` and `end_close` may exceed 1440).

- [ ] **Step 1: Write the failing tests** — create `tests/test_start.py`:

```python
import pytest

from day_plan.start import recommend_start

H = 60


def test_no_duration_recommends_nothing():
    assert recommend_start(None, sunrise=300, sunset=1200).status == "no_duration"
    assert recommend_start(0).status == "no_duration"


def test_plain_summer_day_starts_at_seven():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281)
    assert rec.status == "ok" and rec.start_min == 7 * H
    assert (rec.earliest, rec.earliest_limit) == (283, "sunrise")
    assert (rec.latest, rec.latest_limit) == (1281 - 60 - 300, "sunset")


def test_the_seven_oclock_preference_is_dropped_when_the_route_would_not_fit():
    # sunset 17:00, 9 h route: latest = 17:00 - 1 h - 9 h = 07:00 is fine; 10 h route: latest = 06:00 < 07:00
    rec = recommend_start(10 * H, sunrise=5 * H, sunset=17 * H)
    assert rec.status == "ok" and rec.start_min == 5 * H and rec.latest == 6 * H


def test_first_arrival_and_start_point_opening_raise_the_earliest():
    rec = recommend_start(4 * H, sunrise=300, sunset=1200, start_open=8 * H, first_arrival=9 * H + 10)
    assert rec.start_min == 9 * H + 10 and rec.earliest_limit == "first_arrival"
    rec = recommend_start(4 * H, sunrise=300, sunset=1200, start_open=10 * H, first_arrival=9 * H)
    assert rec.start_min == 10 * H and rec.earliest_limit == "start_open"


def test_last_departure_and_end_point_closing_lower_the_latest():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=14 * H)
    assert rec.latest == 14 * H - 30 - 300 and rec.latest_limit == "last_departure" and rec.start_min == 7 * H
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, end_close=15 * H)
    assert rec.latest == 10 * H and rec.latest_limit == "end_close"


def test_a_departure_after_midnight_is_a_loose_limit():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=24 * H + 20)
    assert rec.latest_limit == "sunset"


def test_when_seven_is_too_late_the_earliest_feasible_start_is_taken():
    rec = recommend_start(5 * H, sunrise=283, sunset=1281, last_departure=12 * H)
    assert rec.status == "ok" and rec.start_min == 283 and rec.latest == 390


def test_empty_window_names_both_limits_and_uses_the_daylight_start():
    rec = recommend_start(9 * H, sunrise=330, sunset=18 * H, first_arrival=9 * H + 10)
    assert rec.status == "empty_window"
    assert (rec.earliest_limit, rec.latest_limit) == ("first_arrival", "sunset")
    assert rec.start_min == 18 * H - 60 - 9 * H == 8 * H


def test_no_limits_at_all_uses_the_preference():
    rec = recommend_start(3 * H)
    assert rec.status == "ok" and rec.start_min == 7 * H and rec.earliest_limit is None and rec.latest is None


@pytest.mark.parametrize("duration", [30, 12 * H])
def test_start_is_never_negative_or_after_midnight(duration):
    rec = recommend_start(duration, sunrise=0, sunset=23 * H)
    assert 0 <= rec.start_min < 1440
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_start.py -q`
Expected: collection error `ModuleNotFoundError: day_plan.start`.

- [ ] **Step 3: Implement** — create `scripts/day_plan/start.py`:

```python
"""The start of the trip: the one the person gave, or the one the plan recommends.

The recommendation is the earliest feasible start, but not earlier than 07:00 (a start before sunrise in summer is
not a sensible advice); when the route would not fit otherwise, the earliest feasible one. The window of a feasible
start is bounded below by sunrise, the opening of the start point and the first public transport that reaches it, and
above by sunset (minus a safety buffer), the last public transport back and the closing of the end point, each minus
the duration of the route. An empty window is reported, never hidden. All times are minutes after local midnight."""
from dataclasses import dataclass, field

PREFERRED_FROM_MIN = 7 * 60
SUNSET_BUFFER_MIN = 60
LAST_DEPARTURE_BUFFER_MIN = 30


@dataclass
class StartRecommendation:
    status: str                        # "ok" | "empty_window" | "no_duration"
    start_min: int | None = None
    earliest: int | None = None
    earliest_limit: str | None = None  # sunrise | start_open | first_arrival
    latest: int | None = None
    latest_limit: str | None = None    # sunset | last_departure | end_close
    missing: list = field(default_factory=list)   # transport facts that were not recorded


def recommend_start(duration_min, sunrise=None, sunset=None, start_open=None, first_arrival=None,
                    last_departure=None, end_close=None, preferred_from=PREFERRED_FROM_MIN) -> StartRecommendation:
    if not duration_min:
        return StartRecommendation("no_duration")
    lows = {name: value for name, value in (("sunrise", sunrise), ("start_open", start_open),
                                            ("first_arrival", first_arrival)) if value is not None}
    highs = {}
    if sunset is not None:
        highs["sunset"] = sunset - SUNSET_BUFFER_MIN - duration_min
    if last_departure is not None:
        highs["last_departure"] = last_departure - LAST_DEPARTURE_BUFFER_MIN - duration_min
    if end_close is not None:
        highs["end_close"] = end_close - duration_min
    earliest_limit = max(lows, key=lows.get) if lows else None
    earliest = lows[earliest_limit] if lows else 0
    latest_limit = min(highs, key=highs.get) if highs else None
    latest = highs[latest_limit] if highs else None
    rec = StartRecommendation("ok", None, earliest, earliest_limit, latest, latest_limit)
    wanted = max(earliest, preferred_from)
    if latest is None or earliest <= latest:
        start = wanted if latest is None or wanted <= latest else earliest
    else:
        rec.status = "empty_window"
        start = highs.get("sunset", latest)
    rec.start_min = min(1439, max(0, int(start)))
    return rec
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_start.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan/start.py tests/test_start.py
git commit -m "Start: the pure recommendation (window of a feasible start, 07:00 preference)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Resolve the start from the route, wire it in, show it

**Files:**
- Create: `scripts/day_plan/i18n_conditions.py`
- Modify: `scripts/day_plan/i18n.py` (merge the new strings, end of file after the `PLUGIN_NAMES` loop)
- Modify: `scripts/day_plan/context.py` (fields `start_source`, `start_info`; `build_context`)
- Modify: `scripts/day_plan/start.py` (`resolve_start`, `start_lines`)
- Modify: `scripts/day_plan/service.py` (`run_plugins`)
- Modify: `scripts/day_plan/plugins/light.py`
- Test: `tests/test_start.py`

**Interfaces:**
- Consumes: `recommend_start`, `StartRecommendation` (Task 2); `weather.choose_source`, `weather._fetch(ctx, source, lat, lon)` returning `(rows, utc_offset_seconds, fetched_at, elevation)` (unchanged in this task); `transit._return_point(points)`; `opening_hours.evaluate`, `latest_close`; `calendar_info.resolve_day_type(ctx)`; `facts.lookup`.
- Produces: `ctx.start_source` (`"user" | "recommended" | "none"`), `ctx.start_info` (`StartRecommendation | None`); `resolve_start(ctx) -> None` (sets `ctx.start_time` when it recommends); `start_lines(ctx) -> (lines: list[str], warnings: list[PlanWarning])`; i18n keys `st_*`; `CONDITION_STRINGS`, `CONDITION_PLUGIN_NAMES` dicts in `i18n_conditions.py` that later tasks extend.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_start.py`:

```python
import datetime
import json

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.light import LightPlugin
from day_plan.start import resolve_start, start_lines

JUNE = datetime.date(2026, 6, 21)


def _facts(route_dir, **transit):
    entry = {"markdown": "Bus 41.", "sources": ["https://www.crtm.es/horarios"], **transit}
    (route_dir / "facts.json").write_text(json.dumps({"all": {"transit": entry}}), encoding="utf-8")


def _ctx(make_route, fixed_now, weather_response, date=JUNE, **kwargs):
    http = kwargs.pop("http", lambda url: weather_response(date=date.isoformat()))
    route_dir = kwargs.pop("route_dir", None) or make_route(**{k: v for k, v in kwargs.items()
                                                               if k in ("duration_hours", "coords")})
    return route_dir, build_context(route_dir, date, http=http, now=fixed_now,
                                    start_time=kwargs.get("start_time"))


def test_without_facts_the_start_is_seven_oclock(make_route, fixed_now, weather_response):
    _, ctx = _ctx(make_route, fixed_now, weather_response)
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(7, 0) and ctx.start_source == "recommended"
    assert ctx.start_info.status == "ok" and ctx.start_info.missing == ["first_arrival", "last_departure"]


def test_a_start_given_by_the_user_wins_and_asks_nothing(make_route, fixed_now, weather_response):
    def http(url):
        raise AssertionError("the resolver must not touch the network when --start is given")

    _, ctx = _ctx(make_route, fixed_now, weather_response, http=http, start_time=datetime.time(9, 30))
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(9, 30) and ctx.start_source == "user"


def test_first_arrival_moves_the_start(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, first_arrival_local="09:10")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    assert ctx.start_time == datetime.time(9, 10) and ctx.start_info.earliest_limit == "first_arrival"


def test_a_last_departure_after_midnight_is_read_as_the_next_night(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, last_departure_local="00:20")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    assert ctx.start_info.latest_limit == "sunset" and ctx.start_time == datetime.time(7, 0)


def test_an_empty_window_gives_a_danger_warning(make_route, fixed_now, weather_response):
    route_dir = make_route(duration_hours=9.0)
    _facts(route_dir, first_arrival_local="16:00")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    lines, warnings = start_lines(ctx)
    assert ctx.start_info.status == "empty_window"
    assert [w.severity for w in warnings] == ["danger"] and "16:00" in warnings[0].text


def test_polar_night_gets_no_recommendation(make_route, fixed_now, weather_response):
    def http(url):
        raise AssertionError("no request expected")

    _, ctx = _ctx(make_route, fixed_now, weather_response, date=datetime.date(2026, 12, 21), http=http,
                  coords=((15.6, 78.2, 10.0), (15.7, 78.25, 20.0)))
    resolve_start(ctx)
    assert ctx.start_source == "none" and ctx.start_time is None


def test_a_weather_failure_still_gives_a_start(make_route, fixed_now, weather_response):
    def http(url):
        raise HttpError("boom")

    _, ctx = _ctx(make_route, fixed_now, weather_response, http=http)
    resolve_start(ctx)
    assert ctx.start_source == "recommended" and ctx.start_time is not None


def test_the_light_section_shows_the_recommendation(make_route, fixed_now, weather_response):
    route_dir = make_route()
    _facts(route_dir, first_arrival_local="09:10", last_departure_local="23:30")
    _, ctx = _ctx(make_route, fixed_now, weather_response, route_dir=route_dir)
    resolve_start(ctx)
    section = LightPlugin().run(ctx, {"weather": {"utc_offset_seconds": 3600}})
    assert "Recommended start: **09:10**" in section.markdown
    assert "estimated finish 14:10" in section.markdown
    assert "Not recorded" not in section.markdown


def test_missing_transport_facts_are_said_when_there_are_access_points(make_route_with_points, fixed_now,
                                                                       weather_response):
    route_dir = make_route_with_points([("Cercedilla", "access", -3.75, 40.42, {"role": "start"})],
                                       duration_hours=4.0)
    ctx = build_context(route_dir, JUNE, http=lambda url: weather_response(utc_offset_seconds=7200), now=fixed_now)
    resolve_start(ctx)
    lines, _ = start_lines(ctx)
    assert any("Not recorded" in line for line in lines)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_start.py -q`
Expected: FAIL (`resolve_start` not importable).

- [ ] **Step 3: Implement**

3a. Create `scripts/day_plan/i18n_conditions.py` (later tasks add keys here):

```python
"""Strings of the hike-conditions features (recommended start, full-day forecast, ticks by terrain, nearby water).
English and Russian are complete; the other languages fall back to English like the rest of the plan. Merged into
`i18n.STRINGS` at import time (see the end of i18n.py)."""

CONDITION_STRINGS = {
    "en": {
        # recommended start
        "st_limits": {"sunrise": "sunrise", "start_open": "the start point opens",
                      "first_arrival": "the first public transport arrives", "sunset": "sunset",
                      "last_departure": "the last public transport back", "end_close": "the end point closes"},
        "st_no_limit": "no limit",
        "st_recommended": "Recommended start: **{start}** (a start is possible from {early} to {late}{pref}).",
        "st_pref": ", not earlier than 07:00 by preference",
        "st_warn_empty": "No start fits all limits: a start is possible only from {earliest} ({early}) but only until {latest} ({late}); the start used is {start}.",
        "st_transport_missing": "Not recorded: {what} — those transport limits are not applied to the recommended start.",
        "st_missing": {"first_arrival": "the first public transport to the start point",
                       "last_departure": "the last public transport back"},
    },
    "ru": {
        "st_limits": {"sunrise": "рассвет", "start_open": "открытие точки старта",
                      "first_arrival": "прибытие первого рейса", "sunset": "закат",
                      "last_departure": "последний рейс назад", "end_close": "закрытие точки финиша"},
        "st_no_limit": "без ограничения",
        "st_recommended": "Рекомендуемый старт: **{start}** (старт возможен с {early} до {late}{pref}).",
        "st_pref": ", не раньше 07:00 по предпочтению",
        "st_warn_empty": "Нет старта, подходящего под все ограничения: стартовать можно только с {earliest} ({early}), но не позже {latest} ({late}); взят старт {start}.",
        "st_transport_missing": "Не записано: {what} — эти ограничения по транспорту не учтены в рекомендуемом старте.",
        "st_missing": {"first_arrival": "первый рейс до точки старта", "last_departure": "последний рейс назад"},
    },
}

# plugin names for the progress lines: every language (a test requires it for every default plugin)
CONDITION_PLUGIN_NAMES = {lang: {} for lang in ("en", "ru", "es", "fr", "de", "pt", "it")}
```

3b. At the very end of `scripts/day_plan/i18n.py` (after the `for _lang, _names in PLUGIN_NAMES.items(): ...` loop, before `def tr`):

```python
from .i18n_conditions import CONDITION_PLUGIN_NAMES, CONDITION_STRINGS  # noqa: E402

for _lang, _extra in CONDITION_PLUGIN_NAMES.items():
    STRINGS[_lang].update(_extra)
for _lang, _extra in CONDITION_STRINGS.items():
    STRINGS[_lang].update(_extra)
```

3c. `scripts/day_plan/context.py`: add the two fields after `progress`:

```python
    start_source: str = "none"                                      # "user" | "recommended" | "none" (see start.py)
    start_info: object = None                                       # StartRecommendation when recommended
```
and in `build_context(...)` pass `start_source="user" if start_time is not None else "none",` in the `PlanContext(...)` call.

3d. Append to `scripts/day_plan/start.py` (add the imports at the top of the file):

```python
import datetime

from .base import PlanWarning
from .calendar_info import resolve_day_type
from .facts import lookup
from .http import HttpError
from .i18n import tr
from .opening_hours import evaluate, latest_close
from .plugins import weather
from .plugins.transit import _return_point
from .sun import sun_times


def _clock(minute) -> str:
    return f"{(int(minute) // 60) % 24:02d}:{int(minute) % 60:02d}"


def _fact_minutes(text) -> int | None:
    if not isinstance(text, str) or ":" not in text:
        return None
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _start_point(points: list):
    for point in points:
        if point.role == "start":
            return point
    return points[0] if len(points) == 1 else None


def _utc_offset_seconds(ctx) -> float:
    lat, lon = ctx.centroid
    try:
        _, offset, _, _ = weather._fetch(ctx, weather.choose_source(ctx.date, ctx.today), lat, lon)
    except (HttpError, KeyError, IndexError, ValueError, TypeError):
        offset = None
    return offset if offset is not None else round(lon / 15.0 * 2) / 2 * 3600


def resolve_start(ctx) -> None:
    """Sets ctx.start_time (and start_source, start_info) to the recommended start when the person gave none.
    Nothing is done when --start was given, when the route has no duration, or on a polar night."""
    if ctx.start_source != "none" or not ctx.duration_hours:
        return
    lat, lon = ctx.centroid
    sun = sun_times(ctx.date, lat, lon)
    if sun.kind == "polar_night":
        return
    sunrise = sunset = None
    if sun.kind == "normal":
        offset_min = _utc_offset_seconds(ctx) / 60.0
        sunrise, sunset = sun.sunrise_utc_min + offset_min, sun.sunset_utc_min + offset_min
    sun_map = {"sunrise": int(sunrise), "sunset": int(sunset)} if sunrise is not None else None
    day = resolve_day_type(ctx)
    start_open = end_close = None
    start_point, end_point = _start_point(ctx.access_points), _return_point(ctx.access_points)
    if start_point is not None and start_point.opening_hours:
        result = evaluate(start_point.opening_hours, ctx.date, day.holiday, sun_map)
        if result.status == "open_hours" and result.intervals:
            start_open = min(begin for begin, _ in result.intervals)
    if end_point is not None and end_point.opening_hours:
        result = evaluate(end_point.opening_hours, ctx.date, day.holiday, sun_map)
        if result.status == "open_hours":
            end_close = latest_close(result)
    fact = lookup(ctx.facts, ctx.date_iso, "transit") or {}
    first_arrival = _fact_minutes(fact.get("first_arrival_local"))
    last_departure = _fact_minutes(fact.get("last_departure_local"))
    if last_departure is not None and last_departure < 240:      # a departure at 00:30 belongs to the night after this date
        last_departure += 1440
    rec = recommend_start(round(ctx.duration_hours * 60), sunrise, sunset, start_open, first_arrival,
                          last_departure, end_close)
    rec.missing = [name for name, value in (("first_arrival", first_arrival), ("last_departure", last_departure))
                   if value is None]
    ctx.start_time = datetime.time(rec.start_min // 60, rec.start_min % 60)
    ctx.start_source = "recommended"
    ctx.start_info = rec


def _limit(minute, key, lang) -> str:
    return f"{_clock(minute)} ({tr('st_limits', lang)[key]})" if minute is not None and key else tr("st_no_limit", lang)


def start_lines(ctx) -> tuple[list, list]:
    """Plan lines and warnings that explain a recommended start; nothing for a start the person gave."""
    info = getattr(ctx, "start_info", None)
    if getattr(ctx, "start_source", "none") != "recommended" or info is None:
        return [], []
    lang = ctx.lang
    lines, warnings = [], []
    if info.status == "empty_window":
        warnings.append(PlanWarning("danger", tr(
            "st_warn_empty", lang, earliest=_clock(info.earliest), early=tr("st_limits", lang)[info.earliest_limit],
            latest=_clock(info.latest), late=tr("st_limits", lang)[info.latest_limit], start=_clock(info.start_min))))
    else:
        pref = tr("st_pref", lang) if info.start_min == PREFERRED_FROM_MIN and info.earliest < PREFERRED_FROM_MIN else ""
        lines.append("- " + tr("st_recommended", lang, start=_clock(info.start_min),
                               early=_limit(info.earliest if info.earliest_limit else None, info.earliest_limit, lang),
                               late=_limit(info.latest, info.latest_limit, lang), pref=pref))
    if info.missing and ctx.access_points:
        what = ", ".join(tr("st_missing", lang)[name] for name in info.missing)
        lines.append("- " + tr("st_transport_missing", lang, what=what))
    return lines, warnings
```
(`PREFERRED_FROM_MIN` is already defined in this module.) Note: `from .plugins import weather` must not import `light`; it does not.

3e. `scripts/day_plan/service.py`: add `from .start import resolve_start` and at the start of `run_plugins`, after `ctx.progress = progress`:

```python
    try:
        resolve_start(ctx)
    except Exception:  # noqa: BLE001 — a recommendation must never stop the plan
        pass
```

3f. `scripts/day_plan/plugins/light.py`: add `from ..start import start_lines` and in the branch `if ctx.start_time is not None:` insert before the `light_finish` line is appended:

```python
                extra_lines, extra_warnings = start_lines(ctx)
                lines += extra_lines
                warnings += extra_warnings
```

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `python3 -m pytest tests/test_start.py -q` → all PASS.
Run: `python3 -m pytest -q`.
Expected: the suite may now fail where an end-to-end test (`test_cli.py`, `test_service.py`, `test_light.py`, `test_pinned_warnings.py`) assumed that without `--start` no start/finish exists (the plan now always has a recommended start). For each failure decide: an assertion that encoded "no start means no return checks / `latest start` line" is an intended change — update it with a comment `# the plan now recommends a start`; any other failure is a bug in the code above — fix the code. Re-run until green.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan tests
git commit -m "Start: resolve the recommended start from sun, access points and transport facts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Weather — 24 hours plus 4 hours after the finish

**Files:**
- Modify: `scripts/day_plan/plugins/weather.py`
- Modify: `scripts/day_plan/i18n_conditions.py`
- Test: `tests/test_weather.py`

**Interfaces:**
- Consumes: `ctx.start_time`, `ctx.start_source`, `finish_minute(ctx)` from `plugins/common.py` (minutes after midnight, may exceed 1440).
- Produces:
  - `AFTER_FINISH_MIN = 240`
  - `_fetch(ctx, source, lat, lon, date=None)` (same return; `date` defaults to `ctx.date`; the cache key uses it)
  - `needs_next_day(finish_min) -> bool`
  - `window_rows(day_rows, next_rows, finish_min) -> list[dict]` — each row copied with `day` (0/1) and `after` (bool)
  - `trip_rows(window, day_rows, start_min, finish_min) -> (trip, post)`
  - section `shared["window_rows"]`; `render_table` adds a column "After finish" only when a row has `after`, and `(+1)` after the hour of next-day rows.
- i18n keys: `w_after`, `w_after_prefix`, `w_start_user`, `w_start_recommended`, `w_start_line`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_weather.py`:

```python
from day_plan.plugins.weather import needs_next_day, trip_rows, window_rows


def _day(weather_response, date="2026-06-21"):
    return parse_hourly(weather_response(date=date))


def test_window_without_a_finish_is_the_whole_date(weather_response):
    window = window_rows(_day(weather_response), None, None)
    assert [r["hour"] for r in window] == list(range(24)) and not any(r["after"] for r in window)


def test_window_marks_rows_after_the_finish_and_adds_four_hours_of_the_next_day(weather_response):
    today, tomorrow = _day(weather_response), _day(weather_response, "2026-06-22")
    window = window_rows(today, tomorrow, 22 * 60)
    assert needs_next_day(22 * 60)
    assert [r["hour"] for r in window if r["day"] == 1] == [0, 1, 2, 3]       # (22:00 + 4 h) // 60 = 26 -> 02:00 + the hour
    assert [r["hour"] for r in window if r["after"] and r["day"] == 0] == [22, 23]
    assert not needs_next_day(14 * 60)


def test_window_survives_a_missing_next_day(weather_response):
    window = window_rows(_day(weather_response), None, 22 * 60)
    assert len(window) == 24


def test_trip_rows_are_the_hours_walked(weather_response):
    today, tomorrow = _day(weather_response), _day(weather_response, "2026-06-22")
    window = window_rows(today, tomorrow, 14 * 60)
    trip, post = trip_rows(window, today, 9 * 60, 14 * 60)
    assert [r["hour"] for r in trip] == [9, 10, 11, 12, 13]
    assert all(r["after"] for r in post) and post[0]["hour"] == 14


def test_plugin_shows_the_whole_day_and_four_hours_after_midnight(make_route, fixed_now, weather_response):
    import datetime as dt
    urls = []

    def http(url):
        urls.append(url)
        return weather_response(date="2026-06-22" if "start_date=2026-06-22" in url else "2026-06-21")

    ctx = build_context(make_route(duration_hours=6.0), datetime.date(2026, 6, 21), start_time=dt.time(17, 0),
                        http=http, now=fixed_now)
    section = WeatherPlugin().run(ctx, {})
    assert len(urls) == 2
    assert "| 00:00 |" in section.markdown and "| 23:00 |" in section.markdown
    assert "| 03:00 (+1) |" in section.markdown and "| 04:00 (+1) |" not in section.markdown
    assert "After finish" in section.markdown and "given by you" in section.markdown
    assert len(section.shared["window_rows"]) == 28
    assert section.shared["rows"][0]["hour"] == 0 and len(section.shared["rows"]) == 24


def test_a_failing_next_day_still_gives_the_day(make_route, fixed_now, weather_response):
    import datetime as dt

    def http(url):
        if "start_date=2026-06-22" in url:
            raise HttpError("boom")
        return weather_response()

    ctx = build_context(make_route(duration_hours=6.0), datetime.date(2026, 6, 21), start_time=dt.time(17, 0),
                        http=http, now=fixed_now)
    section = WeatherPlugin().run(ctx, {})
    assert "(+1)" not in section.markdown and len(section.shared["window_rows"]) == 24


def test_without_a_start_the_table_is_24_hours_with_one_request(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        return weather_response()

    section = WeatherPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert len(urls) == 1 and section.markdown.count("\n| ") >= 24
    assert "After finish" not in section.markdown


def test_a_warning_caused_only_by_an_hour_after_the_finish_says_so(make_route, fixed_now, weather_response):
    import datetime as dt
    ctx = build_context(make_route(duration_hours=4.0), datetime.date(2026, 6, 21), start_time=dt.time(9, 0),
                        http=lambda u: weather_response(weather_code={16: 95}), now=fixed_now)
    section = WeatherPlugin().run(ctx, {})
    texts = [w.text for w in section.warnings]
    assert any(t.startswith("After the finish") and "Thunderstorms" in t for t in texts)
    ctx = build_context(make_route(duration_hours=4.0), datetime.date(2026, 6, 21), start_time=dt.time(9, 0),
                        http=lambda u: weather_response(weather_code={11: 95}), now=fixed_now)
    texts = [w.text for w in WeatherPlugin().run(ctx, {}).warnings]
    assert any("Thunderstorms" in t and not t.startswith("After the finish") for t in texts)


def test_russian_start_line(make_route, fixed_now, weather_response):
    import datetime as dt
    ctx = build_context(make_route(duration_hours=4.0), datetime.date(2026, 6, 21), lang="ru",
                        start_time=dt.time(9, 0), http=lambda u: weather_response(), now=fixed_now)
    ctx.start_source = "recommended"
    assert "рекомендован планом" in WeatherPlugin().run(ctx, {}).markdown
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_weather.py -q`
Expected: new tests FAIL (names not importable).

- [ ] **Step 3: Implement**

3a. `i18n_conditions.py` — add to the `"en"` dict:

```python
        # weather window
        "w_after": "After finish",
        "w_after_prefix": "After the finish:",
        "w_start_user": "given by you", "w_start_recommended": "recommended by the plan",
        "w_start_line": "Start **{start}** ({source}) → estimated finish **{finish}**; the rows after the finish are marked.",
```
and to `"ru"`:
```python
        "w_after": "После финиша",
        "w_after_prefix": "После финиша:",
        "w_start_user": "задан вами", "w_start_recommended": "рекомендован планом",
        "w_start_line": "Старт **{start}** ({source}) → расчётный финиш **{finish}**; строки после финиша отмечены.",
```

3b. `scripts/day_plan/plugins/weather.py`:

Add import `from .common import finish_minute` and constant `AFTER_FINISH_MIN = 240` below `FORECAST_TTL_S`.

Change `_fetch` to take a date (replace `ctx.date`/`ctx.date_iso` inside it by `date`):

```python
def _fetch(ctx, source: str, lat: float, lon: float, date: datetime.date | None = None):
    """Returns (rows, utc_offset_seconds, fetched_at_epoch, model_elevation_m) for `date` (default: the plan's date)."""
    date = date or ctx.date
    variables = FORECAST_VARS if source == "forecast" else ARCHIVE_VARS
    key = f"weather|{source}|{_vars_id(variables)}|{lat:.3f}|{lon:.3f}|{date.isoformat()}"
    ...
    if source == "forecast":
        response = ctx.http(_url(FORECAST_URL, FORECAST_VARS, lat, lon, date))
        rows, offset = parse_hourly(response), utc_offset_for(response, date)
        ...
    elif source == "archive":
        response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, date))
        rows, offset = parse_hourly(response), utc_offset_for(response, date)
        ...
    else:
        ...
            past = _same_day_in_year(date, ctx.today.year - back)
            ...
            offset = offset if offset is not None else utc_offset_for(response, date)
```

Add the window helpers (after `daytime_rows`):

```python
def needs_next_day(finish_min) -> bool:
    return finish_min is not None and (finish_min + AFTER_FINISH_MIN) // 60 >= 24


def window_rows(day_rows: list, next_rows, finish_min) -> list:
    """The 24 rows of the date plus, when the finish + 4 h passes midnight, the rows of the next day up to that moment.
    Every row is a copy with `day` (0 | 1) and `after` (the hour starts at or after the finish)."""
    out = []
    for row in day_rows:
        out.append({**row, "day": 0, "after": finish_min is not None and row["hour"] * 60 >= finish_min})
    if finish_min is not None and next_rows:
        last_abs = (finish_min + AFTER_FINISH_MIN) // 60
        for row in next_rows:
            if 24 + row["hour"] <= last_abs:
                out.append({**row, "day": 1, "after": (24 + row["hour"]) * 60 >= finish_min})
    return out


def trip_rows(window: list, day_rows: list, start_min, finish_min) -> tuple:
    """(rows walked, rows after the finish). Without a start and a finish the daylight rows stand for the trip."""
    if start_min is None or finish_min is None:
        return day_rows, []
    trip = [r for r in window if not r.get("after") and (24 * r.get("day", 0) + r["hour"]) * 60 + 59 >= start_min]
    post = [r for r in window if r.get("after")]
    return trip or day_rows, post
```

In `render_table`, replace the function with:

```python
def render_table(rows: list[dict], lang: str) -> str:
    keys = ("w_time", "w_temp", "w_feels", "w_precip", "w_cloud", "w_vis", "w_wind", "w_gust", "w_snow", "w_sky")
    marked = any(r.get("after") for r in rows)
    header = [tr(k, lang) for k in keys] + ([tr("w_after", lang)] if marked else [])
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        vis_km = r["vis_m"] / 1000.0 if r.get("vis_m") is not None else None
        snow_cm = r["snow_m"] * 100.0 if r.get("snow_m") is not None else None
        hour = f"{r['hour']:02d}:00" + (" (+1)" if r.get("day") == 1 else "")
        cells = [hour, _num(r["temp"], 0), _num(r["feels"], 0), _precip_cell(r),
                 _num(r["cloud"], 0), _num(vis_km, 1), _wind_cell(r, lang), _num(r["gust"], 1),
                 _num(snow_cm, 0), tr(_sky_key(r["code"]), lang)]
        if marked:
            cells.append("•" if r.get("after") else "")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
```

Replace the body of `WeatherPlugin.run` after the `window` (route window) computation:

```python
        day = daytime_rows(rows, ctx.date, lat, lon, offset, route_window=window) or rows
        start_min = ctx.start_time.hour * 60 + ctx.start_time.minute if ctx.start_time is not None else None
        finish = finish_minute(ctx)
        next_rows = None
        if needs_next_day(finish):
            try:
                next_rows = _fetch(ctx, source, lat, lon, ctx.date + datetime.timedelta(days=1))[0]
            except (HttpError, KeyError, IndexError, ValueError, TypeError):
                next_rows = None           # the 24 hours of the date are still shown
        shown = window_rows(rows, next_rows, finish)
        trip, post = trip_rows(shown, day, start_min, finish)
        note_key = {"forecast": "w_source_forecast", "archive": "w_source_archive",
                    "climate": "w_source_climate"}[source]
        note = tr(note_key, ctx.lang, years=CLIMATE_YEARS) if source == "climate" else tr(note_key, ctx.lang)
        start_line = ""
        if start_min is not None and finish is not None:
            finish_text = f"{(finish // 60) % 24:02d}:{finish % 60:02d}" + (" (+1)" if finish >= 1440 else "")
            origin = tr("w_start_recommended" if getattr(ctx, "start_source", "none") == "recommended"
                        else "w_start_user", ctx.lang)
            start_line = tr("w_start_line", ctx.lang, start=f"{start_min // 60:02d}:{start_min % 60:02d}",
                            source=origin, finish=finish_text) + "\n\n"
        markdown = start_line + render_table(shown, ctx.lang) + "\n\n*" + note + "*"
        warnings = warnings_for(trip, ctx.lang, source)
        seen = {w.text for w in warnings}
        for w in warnings_for(post, ctx.lang, "forecast"):
            if w.text not in seen:
                warnings.append(PlanWarning(w.severity, f"{tr('w_after_prefix', ctx.lang)} {w.text}"))
        means = [r["temp"] for r in rows if r.get("temp") is not None]
        return Section(
            "weather", markdown, "derived", sources=["https://open-meteo.com/"], warnings=warnings,
            shared={"utc_offset_seconds": offset, "rows": rows, "daytime_rows": day, "window_rows": shown,
                    "source": source, "fetched_at": fetched_at, "elevation_m": elevation,
                    "daily_mean_temp": sum(means) / len(means) if means else None},
        )
```
(Delete the old `markdown = ...`, `means = ...` and `return Section(...)` that this replaces.)

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `python3 -m pytest tests/test_weather.py -q` → PASS.
Run: `python3 -m pytest -q`. Failures now come from tests that assumed a daylight-only table (e.g. a table without `| 00:00 |`, a row count of the day): these assert the intentionally changed behaviour; update them (comment `# the table is the whole date now`). Anything else is a bug — fix the code.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan tests
git commit -m "Weather: 24 hours of the date plus 4 hours after the finish, rows after the finish marked

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `land_cover` — forest and open ground along the route

**Files:**
- Create: `scripts/day_plan/plugins/land_cover.py`
- Test: `tests/test_land_cover.py`

**Interfaces:**
- Consumes: `osm_features.haversine_m`, `route_samples`; `overpass.run`, `OverpassError`, `ROUTES_TTL_S`, `EMPTY_TTL_S`; `ctx.cache.get_entry(key, max_age) -> (value, stored_at) | None`, `ctx.cache.put(key, value)`; `ctx.overpass_health`, `ctx.progress`.
- Produces: `LandCoverPlugin` (`plugin_id = "land_cover"`, `section_id = "hazards"`, `omit=True`) with `shared = {"known": bool, "forest": float, "open": float, "total": float, "error": str | None}` (shares are 0..1 of the route); pure helpers `cover_query(poly)`, `route_polyline(coords)`, `densify(coords, step_m, max_points)`, `parse_polygons(data)`, `cover_shares(polygons, samples)`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_land_cover.py`:

```python
import datetime

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.land_cover import (
    LandCoverPlugin, cover_query, cover_shares, densify, parse_polygons, route_polyline,
)

DATE = datetime.date(2026, 6, 21)


def _square(lon0, lat0, lon1, lat1):
    return [{"lat": lat0, "lon": lon0}, {"lat": lat0, "lon": lon1}, {"lat": lat1, "lon": lon1},
            {"lat": lat1, "lon": lon0}, {"lat": lat0, "lon": lon0}]


def _way(kind_tag, ring):
    return {"type": "way", "id": 1, "tags": kind_tag, "geometry": ring}


def test_query_is_an_around_query_on_the_polyline():
    ql = cover_query("51.45,-0.2,51.55,-0.05")
    assert "around:30,51.45,-0.2,51.55,-0.05" in ql and "wood|scrub|grassland|heath" in ql
    assert "forest|meadow|grass|farmland" in ql and "out tags geom" in ql


def test_densify_samples_along_the_distance_not_per_vertex():
    points = densify([(-0.20, 51.45, None), (-0.05, 51.55, None)], step_m=100, max_points=300)
    assert 100 < len(points) <= 300                       # a 15 km two-point line
    assert points[0] == (51.45, -0.20) and points[-1] == (51.55, -0.05)


def test_polyline_is_short_enough_for_a_url():
    coords = [(-0.2 + i * 0.001, 51.45, None) for i in range(1000)]
    assert len(route_polyline(coords).split(",")) <= 2 * 100


def test_forest_wins_over_open_ground_and_shares_are_fractions():
    forest = _way({"natural": "wood"}, _square(0.0, 0.0, 1.0, 1.0))
    meadow = _way({"landuse": "meadow"}, _square(0.0, 0.0, 2.0, 1.0))
    polygons = parse_polygons({"elements": [forest, meadow]})
    samples = [(0.5, 0.5), (0.5, 1.5), (0.5, 3.0), (0.5, 0.9)]       # forest, open, none, forest
    assert cover_shares(polygons, samples) == {"forest": 0.5, "open": 0.25}


def test_a_relation_with_a_hole_does_not_cover_the_hole():
    outer = {"type": "way", "role": "outer", "geometry": _square(0.0, 0.0, 4.0, 4.0)}
    inner = {"type": "way", "role": "inner", "geometry": _square(1.0, 1.0, 3.0, 3.0)}
    relation = {"type": "relation", "id": 9, "tags": {"natural": "wood"}, "members": [outer, inner]}
    polygons = parse_polygons({"elements": [relation]})
    assert cover_shares(polygons, [(2.0, 2.0), (0.5, 0.5)]) == {"forest": 0.5, "open": 0.0}


def test_an_outer_ring_split_in_two_ways_is_stitched():
    ring = _square(0.0, 0.0, 2.0, 2.0)
    first = {"type": "way", "role": "outer", "geometry": ring[:3]}
    second = {"type": "way", "role": "outer", "geometry": ring[2:]}
    relation = {"type": "relation", "id": 9, "tags": {"landuse": "forest"}, "members": [first, second]}
    assert cover_shares(parse_polygons({"elements": [relation]}), [(1.0, 1.0)]) == {"forest": 1.0, "open": 0.0}


def test_malformed_geometry_is_ignored_without_a_crash():
    broken = [
        _way({"natural": "wood"}, _square(0, 0, 1, 1)[:3]),                                # not closed
        {"type": "relation", "tags": {"natural": "wood"}, "members": []},                  # no members
        {"type": "relation", "tags": {"natural": "wood"},
         "members": [{"type": "way", "role": "inner", "geometry": _square(0, 0, 1, 1)}]},  # inner only
        {"type": "node", "tags": {"natural": "wood"}, "lat": 1, "lon": 1},
        {"type": "way", "tags": {"natural": "beach"}, "geometry": _square(0, 0, 1, 1)},    # not a cover kind
    ]
    assert parse_polygons({"elements": broken}) == []


def _ctx(make_route, fixed_now, http):
    return build_context(make_route(), DATE, http=http, now=fixed_now)


def test_plugin_reports_the_share_and_caches_it(make_route, fixed_now):
    calls = []
    forest = _way({"natural": "wood"}, _square(-0.3, 51.4, 0.0, 51.6))

    def http(url):
        calls.append(url)
        return {"elements": [forest]}

    ctx = _ctx(make_route, fixed_now, http)
    section = LandCoverPlugin().run(ctx, {})
    assert section.omit and section.shared["known"] and section.shared["forest"] == 1.0
    assert section.shared["total"] == 1.0
    LandCoverPlugin().run(ctx, {})
    assert len(calls) == 1                                  # the second run is served from the cache


def test_a_beach_route_has_no_cover(make_route, fixed_now):
    section = LandCoverPlugin().run(_ctx(make_route, fixed_now, lambda url: {"elements": []}), {})
    assert section.shared["known"] is True and section.shared["total"] == 0.0


def test_an_overpass_failure_is_unknown_not_zero(make_route, fixed_now):
    def http(url):
        raise HttpError("503")

    section = LandCoverPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert section.shared["known"] is False and section.shared["error"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_land_cover.py -q`
Expected: collection error (`day_plan.plugins.land_cover` missing).

- [ ] **Step 3: Implement** — create `scripts/day_plan/plugins/land_cover.py`:

```python
"""Forest and open ground along the route, for the tick estimate (`bio_hazards`).

One Overpass query returns the polygons that touch a 30 m corridor around the track, with their geometry; points
taken along the track (by distance, not per vertex) are tested against the polygons here. Data only: nothing is
written into the plan (`omit=True`); `shared["known"]` is False when Overpass did not answer, so the consumer can say
"terrain not determined" instead of "no forest"."""
import hashlib
import math
from dataclasses import dataclass

from ..base import Section, SectionPlugin
from ..osm_features import haversine_m, route_samples
from ..overpass import EMPTY_TTL_S, ROUTES_TTL_S, OverpassError, run

AROUND_M = 30
SAMPLE_STEP_M = 100.0
SAMPLE_MAX = 300
POLYLINE_MAX = 100
QUERY_VERSION = "1"
# (tag, value) -> kind; one table, so a region can be tuned
COVER_KINDS = {
    ("natural", "wood"): "forest", ("landuse", "forest"): "forest",
    ("natural", "scrub"): "open", ("natural", "heath"): "open", ("natural", "grassland"): "open",
    ("landuse", "meadow"): "open", ("landuse", "grass"): "open", ("landuse", "farmland"): "open",
}


@dataclass
class Polygon:
    kind: str
    outers: list       # rings of (lon, lat)
    inners: list
    bbox: tuple        # (min_lon, min_lat, max_lon, max_lat)

    def covers(self, lon: float, lat: float) -> bool:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            return False
        return (any(_in_ring(lon, lat, ring) for ring in self.outers)
                and not any(_in_ring(lon, lat, ring) for ring in self.inners))


def route_polyline(coords: list) -> str:
    return ",".join(f"{lat:.5f},{lon:.5f}" for lat, lon in route_samples(coords, POLYLINE_MAX))


def cover_query(poly: str) -> str:
    return (f'[out:json][timeout:25];(nwr(around:{AROUND_M},{poly})["natural"~"^(wood|scrub|grassland|heath)$"];'
            f'nwr(around:{AROUND_M},{poly})["landuse"~"^(forest|meadow|grass|farmland)$"];);out tags geom 400;')


def densify(coords: list, step_m: float = SAMPLE_STEP_M, max_points: int = SAMPLE_MAX) -> list:
    """[(lat, lon)] along the track about every `step_m`, at most `max_points`, both ends included."""
    points = []
    for (lon1, lat1, *_), (lon2, lat2, *_) in zip(coords, coords[1:]):
        parts = max(1, math.ceil(haversine_m(lat1, lon1, lat2, lon2) / step_m))
        for i in range(parts):
            f = i / parts
            points.append((lat1 + (lat2 - lat1) * f, lon1 + (lon2 - lon1) * f))
    last = coords[-1]
    points.append((last[1], last[0]))
    if len(points) > max_points:
        step = (len(points) - 1) / (max_points - 1)
        points = [points[round(i * step)] for i in range(max_points)]
    return points


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _stitch(ways: list) -> list:
    """Closed rings from member ways joined at identical end points; rings that cannot be closed are dropped."""
    ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while ways:
        ring = ways.pop(0)
        while ring[0] != ring[-1]:
            for i, way in enumerate(ways):
                if way[0] == ring[-1]:
                    ring = ring + way[1:]
                elif way[-1] == ring[-1]:
                    ring = ring + way[::-1][1:]
                elif way[-1] == ring[0]:
                    ring = way[:-1] + ring
                elif way[0] == ring[0]:
                    ring = way[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                break
            else:
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _kind(tags: dict):
    for key in ("natural", "landuse"):
        kind = COVER_KINDS.get((key, tags.get(key)))
        if kind:
            return kind
    return None


def _points(geometry) -> list:
    return [(g["lon"], g["lat"]) for g in geometry or [] if isinstance(g, dict) and "lat" in g and "lon" in g]


def parse_polygons(data: dict) -> list:
    polygons = []
    for element in data.get("elements", []):
        kind = _kind(element.get("tags") or {})
        if kind is None:
            continue
        if element.get("type") == "way":
            ring = _points(element.get("geometry"))
            outers, inners = ([ring] if len(ring) >= 4 and ring[0] == ring[-1] else []), []
        elif element.get("type") == "relation":
            outer_ways, inner_ways = [], []
            for member in element.get("members") or []:
                if member.get("type") == "way" and member.get("geometry"):
                    (inner_ways if member.get("role") == "inner" else outer_ways).append(_points(member["geometry"]))
            outers, inners = _stitch(outer_ways), _stitch(inner_ways)
        else:
            continue
        if outers:
            xs = [x for ring in outers for x, _ in ring]
            ys = [y for ring in outers for _, y in ring]
            polygons.append(Polygon(kind, outers, inners, (min(xs), min(ys), max(xs), max(ys))))
    return polygons


def cover_shares(polygons: list, samples: list) -> dict:
    counts = {"forest": 0, "open": 0}
    for lat, lon in samples:
        hit = None
        for polygon in polygons:
            if polygon.covers(lon, lat):
                if polygon.kind == "forest":
                    hit = "forest"
                    break
                hit = "open"
        if hit:
            counts[hit] += 1
    total = len(samples) or 1
    return {kind: count / total for kind, count in counts.items()}


class LandCoverPlugin(SectionPlugin):
    """Data only: the share of the route on forest and on open ground (meadows, fields, scrub, heath)."""
    plugin_id = "land_cover"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        samples = densify(ctx.coords)
        digest = hashlib.sha1(route_polyline(ctx.coords).encode("utf-8")).hexdigest()[:12]
        key = f"land_cover|{QUERY_VERSION}|{digest}"
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None:
            value = cached[0]
            return self._section(value["forest"], value["open"], None)
        try:
            data = run(ctx.http, cover_query(route_polyline(ctx.coords)), health=ctx.overpass_health,
                       progress=ctx.progress)
        except OverpassError as e:
            return self._section(0.0, 0.0, str(e))
        shares = cover_shares(parse_polygons(data), samples)
        ctx.cache.put(key, shares)
        return self._section(shares["forest"], shares["open"], None)

    @staticmethod
    def _section(forest: float, open_ground: float, error) -> Section:
        return Section("hazards", "", "no-data" if error else "tag-backed", omit=True,
                       shared={"known": error is None, "forest": forest, "open": open_ground,
                               "total": forest + open_ground, "error": error})
```
`EMPTY_TTL_S` is imported for symmetry with `osm_features` but not needed here: remove it from the import line if the linter complains.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_land_cover.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan/plugins/land_cover.py tests/test_land_cover.py
git commit -m "land_cover: forest and open-ground share along the route

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `bio_hazards` — ticks only on forest and grass

**Files:**
- Modify: `scripts/day_plan/plugins/bio_hazards.py`
- Modify: `scripts/day_plan/i18n_conditions.py`
- Test: `tests/test_bio_hazards.py`

**Interfaces:**
- Consumes: `shared["land_cover"] = {"known", "forest", "open", "total", "error"}` (Task 5).
- Produces: `TICK_MIN_COVER = 0.05`; `BioHazardsPlugin.depends_on` gains `"land_cover"`; keys `bio_tick_terrain`, `bio_tick_terrain_unknown`.

- [ ] **Step 1: Update the helper and write the failing tests** — in `tests/test_bio_hazards.py` change `run(...)` to take a `cover` argument (default forest-heavy so the existing tests keep their meaning):

```python
FOREST = {"known": True, "forest": 0.6, "open": 0.1, "total": 0.7, "error": None}


def run(make_route, fixed_now, weather_rows, mean=18.0, features=None, error=None, date=JULY, lang="en", facts=None,
        coords=ROUTE, light=True, with_osm=True, folder="route", cover=FOREST):
    ...
    shared = {"weather": {...}}
    if cover is not None:
        shared["land_cover"] = cover
    ...
```
(keep the rest of the helper as it is) and append:

```python
def test_no_forest_and_no_grass_means_no_tick_lines(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(), cover={"known": True, "forest": 0.0, "open": 0.02, "total": 0.02,
                                                       "error": None})
    assert "Ticks" not in section.markdown and not any("tick" in w.text.lower() for w in section.warnings)


def test_a_beach_in_australia_has_no_tick_warning(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(), date=datetime.date(2026, 1, 15), mean=22.0,
                  coords=((151.28, -33.89, 5.0), (151.29, -33.90, 8.0)),
                  cover={"known": True, "forest": 0.0, "open": 0.0, "total": 0.0, "error": None})
    assert "Ticks" not in section.markdown


def test_forest_route_shows_the_terrain_and_a_caution(make_route, fixed_now):
    section = run(make_route, fixed_now, rows())
    assert "Ticks: **high**" in section.markdown
    assert "forest ~60 %" in section.markdown and "open ground" in section.markdown and "~10 %" in section.markdown
    assert any(w.severity == "caution" and "tick" in w.text.lower() for w in section.warnings)


def test_unknown_terrain_keeps_the_line_with_a_note_and_only_an_info(make_route, fixed_now):
    unknown = {"known": False, "forest": 0.0, "open": 0.0, "total": 0.0, "error": "503"}
    for cover in (unknown, None):                       # Overpass failed / the plugin did not run
        section = run(make_route, fixed_now, rows(), cover=cover)
        assert "Ticks:" in section.markdown and "terrain type not determined" in section.markdown
        tick_warnings = [w for w in section.warnings if "tick" in w.text.lower()]
        assert tick_warnings and all(w.severity == "info" for w in tick_warnings)


def test_regional_facts_are_still_shown_without_ticks(make_route, fixed_now):
    facts = {"all": {"bio_hazards": {"markdown": "Paralysis ticks and snakes in the bush.",
                                     "sources": ["https://example.org/a"]}}}
    section = run(make_route, fixed_now, rows(), facts=facts,
                  cover={"known": True, "forest": 0.0, "open": 0.0, "total": 0.0, "error": None})
    assert "Paralysis ticks" in section.markdown


def test_russian_terrain_line(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(), lang="ru")
    assert "лес ~60 %" in section.markdown
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_bio_hazards.py -q`
Expected: the new tests FAIL; the old ones still pass (the helper passes a forest cover that is ignored for now).

- [ ] **Step 3: Implement**

`i18n_conditions.py` — `"en"`:
```python
        # ticks by terrain
        "bio_tick_terrain": "Terrain on the route: forest ~{forest} %, open ground (meadows, fields, scrub, heath) ~{open} %.",
        "bio_tick_terrain_unknown": "Terrain type not determined (the map query failed): this tick estimate does not take vegetation into account.",
```
`"ru"`:
```python
        "bio_tick_terrain": "Местность на маршруте: лес ~{forest} %, открытые места (луга, поля, кустарник, пустошь) ~{open} %.",
        "bio_tick_terrain_unknown": "Тип местности не определён (запрос к карте не удался): оценка клещей без учёта растительности.",
```

`bio_hazards.py`: add the constant `TICK_MIN_COVER = 0.05`, change `depends_on = ("weather", "light", "osm_features", "land_cover")`, and replace the tick block in `run`:

```python
        # ticks: only where the route runs through forest or open ground
        cover = shared.get("land_cover") or {}
        cover_known = bool(cover.get("known"))
        mean = weather.get("daily_mean_temp")
        terrain_ok = (not cover_known) or cover.get("total", 0.0) >= TICK_MIN_COVER
        if mean is not None and mean >= 0.0 and in_season(month, TICK_MONTHS, lat) and terrain_ok:     # no tick line on a freezing day
            band = tick_band(mean)
            lines.append("- " + tr("bio_tick", lang, band=tr("bio_band", lang)[_BANDS[band]], temp=f"{mean:.0f}"))
            if cover_known:
                lines.append("  " + tr("bio_tick_terrain", lang, forest=f"{cover['forest'] * 100:.0f}",
                                       open=f"{cover['open'] * 100:.0f}"))
            else:
                lines.append("  *" + tr("bio_tick_terrain_unknown", lang) + "*")
            if band >= 1:
                lines.append("  " + tr("bio_tick_advice", lang))
            if band == 2:
                warnings.append(PlanWarning("caution" if cover_known else "info",
                                            tr("bio_warn_tick", lang, temp=f"{mean:.0f}")))
```
(the former `mean = weather.get("daily_mean_temp")` line above the block is removed — `mean` is now set here and is also used further down in the `missing_weather` branch.)

- [ ] **Step 4: Run to verify they pass, then the suite**

Run: `python3 -m pytest tests/test_bio_hazards.py -q` → PASS; `python3 -m pytest -q` → green except possibly `test_cli.py` end-to-end tests that look for a tick line: those build a plan without `land_cover` data (the unknown-terrain path keeps the line, with an `info` warning); update an assertion only if it demands a `caution`.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan tests
git commit -m "bio_hazards: ticks only where the route runs through forest or open ground

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `water_near` — water within 500 m of the track and the points

**Files:**
- Create: `scripts/day_plan/plugins/water_near.py`
- Test: `tests/test_water_near.py`

**Interfaces:**
- Consumes: `land_cover.route_polyline`; `osm_features.haversine_m`, `route_samples`; `overpass.run`; `ctx.access_points`, `ctx.interest_points` (`RoutePoint` with `name`, `type`, `lat`, `lon`, `role`).
- Produces:
  - `RADIUS_M = 500`, `POINT_MAX = 12`
  - `@dataclass Anchor(kind, name, lat, lon)` — `kind` in `track | start | end | access | poi`
  - `@dataclass WaterBody(kind, name, lat, lon, bbox, size_km, tags, distance_m, near_kind, near_name)`; `kind` in `lake | pond | river | canal`; `bbox = (south, west, north, east)`
  - `rect_distance_m(lat, lon, bbox) -> float`
  - `water_query(poly, points) -> str`, `parse_water(data) -> (bodies, coast_bboxes, swim_spots)`, `place_bodies(bodies, anchors) -> list[WaterBody]`
  - `WaterNearPlugin` (`plugin_id = "water_near"`, `omit=True`) with `shared = {"bodies": [WaterBody], "sea": dict | None, "swim_spots": [(name, lat, lon)], "error": str | None}`; `sea = {"lat", "lon", "distance_m", "near_kind", "near_name"}`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_water_near.py`:

```python
import datetime

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.water_near import (
    Anchor, WaterNearPlugin, parse_water, place_bodies, rect_distance_m, water_query,
)

DATE = datetime.date(2026, 6, 21)


def _el(tags, bounds=None, lat=None, lon=None, type_="way"):
    element = {"type": type_, "id": 1, "tags": tags}
    if bounds:
        s, w, n, e = bounds
        element["bounds"] = {"minlat": s, "minlon": w, "maxlat": n, "maxlon": e}
        element["center"] = {"lat": (s + n) / 2, "lon": (w + e) / 2}
    if lat is not None:
        element["lat"], element["lon"] = lat, lon
    return element


def test_query_has_a_clause_for_the_track_and_for_each_point():
    points = [Anchor("poi", "Viewpoint", 40.43, -3.74), Anchor("start", "Cercedilla", 40.42, -3.75)]
    ql = water_query("40.42,-3.75,40.43,-3.74", points)
    assert "around:500,40.42,-3.75,40.43,-3.74" in ql
    assert "around:500,40.43000,-3.74000" in ql and "around:500,40.42000,-3.75000" in ql
    assert "coastline" in ql and "swimming_area" in ql and "river|canal" in ql and "out tags bb center" in ql


def test_rect_distance_is_zero_inside_and_grows_outside():
    bbox = (40.0, -4.0, 40.1, -3.9)
    assert rect_distance_m(40.05, -3.95, bbox) == 0.0
    assert 1000 < rect_distance_m(40.05, -3.8, bbox) < 1200


def test_parse_classifies_kinds_and_sizes():
    data = {"elements": [
        _el({"natural": "water", "name": "Big lake"}, bounds=(40.0, -4.0, 40.1, -3.9)),
        _el({"natural": "water", "water": "pond"}, bounds=(40.0, -4.0, 40.001, -3.999)),
        _el({"waterway": "river", "name": "Rio Guadarrama"}, bounds=(40.0, -4.0, 40.02, -3.98)),
        _el({"waterway": "canal"}, bounds=(40.0, -4.0, 40.0, -3.99)),
        _el({"natural": "coastline"}, bounds=(36.0, -5.0, 36.1, -4.9)),
        _el({"leisure": "swimming_area", "name": "Playa"}, lat=36.05, lon=-4.95, type_="node"),
        _el({"natural": "water", "water": "reservoir", "name": "Embalse"}, bounds=(40.2, -4.0, 40.3, -3.9)),
    ]}
    bodies, coast, spots = parse_water(data)
    kinds = {b.name or b.kind: b.kind for b in bodies}
    assert kinds["Big lake"] == "lake" and kinds["pond"] == "pond" and kinds["Rio Guadarrama"] == "river"
    assert kinds["canal"] == "canal" and kinds["Embalse"] == "lake"
    assert len(coast) == 1 and spots == [("Playa", 36.05, -4.95)]
    big = next(b for b in bodies if b.name == "Big lake")
    assert 12 < big.size_km < 16                    # the bbox diagonal of 0.1 x 0.1 degrees


def test_parse_keeps_the_swimming_tags_and_merges_named_pieces():
    data = {"elements": [
        _el({"natural": "water", "name": "Lago", "swimming": "no"}, bounds=(40.0, -4.0, 40.1, -3.9)),
        _el({"natural": "water", "name": "Lago"}, bounds=(40.0, -4.0, 40.01, -3.99)),
    ]}
    bodies, _, _ = parse_water(data)
    assert len(bodies) == 1 and bodies[0].tags["swimming"] == "no" and bodies[0].size_km > 10


def test_place_names_what_the_water_is_near():
    lake = parse_water({"elements": [_el({"natural": "water", "name": "Lago"}, bounds=(40.0, -4.0, 40.01, -3.99))]})[0]
    anchors = [Anchor("track", "", 41.0, -3.0), Anchor("poi", "Mirador", 40.0105, -3.985)]
    placed = place_bodies(lake, anchors)
    assert placed[0].near_kind == "poi" and placed[0].near_name == "Mirador" and placed[0].distance_m < 100


def _ctx(make_route_with_points, fixed_now, http, points=()):
    return build_context(make_route_with_points(list(points)), DATE, http=http, now=fixed_now)


def test_plugin_finds_the_sea_and_the_lakes_and_caches(make_route_with_points, fixed_now):
    calls = []

    def http(url):
        calls.append(url)
        return {"elements": [
            _el({"natural": "coastline"}, bounds=(40.41, -3.76, 40.44, -3.73)),
            _el({"natural": "water", "name": "Lago"}, bounds=(40.425, -3.745, 40.427, -3.743)),
        ]}

    ctx = _ctx(make_route_with_points, fixed_now, http,
               [("Mirador", "viewpoint", -3.742, 40.428, {}), ("Cercedilla", "access", -3.75, 40.42, {"role": "start"})])
    section = WaterNearPlugin().run(ctx, {})
    assert section.omit and section.shared["error"] is None
    assert section.shared["sea"]["near_kind"] in ("track", "start", "poi", "access")
    assert [b.name for b in section.shared["bodies"]] == ["Lago"]
    assert "around:500,40.42800,-3.74200" in calls[0]            # the point of interest is a centre
    WaterNearPlugin().run(ctx, {})
    assert len(calls) == 1


def test_nothing_nearby_is_an_empty_result_not_an_error(make_route_with_points, fixed_now):
    section = WaterNearPlugin().run(_ctx(make_route_with_points, fixed_now, lambda u: {"elements": []}), {})
    assert section.shared == {"bodies": [], "sea": None, "swim_spots": [], "error": None}


def test_overpass_failure_is_reported(make_route_with_points, fixed_now):
    def http(url):
        raise HttpError("503")

    section = WaterNearPlugin().run(_ctx(make_route_with_points, fixed_now, http), {})
    assert section.shared["error"] and section.shared["bodies"] == [] and section.confidence == "no-data"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_water_near.py -q`
Expected: collection error.

- [ ] **Step 3: Implement** — create `scripts/day_plan/plugins/water_near.py`:

```python
"""Water within 500 m of the track and of the points of the route (OpenStreetMap, Overpass).

One `around` query: one clause set for the track (a polyline) and one per point of interest or access point (at most
POINT_MAX). The answer carries bounding boxes; the distance to a body is measured to its box, which is exact enough
for "what is near" and never longer than the true distance. Data only (`omit=True`); `shared["error"]` is set when
Overpass did not answer."""
import math
from dataclasses import asdict, dataclass

from ..base import Section, SectionPlugin
from ..osm_features import haversine_m, route_samples
from ..overpass import EMPTY_TTL_S, ROUTES_TTL_S, OverpassError, run
from .land_cover import route_polyline

RADIUS_M = 500
POINT_MAX = 12
QUERY_VERSION = "1"
KEEP_TAGS = ("swimming", "bathing", "access", "sport", "water", "salt")
_FILTERS = ('["natural"~"^(water|coastline)$"]', '["waterway"~"^(river|canal)$"]',
            '["leisure"~"^(swimming_area|bathing_place)$"]')


@dataclass
class Anchor:
    kind: str        # track | start | end | access | poi
    name: str
    lat: float
    lon: float


@dataclass
class WaterBody:
    kind: str        # lake | pond | river | canal
    name: str
    lat: float
    lon: float
    bbox: tuple      # (south, west, north, east)
    size_km: float
    tags: dict
    distance_m: float = 0.0
    near_kind: str = "track"
    near_name: str = ""


def rect_distance_m(lat: float, lon: float, bbox) -> float:
    south, west, north, east = bbox
    return haversine_m(lat, lon, min(max(lat, south), north), min(max(lon, west), east))


def point_anchors(ctx) -> list:
    anchors = []
    for point in ctx.access_points:
        anchors.append(Anchor(point.role if point.role in ("start", "end") else "access", point.name,
                              point.lat, point.lon))
    for point in ctx.interest_points:
        anchors.append(Anchor("poi", point.name, point.lat, point.lon))
    return anchors[:POINT_MAX]


def water_query(poly: str, points: list) -> str:
    around = [f"around:{RADIUS_M},{poly}"] + [f"around:{RADIUS_M},{a.lat:.5f},{a.lon:.5f}" for a in points]
    body = "".join(f"nwr({a}){f};" for a in around for f in _FILTERS)
    return f"[out:json][timeout:25];({body});out tags bb center 800;"


def _bbox(element: dict):
    bounds = element.get("bounds")
    if isinstance(bounds, dict) and all(k in bounds for k in ("minlat", "minlon", "maxlat", "maxlon")):
        return (bounds["minlat"], bounds["minlon"], bounds["maxlat"], bounds["maxlon"])
    centre = element.get("center") or element
    if isinstance(centre.get("lat"), (int, float)) and isinstance(centre.get("lon"), (int, float)):
        return (centre["lat"], centre["lon"], centre["lat"], centre["lon"])
    return None


def _diagonal_km(bbox) -> float:
    south, west, north, east = bbox
    return haversine_m(south, west, north, east) / 1000.0


def _water_kind(tags: dict):
    if tags.get("waterway") in ("river", "canal"):
        return tags["waterway"]
    if tags.get("natural") == "water":
        water = tags.get("water")
        if water == "pond":
            return "pond"
        if water in ("river", "canal"):
            return water
        return "lake"
    return None


def parse_water(data: dict) -> tuple:
    """(bodies, coastline bounding boxes, swim spots [(name, lat, lon)]). Named pieces of one body are merged
    (the largest box and every swimming tag are kept)."""
    bodies, coast, spots, named = [], [], [], {}
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        bbox = _bbox(element)
        if bbox is None:
            continue
        centre = element.get("center") or element
        lat, lon = float(centre.get("lat", bbox[0])), float(centre.get("lon", bbox[1]))
        if tags.get("natural") == "coastline":
            coast.append(bbox)
            continue
        if tags.get("leisure") in ("swimming_area", "bathing_place"):
            spots.append((str(tags.get("name", "")), lat, lon))
            continue
        kind = _water_kind(tags)
        if kind is None:
            continue
        body = WaterBody(kind, str(tags.get("name", "")), lat, lon, bbox, _diagonal_km(bbox),
                         {k: tags[k] for k in KEEP_TAGS if k in tags})
        key = (kind, body.name)
        if body.name and key in named:
            old = named[key]
            old.tags = {**body.tags, **old.tags}
            if body.size_km > old.size_km:
                old.bbox, old.size_km, old.lat, old.lon = body.bbox, body.size_km, body.lat, body.lon
            continue
        if body.name:
            named[key] = body
        bodies.append(body)
    return bodies, coast, spots


def _nearest(bbox, anchors: list):
    return min(((rect_distance_m(a.lat, a.lon, bbox), a) for a in anchors), key=lambda pair: pair[0])


def place_bodies(bodies: list, anchors: list) -> list:
    for body in bodies:
        distance, anchor = _nearest(body.bbox, anchors)
        body.distance_m, body.near_kind, body.near_name = min(distance, float(RADIUS_M)), anchor.kind, anchor.name
    return bodies


class WaterNearPlugin(SectionPlugin):
    plugin_id = "water_near"
    section_id = "hazards"

    def run(self, ctx, shared: dict) -> Section:
        points = point_anchors(ctx)
        poly = route_polyline(ctx.coords)
        key = f"water_near|{QUERY_VERSION}|" + str(hash((poly, tuple((p.lat, p.lon) for p in points))) & 0xFFFFFFFF)
        cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
        if cached is not None and (cached[0]["bodies"] or cached[0]["sea"] or cached[0]["swim_spots"]
                                   or ctx.now.timestamp() - cached[1] <= EMPTY_TTL_S):
            value = cached[0]
            bodies = [WaterBody(**{**b, "bbox": tuple(b["bbox"])}) for b in value["bodies"]]
            return self._section(bodies, value["sea"], [tuple(s) for s in value["swim_spots"]], None)
        try:
            data = run(ctx.http, water_query(poly, points), health=ctx.overpass_health, progress=ctx.progress)
        except OverpassError as e:
            return self._section([], None, [], str(e))
        bodies, coast, spots = parse_water(data)
        anchors = [Anchor("track", "", lat, lon) for lat, lon in route_samples(ctx.coords)] + points
        place_bodies(bodies, anchors)
        sea = None
        if coast:
            distance, anchor = min((_nearest(bbox, anchors) for bbox in coast), key=lambda pair: pair[0])
            sea = {"lat": anchor.lat, "lon": anchor.lon, "distance_m": min(distance, float(RADIUS_M)),
                   "near_kind": anchor.kind, "near_name": anchor.name}
        ctx.cache.put(key, {"bodies": [asdict(b) for b in bodies], "sea": sea, "swim_spots": spots})
        return self._section(bodies, sea, spots, None)

    @staticmethod
    def _section(bodies: list, sea, spots: list, error) -> Section:
        return Section("hazards", "", "no-data" if error else "tag-backed", omit=True,
                       shared={"bodies": bodies, "sea": sea, "swim_spots": spots, "error": error})
```
Note: `hash()` of a tuple of floats is stable within one process only for str; use a stable digest instead — replace the `key = ...` line with:
```python
        digest = hashlib.sha1(f"{poly}|{[(round(p.lat, 5), round(p.lon, 5)) for p in points]}".encode("utf-8")).hexdigest()[:12]
        key = f"water_near|{QUERY_VERSION}|{digest}"
```
and add `import hashlib` to the imports (remove the unused `math` import).

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_water_near.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan/plugins/water_near.py tests/test_water_near.py
git commit -m "water_near: water within 500 m of the track and the points of the route

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Marine data, inland estimate and the `water` section

**Files:**
- Create: `scripts/day_plan/marine.py`
- Create: `scripts/day_plan/plugins/water.py`
- Modify: `scripts/day_plan/i18n_conditions.py`
- Test: `tests/test_marine.py`, `tests/test_water.py`

**Interfaces:**
- Consumes: `shared["water_near"]` (Task 7: `bodies` sorted here by `size_km`, `sea`, `swim_spots`, `error`), `shared["weather"]["window_rows"]` (Task 4; rows with `day`, `hour`), `weather._same_day_in_year`, `weather.FORECAST_URL`, `ARCHIVE_URL`, `FORECAST_HORIZON_DAYS`; `facts.lookup(ctx.facts, ctx.date_iso, "water")`; `common.cell`, `sources_line`.
- Produces in `marine.py`: `MARINE_URL`, `fetch_marine_day(ctx, lat, lon, date) -> {"sst": [...], "level": [...]}`, `mean_sst(day) -> float | None`, `find_sea_day(ctx, lat, lon, date) -> (day, lat, lon) | None`, `sea_temperature(ctx, lat, lon) -> {"temp", "kind": "model"|"climatology", "point", "day"} | None`, `tide_extrema(levels) -> [(kind, hours_float, level)]`.
- Produces in `water.py`: `tau_days`, `estimate_inland_temp(air_means, kind, size_km)`, `air_history(ctx, lat, lon)`, `bathing_status(tags, near_spot)`, `WaterPlugin` (`plugin_id = "water"`, `section_id = "hazards"`, `title_key = "hz_water"`, `depends_on = ("weather", "water_near")`); `Section.shared["water_applies"] = True` when anything is shown.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_marine.py`:

```python
import datetime
import math

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.marine import fetch_marine_day, find_sea_day, mean_sst, sea_temperature, tide_extrema

DATE = datetime.date(2026, 6, 21)


def _day(sst=21.0, level=None):
    level = level if level is not None else [round(1.5 * math.sin(2 * math.pi * (h - 3) / 12.42), 3) for h in range(24)]
    return {"hourly": {"time": [f"2026-06-21T{h:02d}:00" for h in range(24)],
                       "sea_surface_temperature": [sst] * 24, "sea_level_height_msl": level}}


def _ctx(make_route, fixed_now, http):
    return build_context(make_route(), DATE, http=http, now=fixed_now)


def test_tide_extrema_finds_highs_and_lows_with_sub_hour_times():
    levels = [1.5 * math.sin(2 * math.pi * (h - 3) / 12.42) for h in range(24)]
    events = tide_extrema(levels)
    kinds = [e[0] for e in events]
    assert kinds[:2] == ["high", "low"] and abs(events[0][1] - (3 + 12.42 / 4)) < 0.3
    assert abs(events[0][2] - 1.5) < 0.05 and abs(events[1][2] + 1.5) < 0.05


def test_tide_extrema_ignores_gaps_and_flat_series():
    assert tide_extrema([0.0] * 24) == []
    assert tide_extrema([None, 1.0, None, 2.0]) == []


def test_fetch_is_cached_and_reads_the_marine_api(make_route, fixed_now):
    urls = []

    def http(url):
        urls.append(url)
        return _day()

    ctx = _ctx(make_route, fixed_now, http)
    day = fetch_marine_day(ctx, 43.5, -3.5, DATE)
    fetch_marine_day(ctx, 43.5, -3.5, DATE)
    assert len(urls) == 1 and urls[0].startswith("https://marine-api.open-meteo.com/v1/marine?")
    assert "sea_surface_temperature,sea_level_height_msl" in urls[0] and "start_date=2026-06-21" in urls[0]
    assert mean_sst(day) == 21.0


def test_a_land_cell_falls_back_to_a_neighbouring_grid_point(make_route, fixed_now):
    seen = []

    def http(url):
        seen.append(url)
        return _day(sst=None) if len(seen) == 1 else _day(sst=19.5)

    found = find_sea_day(_ctx(make_route, fixed_now, http), 43.5, -3.5, DATE)
    assert found is not None and mean_sst(found[0]) == 19.5 and len(seen) == 2


def test_a_service_error_gives_nothing_without_hammering(make_route, fixed_now):
    seen = []

    def http(url):
        seen.append(url)
        raise HttpError("400")

    assert find_sea_day(_ctx(make_route, fixed_now, http), 43.5, -3.5, DATE) is None and len(seen) == 1


def test_beyond_the_horizon_the_temperature_is_a_climatology(make_route, fixed_now):
    def http(url):
        if "2026-06-21" in url:
            raise HttpError("400")
        return _day(sst=20.0)

    result = sea_temperature(_ctx(make_route, fixed_now, http), 43.5, -3.5)
    assert result["kind"] == "climatology" and result["temp"] == 20.0 and result["day"] is None


def test_everything_failing_is_none(make_route, fixed_now):
    def http(url):
        raise HttpError("500")

    assert sea_temperature(_ctx(make_route, fixed_now, http), 43.5, -3.5) is None
```

Create `tests/test_water.py`:

```python
import datetime
import math

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.water import (
    WaterPlugin, bathing_status, estimate_inland_temp, tau_days,
)
from day_plan.plugins.water_near import WaterBody

DATE = datetime.date(2026, 6, 21)


def _body(name, size, kind="lake", tags=None, distance=120.0, near_kind="track", near_name=""):
    return WaterBody(kind, name, 40.0, -3.0, (40.0, -3.0, 40.0, -3.0), size, tags or {}, distance, near_kind, near_name)


def _near(bodies=(), sea=None, spots=()):
    return {"bodies": list(bodies), "sea": sea, "swim_spots": list(spots), "error": None}


SEA = {"lat": 43.5, "lon": -3.5, "distance_m": 80.0, "near_kind": "start", "near_name": "Playa"}


def _weather(last_hour=23):
    rows = [{"hour": h, "day": 0} for h in range(24)] + [{"hour": h, "day": 1} for h in range(last_hour - 23)]
    return {"window_rows": rows}


def _marine(sst=21.0):
    level = [round(1.5 * math.sin(2 * math.pi * (h - 3) / 12.42), 3) for h in range(24)]
    return {"hourly": {"time": [f"2026-06-21T{h:02d}:00" for h in range(24)],
                       "sea_surface_temperature": [sst] * 24, "sea_level_height_msl": level}}


def _http(sst=21.0, air=20.0):
    def http(url):
        if "marine-api" in url:
            return _marine(sst)
        if "temperature_2m_mean" in url:
            return {"daily": {"temperature_2m_mean": [air] * 31}}
        raise HttpError("unexpected " + url)
    return http


def _run(make_route, fixed_now, near, http=None, lang="en", facts=None, weather=None):
    import json
    route_dir = make_route()
    if facts:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, DATE, lang=lang, http=http or _http(), now=fixed_now)
    return WaterPlugin().run(ctx, {"water_near": near, "weather": weather or _weather()})


# ---- pure helpers -------------------------------------------------------------------------------
def test_estimate_follows_the_air_with_a_lag():
    assert estimate_inland_temp([20.0] * 30, "lake", 3.0) == pytest.approx(20.0)
    warming = [5.0] * 20 + [25.0] * 10
    pond, big = estimate_inland_temp(warming, "pond", 0.1), estimate_inland_temp(warming, "lake", 40.0)
    assert pond > big > 5.0 and pond < 25.0
    assert estimate_inland_temp([-8.0] * 30, "lake", 3.0) == 0.0          # never below freezing
    assert estimate_inland_temp([20.0, None, 21.0], "lake", 3.0) is None  # too little history


def test_a_river_reacts_faster_than_a_lake():
    assert tau_days("river", 5.0) < tau_days("lake", 5.0) < tau_days("lake", 50.0)


@pytest.mark.parametrize("tags,spot,expected", [
    ({"swimming": "yes"}, False, "allowed"), ({"swimming": "no"}, True, "forbidden"),
    ({"bathing": "yes"}, False, "allowed"), ({}, True, "allowed"), ({"sport": "swimming"}, False, "allowed"),
    ({}, False, "unknown"),
])
def test_bathing_status_from_osm_tags(tags, spot, expected):
    assert bathing_status(tags, spot) == expected


# ---- the section ---------------------------------------------------------------------------------
def test_nothing_nearby_leaves_the_section_out(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near())
    assert section.omit


def test_overpass_failure_is_no_data(make_route, fixed_now):
    near = {"bodies": [], "sea": None, "swim_spots": [], "error": "503"}
    section = _run(make_route, fixed_now, near)
    assert section.confidence == "no-data" and "could not be determined" in section.markdown


def test_sea_is_a_separate_first_row_with_temperature_and_tides(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA))
    lines = section.markdown.splitlines()
    rows = [l for l in lines if l.startswith("| ") and "---" not in l][1:]
    assert rows[0].startswith("| Sea or ocean coast") and "21 °C" in rows[0] and "at the start point" in rows[0]
    assert "Tides" in section.markdown and "high water" in section.markdown and "low water" in section.markdown
    assert section.confidence == "derived" and section.shared["water_applies"] is True
    assert any("Tidal range" in w.text for w in section.warnings)          # 3 m range


def test_two_largest_bodies_get_data_the_rest_are_listed(make_route, fixed_now):
    bodies = [_body("Pond A", 0.2, "pond"), _body("Lago Grande", 9.0), _body("Rio X", 4.0, "river"),
              _body("Stream B", 0.1, "river")]
    section = _run(make_route, fixed_now, _near(bodies))
    text = section.markdown
    assert text.index("Lago Grande") < text.index("Rio X") < text.index("Other water within 500 m")
    table = text.split("Other water within 500 m")[0]
    assert "Pond A" not in table and "Stream B" not in table
    listed = text.split("Other water within 500 m")[1]
    assert "Pond A (pond)" in listed and "Stream B (river)" in listed
    assert "~20 °C" in table or "~19 °C" in table                       # an estimate, marked with "~"


def test_the_list_of_the_rest_is_cut_at_fifteen(make_route, fixed_now):
    bodies = [_body(f"Pond {i}", 0.1 + i / 100, "pond") for i in range(30)]
    text = _run(make_route, fixed_now, _near(bodies)).markdown
    assert text.count("(pond)") == 15 and "…and 13 more." in text


def test_bathing_comes_from_osm_tags_and_swim_spots(make_route, fixed_now):
    near = _near([_body("Lago", 5.0, tags={"swimming": "no"}), _body("Embalse", 4.0)],
                 spots=[("Playa fluvial", 40.0, -3.0)])
    text = _run(make_route, fixed_now, near).markdown
    assert "forbidden (OSM)" in text and "allowed (OSM)" in text


def test_cold_water_gets_one_caution(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_http(air=8.0))
    cold = [w for w in section.warnings if "Cold water" in w.text]
    assert len(cold) == 1 and cold[0].severity == "caution"


def test_ice_is_possible_in_the_cold(make_route, fixed_now):
    assert "ice is possible" in _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_http(air=-3.0)).markdown


def test_a_forbidden_swim_spot_gets_no_cold_shock_warning(make_route, fixed_now):
    near = _near([_body("Lago", 5.0, tags={"swimming": "no"})])
    assert not [w for w in _run(make_route, fixed_now, near, http=_http(air=8.0)).warnings if "Cold" in w.text]


def test_pollution_and_hazards_come_from_the_water_fact(make_route, fixed_now):
    facts = {"all": {"water": {"markdown": "Bathing water quality: excellent (EEA). Strong rip currents at low tide.",
                               "sources": ["https://example.org/bathing"],
                               "warnings": [{"severity": "caution", "text": "Rip currents at low tide"}]}}}
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), facts=facts)
    assert "Strong rip currents" in section.markdown and section.confidence == "web-sourced"
    assert any(w.text == "Rip currents at low tide" for w in section.warnings)
    plain = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]))
    assert "No data on pollution" in plain.markdown and plain.confidence == "derived"


def test_marine_failure_keeps_the_rest(make_route, fixed_now):
    def http(url):
        if "marine-api" in url:
            raise HttpError("500")
        return {"daily": {"temperature_2m_mean": [20.0] * 31}}

    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), http=http)
    assert "Sea or ocean coast" in section.markdown and "–" in section.markdown and "Lago" in section.markdown


def test_air_history_failure_gives_a_dash_for_the_inland_temperature(make_route, fixed_now):
    def http(url):
        raise HttpError("500")

    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=http)
    assert "Lago" in section.markdown and "~" not in section.markdown.split("Lago")[1].splitlines()[0]


def test_tides_over_midnight_use_the_next_day(make_route, fixed_now):
    urls = []
    base = _http()

    def http(url):
        urls.append(url)
        return base(url)

    _run(make_route, fixed_now, _near(sea=SEA), http=http, weather=_weather(last_hour=27))
    assert any("start_date=2026-06-22" in u for u in urls)


def test_russian(make_route, fixed_now):
    text = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), lang="ru").markdown
    assert "Море или океан" in text and "Приливы" in text and "у точки старта" in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_marine.py tests/test_water.py -q`
Expected: collection errors (modules missing).

- [ ] **Step 3: Implement**

3a. Create `scripts/day_plan/marine.py`:

```python
"""Open-Meteo Marine API: sea surface temperature and sea level (tides included) — free, no key, a grid of about
28 km, a forecast horizon of about 9 days (later dates answer HTTP 400 or null). Beyond the horizon the temperature is
the mean of the same date over previous years, and the tides are not available. Lakes return null here."""
import datetime

from .http import HttpError
from .plugins.weather import _same_day_in_year

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
MARINE_TTL_S = 3 * 3600
MARINE_CLIMATE_YEARS = 3
GRID_STEP_DEG = 0.15
_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))     # the point itself, then its neighbours (a coastal cell can be land)


def _url(lat: float, lon: float, date: datetime.date) -> str:
    d = date.isoformat()
    return (f"{MARINE_URL}?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&hourly=sea_surface_temperature,sea_level_height_msl&start_date={d}&end_date={d}&timezone=auto")


def fetch_marine_day(ctx, lat: float, lon: float, date: datetime.date) -> dict:
    """{"sst": [24 values], "level": [24 values]}; HttpError / KeyError propagate."""
    key = f"marine|{lat:.2f}|{lon:.2f}|{date.isoformat()}"
    cached = ctx.cache.get_entry(key, MARINE_TTL_S)
    if cached is not None:
        return cached[0]
    hourly = ctx.http(_url(lat, lon, date))["hourly"]
    value = {"sst": list(hourly.get("sea_surface_temperature") or []), "level": list(hourly.get("sea_level_height_msl") or [])}
    ctx.cache.put(key, value)
    return value


def mean_sst(day: dict):
    values = [v for v in day.get("sst", []) if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def find_sea_day(ctx, lat: float, lon: float, date: datetime.date):
    """(day, lat, lon) of the first grid point that has a sea temperature; None when none has, or on a service error
    (which is not retried on the neighbours)."""
    for dy, dx in _OFFSETS:
        la, lo = lat + dy * GRID_STEP_DEG, lon + dx * GRID_STEP_DEG
        try:
            day = fetch_marine_day(ctx, la, lo, date)
        except (HttpError, KeyError, TypeError, ValueError):
            return None
        if mean_sst(day) is not None:
            return day, la, lo
    return None


def sea_temperature(ctx, lat: float, lon: float):
    """{"temp", "kind": "model" | "climatology", "point": (lat, lon) | None, "day": marine day | None}, or None."""
    found = find_sea_day(ctx, lat, lon, ctx.date)
    if found:
        return {"temp": mean_sst(found[0]), "kind": "model", "point": (found[1], found[2]), "day": found[0]}
    temps = []
    for back in range(1, MARINE_CLIMATE_YEARS + 1):
        past = find_sea_day(ctx, lat, lon, _same_day_in_year(ctx.date, ctx.today.year - back))
        if past:
            temps.append(mean_sst(past[0]))
    if temps:
        return {"temp": sum(temps) / len(temps), "kind": "climatology", "point": None, "day": None}
    return None


def tide_extrema(levels: list) -> list:
    """[(kind "high" | "low", hours since the midnight of the first day (float), level)] of an hourly series, the time
    refined by a parabola through the three hours around the extreme."""
    out = []
    for i in range(1, len(levels) - 1):
        a, b, c = levels[i - 1], levels[i], levels[i + 1]
        if None in (a, b, c):
            continue
        if b > a and b >= c:
            kind = "high"
        elif b < a and b <= c:
            kind = "low"
        else:
            continue
        denominator = a - 2 * b + c
        shift = 0.5 * (a - c) / denominator if denominator else 0.0
        out.append((kind, i + max(-0.5, min(0.5, shift)), b))
    return out
```

3b. Strings. `i18n_conditions.py` `"en"`:

```python
        # water nearby
        "hz_water": "Water nearby",
        "wt_col_water": "Water", "wt_col_near": "Near", "wt_col_temp": "Water temperature", "wt_col_bathing": "Bathing",
        "wt_sea": "Sea or ocean coast",
        "wt_kind": {"lake": "lake", "pond": "pond", "river": "river", "canal": "canal"},
        "wt_unnamed": "unnamed",
        "wt_near_track": "at the track", "wt_near_start": "at the start point", "wt_near_end": "at the end point",
        "wt_near_access": "at an access point {name}", "wt_near_poi": "at {name}",
        "wt_near": "{what}, ~{m} m",
        "wt_temp_model": "{temp} °C (model, daily mean)",
        "wt_temp_climate": "{temp} °C (average of this date in past years, not a forecast)",
        "wt_temp_estimate": "~{temp} °C (estimate from air temperature, error a few degrees)",
        "wt_temp_ice": "; ice is possible",
        "wt_bathing": {"allowed": "allowed (OSM)", "forbidden": "forbidden (OSM)", "unknown": "not stated — check locally"},
        "wt_tides": "Tides (model, heights relative to mean sea level, a guide — not a navigation table): {events}.",
        "wt_tide_names": {"high": "high water", "low": "low water"},
        "wt_tides_unavailable": "Tide data are not available this far ahead.",
        "wt_others": "Other water within 500 m:",
        "wt_other_line": "{name} ({kind}), ~{m} m, {near}",
        "wt_more": "…and {n} more.",
        "wt_pollution_none": "No data on pollution and water hazards are recorded; check local sources before swimming.",
        "wt_web_title": "**Pollution and hazards (web-sourced, not verified in person)**",
        "wt_warn_cold": "Cold water ({name}, about {temp} °C): cold shock and hypothermia are possible when swimming.",
        "wt_warn_tide": "Tidal range about {range} m: beaches and spits can be cut off; plan coastal sections around the tides.",
        "wt_unavailable": "Water bodies near the route could not be determined ({reason}).",
```
`"ru"`:
```python
        "hz_water": "Водоёмы рядом",
        "wt_col_water": "Водоём", "wt_col_near": "Где", "wt_col_temp": "Температура воды", "wt_col_bathing": "Купание",
        "wt_sea": "Побережье моря или океана",
        "wt_kind": {"lake": "озеро", "pond": "пруд", "river": "река", "canal": "канал"},
        "wt_unnamed": "без названия",
        "wt_near_track": "у трека", "wt_near_start": "у точки старта", "wt_near_end": "у точки финиша",
        "wt_near_access": "у точки заброски {name}", "wt_near_poi": "у точки {name}",
        "wt_near": "{what}, ~{m} м",
        "wt_temp_model": "{temp} °C (модель, среднесуточная)",
        "wt_temp_climate": "{temp} °C (средняя за эту дату в прошлые годы, не прогноз)",
        "wt_temp_estimate": "~{temp} °C (оценка по температуре воздуха, погрешность несколько градусов)",
        "wt_temp_ice": "; возможен лёд",
        "wt_bathing": {"allowed": "разрешено (OSM)", "forbidden": "запрещено (OSM)", "unknown": "не указано — уточните на месте"},
        "wt_tides": "Приливы и отливы (модель, высота относительно среднего уровня моря, ориентир — не навигационная таблица): {events}.",
        "wt_tide_names": {"high": "полная вода", "low": "малая вода"},
        "wt_tides_unavailable": "Данных о приливах на такую дату нет.",
        "wt_others": "Другие водоёмы в пределах 500 м:",
        "wt_other_line": "{name} ({kind}), ~{m} м, {near}",
        "wt_more": "…и ещё {n}.",
        "wt_pollution_none": "Данных о загрязнении и опасностях воды не записано; перед купанием проверьте местные источники.",
        "wt_web_title": "**Загрязнение и опасности (из интернета, лично не проверено)**",
        "wt_warn_cold": "Холодная вода ({name}, около {temp} °C): при купании возможны холодовой шок и переохлаждение.",
        "wt_warn_tide": "Размах прилива около {range} м: пляжи и косы могут отрезаться водой; планируйте прибрежные участки с учётом приливов.",
        "wt_unavailable": "Водоёмы рядом с маршрутом определить не удалось ({reason}).",
```

3c. Create `scripts/day_plan/plugins/water.py`:

```python
"""The "Water nearby" section: the sea or ocean coast first (temperature and tides from the Open-Meteo Marine API),
then the two largest other bodies within 500 m of the route (a lake or river temperature is an estimate from the air
temperature of the previous weeks — no free global source of measured values exists), the rest as a list. Bathing
comes from OSM tags; pollution and hazards from a web-sourced `water` fact. Confidence: web-sourced when a fact is
used, else derived."""
import datetime

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..http import HttpError
from ..i18n import tr
from ..marine import fetch_marine_day, sea_temperature, tide_extrema
from .common import cell, sources_line
from .water_near import RADIUS_M, rect_distance_m
from .weather import ARCHIVE_URL, FORECAST_HORIZON_DAYS, FORECAST_URL, _same_day_in_year

DETAILED = 2
LIST_MAX = 15
AIR_HISTORY_DAYS = 30
AIR_YEARS = 3
AIR_TTL_S = 6 * 3600
COLD_WATER_C = 15.0
ICE_C = 4.0
BIG_TIDE_M = 2.0
SWIM_SPOT_M = 300.0


def tau_days(kind: str, size_km: float) -> float:
    """The lag (days) with which the surface water follows the air temperature."""
    if kind == "canal":
        return 2.0
    if kind == "river":
        return 3.0
    if size_km < 0.5:
        return 4.0
    if size_km < 5.0:
        return 10.0
    if size_km < 30.0:
        return 18.0
    return 28.0


def estimate_inland_temp(air_means: list, kind: str, size_km: float):
    """Exponentially smoothed air temperature (oldest day first); None with fewer than 20 usable days."""
    values = [v for v in air_means if isinstance(v, (int, float))]
    if len(values) < 20:
        return None
    tau = tau_days(kind, size_km)
    water = values[0]
    for value in values[1:]:
        water += (value - water) / tau
    return max(0.0, water)


def _daily_means(ctx, base: str, lat: float, lon: float, start: datetime.date, end: datetime.date) -> list:
    url = (f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&daily=temperature_2m_mean"
           f"&start_date={start.isoformat()}&end_date={end.isoformat()}&timezone=auto")
    return ctx.http(url)["daily"]["temperature_2m_mean"]


def air_history(ctx, lat: float, lon: float):
    """Daily mean air temperatures of the AIR_HISTORY_DAYS before the date (oldest first), or None."""
    key = f"air_history|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, AIR_TTL_S)
    if cached is not None:
        return cached[0]
    start, end = ctx.date - datetime.timedelta(days=AIR_HISTORY_DAYS), ctx.date - datetime.timedelta(days=1)
    try:
        if (ctx.today - ctx.date).days > 55:
            means = _daily_means(ctx, ARCHIVE_URL, lat, lon, start, end)
        elif (ctx.date - ctx.today).days <= FORECAST_HORIZON_DAYS:
            means = _daily_means(ctx, FORECAST_URL, lat, lon, start, end)
        else:                                              # beyond the forecast: the same weeks of previous years
            per_year = []
            for back in range(1, AIR_YEARS + 1):
                year = ctx.today.year - back
                per_year.append(_daily_means(ctx, ARCHIVE_URL, lat, lon, _same_day_in_year(start, year),
                                             _same_day_in_year(end, year)))
            length = min(len(m) for m in per_year)
            means = []
            for i in range(length):
                column = [m[i] for m in per_year if isinstance(m[i], (int, float))]
                means.append(sum(column) / len(column) if column else None)
    except (HttpError, KeyError, IndexError, TypeError, ValueError):
        return None
    ctx.cache.put(key, means)
    return means


def bathing_status(tags: dict, near_spot: bool) -> str:
    for key in ("swimming", "bathing"):
        value = tags.get(key)
        if value in ("yes", "designated", "permissive"):
            return "allowed"
        if value in ("no", "prohibited"):
            return "forbidden"
    if near_spot or tags.get("sport") == "swimming":
        return "allowed"
    return "unknown"


def _near_text(kind: str, name: str, distance_m: float, lang: str) -> str:
    if kind == "poi":
        what = tr("wt_near_poi", lang, name=cell(name))
    elif kind == "access":
        what = tr("wt_near_access", lang, name=cell(name))
    else:
        what = tr("wt_near_" + kind, lang)
    return tr("wt_near", lang, what=what, m=int(round(distance_m / 50.0) * 50))


def _clock(hours: float) -> str:
    total = int(round(hours * 60))
    return f"{(total // 60) % 24:02d}:{total % 60:02d}" + (" (+1)" if total >= 1440 else "")


class WaterPlugin(SectionPlugin):
    plugin_id = "water"
    section_id = "hazards"
    depends_on = ("weather", "water_near")
    title_key = "hz_water"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        near = shared.get("water_near")
        if near is None or near.get("error"):
            reason = (near or {}).get("error") or "no data"
            return Section("hazards", tr("wt_unavailable", lang, reason=reason), "no-data")
        bodies = sorted(near["bodies"], key=lambda b: -b.size_km)
        sea, spots = near.get("sea"), near.get("swim_spots") or []
        if not bodies and not sea:
            return Section("hazards", "", "derived", omit=True)
        window = (shared.get("weather") or {}).get("window_rows") or []
        last_hour = max((24 * r.get("day", 0) + r["hour"] for r in window), default=23)

        header = [tr(k, lang) for k in ("wt_col_water", "wt_col_near", "wt_col_temp", "wt_col_bathing")]
        rows = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        warnings, extra, coldest = [], [], None

        if sea:
            data = sea_temperature(ctx, sea["lat"], sea["lon"])
            temp_text = tr("wt_temp_none", lang) if False else "–"
            if data:
                key = "wt_temp_model" if data["kind"] == "model" else "wt_temp_climate"
                temp_text = tr(key, lang, temp=f"{data['temp']:.0f}")
                coldest = (data["temp"], tr("wt_sea", lang), "unknown")
            bathing = "allowed" if spots else "unknown"
            rows.append("| " + " | ".join([
                tr("wt_sea", lang), _near_text(sea["near_kind"], sea["near_name"], sea["distance_m"], lang),
                temp_text, tr("wt_bathing", lang)[bathing]]) + " |")
            extra += self._tides(ctx, data, last_hour, warnings)

        history = None
        detailed = bodies[:DETAILED]
        if detailed:
            lat, lon = ctx.centroid
            history = air_history(ctx, lat, lon)
        for body in detailed:
            temp = estimate_inland_temp(history, body.kind, body.size_km) if history else None
            near_spot = any(rect_distance_m(s_lat, s_lon, body.bbox) <= SWIM_SPOT_M for _, s_lat, s_lon in spots)
            bathing = bathing_status(body.tags, near_spot)
            temp_text = "–"
            if temp is not None:
                temp_text = tr("wt_temp_estimate", lang, temp=f"{temp:.0f}") + (
                    tr("wt_temp_ice", lang) if temp <= ICE_C else "")
                if bathing != "forbidden" and (coldest is None or temp < coldest[0]):
                    coldest = (temp, cell(body.name) or tr("wt_kind", lang)[body.kind], bathing)
            name = cell(body.name) or tr("wt_unnamed", lang)
            rows.append("| " + " | ".join([
                f"{name} ({tr('wt_kind', lang)[body.kind]})", _near_text(body.near_kind, body.near_name,
                                                                       body.distance_m, lang),
                temp_text, tr("wt_bathing", lang)[bathing]]) + " |")
        if coldest is not None and coldest[0] < COLD_WATER_C and coldest[2] != "forbidden":
            warnings.append(PlanWarning("caution", tr("wt_warn_cold", lang, name=coldest[1], temp=f"{coldest[0]:.0f}")))

        lines = ["\n".join(rows)]
        lines += extra
        rest = bodies[DETAILED:]
        if rest:
            listed = [f"- " + tr("wt_other_line", lang, name=cell(b.name) or tr("wt_unnamed", lang),
                                 kind=tr("wt_kind", lang)[b.kind], m=int(round(b.distance_m / 50.0) * 50),
                                 near=_near_text(b.near_kind, b.near_name, b.distance_m, lang).split(", ~")[0])
                      for b in rest[:LIST_MAX]]
            if len(rest) > LIST_MAX:
                listed.append("- " + tr("wt_more", lang, n=len(rest) - LIST_MAX))
            lines += [tr("wt_others", lang), "\n".join(listed)]

        fact = lookup(ctx.facts, ctx.date_iso, "water")
        if fact:
            lines += [tr("wt_web_title", lang), fact["markdown"], sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        else:
            lines.append("*" + tr("wt_pollution_none", lang) + "*")
        return Section("hazards", "\n\n".join(lines), "web-sourced" if fact else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings,
                       shared={"water_applies": True})

    @staticmethod
    def _tides(ctx, data, last_hour: int, warnings: list) -> list:
        lang = ctx.lang
        if not data or data["kind"] != "model":
            return ["*" + tr("wt_tides_unavailable", lang) + "*"]
        levels = list(data["day"]["level"])
        if last_hour >= 24:
            try:
                lat, lon = data["point"]
                levels += fetch_marine_day(ctx, lat, lon, ctx.date + datetime.timedelta(days=1))["level"]
            except (HttpError, KeyError, TypeError, ValueError):
                pass
        shown = [v for v in levels[:last_hour + 1] if v is not None]
        events = [e for e in tide_extrema(levels) if e[1] <= last_hour + 1]
        if not events or not shown:
            return ["*" + tr("wt_tides_unavailable", lang) + "*"]
        names = tr("wt_tide_names", lang)
        text = ", ".join(f"{names[kind]} {_clock(hours)} ({level:+.1f} m)" for kind, hours, level in events)
        tidal_range = max(shown) - min(shown)
        if tidal_range >= BIG_TIDE_M:
            warnings.append(PlanWarning("info", tr("wt_warn_tide", lang, range=f"{tidal_range:.1f}")))
        return [tr("wt_tides", lang, events=text)]
```
Cleanups required before running (keep the file honest): delete the dead expression `tr("wt_temp_none", lang) if False else "–"` and write `temp_text = "–"`; the f-string `f"- "` becomes `"- "`; `RADIUS_M` is imported for no use — drop it from the import.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_marine.py tests/test_water.py -q`
Expected: all PASS. If `test_the_list_of_the_rest_is_cut_at_fifteen` is off by one, the arithmetic is: 30 bodies − 2 detailed = 28 rest, 15 listed, "…and 13 more.".

- [ ] **Step 5: Commit**

```bash
git add scripts/day_plan tests/test_marine.py tests/test_water.py
git commit -m "water: sea temperature and tides, inland estimate, bathing from tags, web facts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Register, hints, docs, spec amendments

**Files:**
- Modify: `scripts/build_day_plan.py`
- Modify: `scripts/day_plan/i18n_conditions.py` (plugin names)
- Modify: `SKILL.md`, `../../README.md` (the repository README, `/mnt/data/pavel/work/osm-hike-route/README.md`)
- Modify: `docs/superpowers/specs/2026-10-01-hike-conditions-design.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `LandCoverPlugin`, `WaterNearPlugin`, `WaterPlugin`; `Section.shared["water_applies"]`.
- Produces: `default_plugins()` includes them; `optional_hazard_facts` can name `water`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_cli.py`:

```python
def test_the_new_plugins_are_registered_and_ordered():
    ids = [p.plugin_id for p in build_day_plan.default_plugins()]
    for new in ("land_cover", "water_near", "water"):
        assert new in ids
    assert ids.index("land_cover") < ids.index("bio_hazards") and ids.index("water_near") < ids.index("water")


def test_the_water_fact_is_suggested_when_water_is_near(make_route, fixed_now):
    from day_plan.base import Section
    ctx = build_context_for(make_route, fixed_now)
    result = type("R", (), {"sections": [Section("hazards", "x", "derived", shared={"water_applies": True})]})()
    assert "water" in build_day_plan.optional_hazard_facts(ctx, result)
    quiet = type("R", (), {"sections": [Section("hazards", "x", "derived")]})()
    assert "water" not in build_day_plan.optional_hazard_facts(ctx, quiet)


def test_a_whole_plan_builds_with_every_new_plugin(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    code = build_day_plan.main([str(route_dir), "2026-06-21", "--quiet"], http=lambda url: (
        {"elements": []} if "overpass" in url else weather_response()), http_text=_text, now=fixed_now)
    assert code == 0 and (route_dir / "day-plan-2026-06-21.md").exists()
    assert "Recommended start" in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
```
(`build_context_for` is a small local helper — add above the tests if the file has none:
```python
def build_context_for(make_route, fixed_now):
    from day_plan.context import build_context
    import datetime
    return build_context(make_route(), datetime.date(2026, 6, 21), http=lambda u: {}, now=fixed_now)
```
and reuse the file's existing `_text` helper for `http_text`.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement**

3a. `scripts/build_day_plan.py`: add imports

```python
from day_plan.plugins.land_cover import LandCoverPlugin
from day_plan.plugins.water import WaterPlugin
from day_plan.plugins.water_near import WaterNearPlugin
```
and in `default_plugins()`:
```python
    return [WeatherPlugin(), LightPlugin(), OsmFeaturesPlugin(), LandCoverPlugin(), WaterNearPlugin(),
            RadiationPlugin(), SnowHistoryPlugin(), TrailPassabilityPlugin(), TransitPlugin(), PoiHoursPlugin(),
            MountainPlugin(), FirePlugin(), BioHazardsPlugin(), WaterPlugin(), AirPlugin(), PeopleHazardsPlugin(),
            CellCoveragePlugin()]
```
in `optional_hazard_facts` after the `trail_conditions` block:
```python
    if result is not None and any(s.shared.get("water_applies") for s in result.sections):
        wanted.append("water")
```
and extend the optional hint text with `water: bathing-water quality, bans on swimming, currents, algae, jellyfish and other dangers of the water near the route`, and the main hint (the "no web-sourced facts recorded for transit" line) with `for transit also --first-arrival (the first public transport to the start point) next to --last-departure`.

3b. `i18n_conditions.py` — fill `CONDITION_PLUGIN_NAMES`:

```python
CONDITION_PLUGIN_NAMES = {
    "en": {"pl_land_cover": "Terrain (forest, grass)", "pl_water_near": "Water nearby (OSM)", "pl_water": "Water nearby"},
    "ru": {"pl_land_cover": "Местность (лес, трава)", "pl_water_near": "Водоёмы рядом (OSM)", "pl_water": "Водоёмы рядом"},
    "es": {"pl_land_cover": "Terreno (bosque, hierba)", "pl_water_near": "Agua cercana (OSM)", "pl_water": "Agua cercana"},
    "fr": {"pl_land_cover": "Terrain (forêt, herbe)", "pl_water_near": "Eau à proximité (OSM)", "pl_water": "Eau à proximité"},
    "de": {"pl_land_cover": "Gelände (Wald, Gras)", "pl_water_near": "Gewässer in der Nähe (OSM)", "pl_water": "Gewässer in der Nähe"},
    "pt": {"pl_land_cover": "Terreno (floresta, erva)", "pl_water_near": "Água por perto (OSM)", "pl_water": "Água por perto"},
    "it": {"pl_land_cover": "Terreno (bosco, erba)", "pl_water_near": "Acqua vicina (OSM)", "pl_water": "Acqua vicina"},
}
```

3c. `SKILL.md`: in "How to Use" step 3 replace the sentence about `--start` with: "Optional `--start HH:MM` if the person gave a start time. Without it the plan **recommends a start** — the earliest feasible one, not earlier than 07:00 — from sunrise, the opening of the start point, the first public transport that reaches it (`--first-arrival`), sunset, the last public transport back (`--last-departure`) and the closing of the end point, and uses it for the forecast window and every return check. An empty window is a danger warning." In the facts section: document `--first-arrival HH:MM` (transit; "record the time public transport brings one to the route's start point, together with the last departure back") and add the `water` plugin line: "`--plugin water`: pollution, bathing-water quality, bans and dangers of the water within 500 m (currents, algae, jellyfish, crocodiles, steep banks); `--warning` is allowed." Mention in the section list: the forecast covers the 24 hours of the date plus 4 hours after the finish; "Ticks" appear only where the route runs through forest or open ground; "Water nearby" (sea first, two largest bodies in detail). Update the plugin enumerations that list `--plugin <...>` to include `water`.

3d. `README.md` (repository root): one short paragraph under the day-plan description listing the three behaviours.

3e. Amend the spec file `docs/superpowers/specs/2026-10-01-hike-conditions-design.md`: (1) in "Weather" replace "one Open-Meteo request with `start_date` and `end_date`" by "a second cached per-day request"; (2) in "Start" replace the polar line by "Polar day: there are no sunrise or sunset limits; polar night: no recommendation (the light section already warns)"; (3) in "bio_hazards" replace the bullet "Regional facts … only if ticks were assessed" by "Regional facts (`facts.json`, `bio_hazards`) are shown as before: they also carry notes about animals"; (4) in the water plugin replace the table description and the pollution bullet by "pollution and hazards are one block under the table (the fact belongs to the plugin, not to a body)".

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: all PASS. Then a manual smoke on a real route folder with the network blocked is not needed (tests mock it); instead read the produced `day-plan-2026-06-21.md` of `test_a_whole_plan_builds_with_every_new_plugin` once with `pytest -q -k whole_plan -s` is optional.

- [ ] **Step 5: Commit**

```bash
git add scripts SKILL.md ../../README.md ../../docs/superpowers/specs/2026-10-01-hike-conditions-design.md tests
git commit -m "Register land_cover, water_near and water; hints and docs; spec amended to the implementation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Part 1: recommended start (Tasks 2–3, `first_arrival_local` Task 1, light lines Task 3), the 24 h + 4 h window with next-day, marks and after-finish warnings (Task 4). Part 2: `land_cover` (Task 5), gating, 5 % threshold, unknown-terrain note, info instead of caution (Task 6). Part 3: `water_near` with track + points centres (Task 7), sea first row, two detailed, list ≤ 15, sea and inland temperature, bathing, pollution fact, tides (Task 8); registration, hints, docs, fact `water` (Tasks 1 and 9). The deliberate deviations are listed in Global Constraints and amended in the spec in Task 9.

**Placeholder scan.** No "TBD"/"similar to"; every code step has code. Three explicit clean-up notes in Task 8 (dead expression, `f"- "`, unused import) and one in Task 7 (`hash` → `sha1`, drop `math`) are instructions to apply while typing the code, not open items.

**Type consistency.** `StartRecommendation` fields and limit names match between Task 2, 3 (`st_limits` keys: sunrise, start_open, first_arrival, sunset, last_departure, end_close). `window_rows` rows carry `day`/`after`, consumed by `trip_rows` (Task 4) and by `WaterPlugin` (`r.get("day", 0)`, Task 8). `land_cover` shared keys (`known`, `forest`, `open`, `total`, `error`) match Task 6. `WaterBody` fields/`Anchor` match between Tasks 7 and 8 (`bbox`, `size_km`, `tags`, `distance_m`, `near_kind`, `near_name`); `water_near.shared` keys (`bodies`, `sea`, `swim_spots`, `error`) match Task 8; `marine.sea_temperature` result keys (`temp`, `kind`, `point`, `day`) match its use in `WaterPlugin._tides`.

**Known risk for the executor.** Task 3 and Task 4 intentionally change behaviour that older tests asserted (the plan now always has a start; the table is the whole date). The steps say to run the whole suite, update only the assertions that encoded the old behaviour (with a comment), and fix the code for anything else.
