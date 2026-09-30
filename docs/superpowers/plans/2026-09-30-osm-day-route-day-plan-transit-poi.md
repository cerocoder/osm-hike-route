# Day Plan — Transit and Points-of-Interest Hours (plan 2 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the "Getting there" and "Points of interest" sections to the day plan — the kind of day (weekday / weekend / public holiday), access-point and point-of-interest opening hours evaluated for the date, the public-transport lines serving the access points, and web-sourced timetables, directions and opening days recorded with sources — after first closing the five hardening items carried over from plan 1.

**Architecture:** The plan-1 plugin system gets two more plugins (`transit`, `poi_hours`) built on four small units: a route-points context (`ctx.access_points`, `ctx.interest_points`), a validated `facts.json` schema with a `record_fact.py` writer, an `opening_hours` evaluator tested against 531 real OSM strings, and a calendar (Nominatim country + Nager.Date holidays, overridable by a web-sourced `calendar` fact). Overpass gives the lines through a stop (mirror list and one retry, degrading to no-data). Nothing in the show skill changes: it already embeds any plan Markdown.

**Tech Stack:** Python 3.10+ standard library only, pytest; live services Overpass, Nominatim, Nager.Date, Open-Meteo (all keyless).

**Spec:** `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md` (plugins *transit* and *poi_hours*, "Skill boundary", Privacy). Plan 1: `docs/superpowers/plans/2026-09-29-osm-day-route-day-plan-core.md` (merged).

**Scope note:** plan 3 will add the hazards group (ticks and biting insects, mountain, people, air, radiation, fire) and mobile coverage.

**Decisions taken from live checks while writing this plan** (each verified against the real service):
- OSM route relations almost never carry `interval` or `opening_hours` (Madrid buses: none; Moscow: some), so timetables must come from recorded web facts; OSM data is shown as-is with "not stated in OSM".
- Nager.Date returns 200 for RU/ES/DE/BY/UA/KZ/FR, but for Russia the free list is incomplete: it misses 8 January and the transferred days off (for example 9 March and 11 May 2026). A `calendar` fact with `day_type` overrides the list, and the day-plan SKILL.md tells Claude to always check Russian dates.
- Overpass answered 429 and 504 under load and one mirror returned HTML: mirrors plus one retry, and a failure degrades to a note.
- Real `opening_hours` (Madrid, Yekaterinburg, Moscow; 531 distinct strings) use a comma between rules (`Su-Th 12:30-24:00, Fr,Sa 12:30-00:30`), overnight ranges, single-digit hours, `19:30+`; 20 of them (point dates like `Jan 01`, comments, typos) are unsupported and must show as "not read".

## Global Constraints

- Every script is **standard-library only**; Python 3.10 or newer. No API key is required.
- Every claim carries a tier: `tag-backed` (OSM), `web-sourced` (facts.json), `derived`, `no-data`. A missing datum is `no-data`, never invented; unsupported `opening_hours` syntax is shown verbatim as "not read", never guessed.
- A `facts.json` entry with no `http(s)` source is **dropped** (never shown); `record_fact.py` refuses it and never overwrites a file it cannot parse.
- The plan is embedded in `map.html`, a file meant to be forwarded: places in the departure point **and in every fact** are city, station or stop level only — never a street address, phone number or anything personal.
- Nominatim: an identifying User-Agent, at most one request per route (the country is cached for good). Nager.Date lists cached 30 days, Overpass lines 7 days.
- Overpass: mirrors `overpass-api.de`, `overpass.kumi.systems`, `overpass.private.coffee`, one full retry after a pause; the client is copied into `day_plan`, not imported from the planning skill.
- Section order stays: Summary, Daylight, Weather by hour, Getting there, Points of interest (then, in plan 3, Hazards, Mobile coverage). Headings exist in `en`, `ru`, `es`, `fr`, `de`, `pt`, `it`; body text of the new sections in `en` and `ru` (English fallback).
- A last departure recorded as `HH:MM` before 04:00 belongs to the night after the date; the return check warns danger if the estimated return is later, caution if the margin is under 30 minutes.
- Tests never use the live network and never sleep for real.

## Review Focus

Inputs the spec implies that no headline task exercises; each has a test in the task that owns the code.

1. An `opening_hours` rule that crosses midnight (`Fr,Sa 12:30-00:30`): on Saturday morning the place is still open from Friday night. (Task 3)
2. Every Overpass mirror failing (429, 504, HTML) or the holiday list being unavailable: the plan still builds, says what is missing, and no test waits for real. (Tasks 4, 5, 6, 8)
3. A Russian date inside a transferred holiday: the free list says "not a holiday", so the plan carries the caveat and a `calendar` fact overrides it. (Task 4)
4. Pipes, newlines and long text in point names, hours strings and notes that would break a Markdown table. (Tasks 6, 7)
5. Garbage, unsourced or hand-edited `facts.json`, and text with markup in a fact: ignored or refused, never a crash, never shown unsourced. (Tasks 1, 2, 8)

---

## File Structure

In `skills/osm-day-route-day-plan/`:

| File | Change | Responsibility |
|---|---|---|
| `scripts/day_plan/summary.py`, `service.py`, `facts.py` | modified (Task 1) | Hardening: unknown severity, one-line failure reason, duplicate ids, unknown sections, malformed facts. |
| `scripts/day_plan/facts.py` | replaced (Task 2) | Facts schema: `normalize_entry`, sourced-only `lookup`. |
| `scripts/day_plan/context.py` | modified (Task 2) | `RoutePoint`, `ctx.access_points`, `ctx.interest_points`. |
| `scripts/day_plan/opening_hours.py` | new (Task 3) | `evaluate(spec, date, holiday, sun)` for the real-world subset of OSM `opening_hours`. |
| `scripts/day_plan/calendar_info.py`, `http.py`, `i18n.py` | new / modified (Task 4) | Day type: weekday, weekend, public holiday. |
| `scripts/day_plan/overpass.py`, `i18n.py`, `tests/conftest.py` | new / modified (Task 5) | Lines through an access point. |
| `scripts/day_plan/plugins/common.py`, `transit.py` | new (Task 6) | "Getting there". |
| `scripts/day_plan/plugins/poi_hours.py` | new (Task 7) | "Points of interest". |
| `scripts/record_fact.py`, `scripts/build_day_plan.py` | new / modified (Task 8) | Fact writer; the CLI registers both plugins and prints hints. |
| `SKILL.md`, `README.md` (repo root) | rewritten / modified (Task 9) | Documentation. |

All commands are run from the repository root unless a `cd` is shown. Work in a fresh worktree off the current `main`.

---

### Task 1: Close the five carried-over hardening items

These were found by the plan-1 reviews and must be fixed before plans 2 and 3 add plugins that make them reachable.

**Files:**
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/summary.py`, `skills/osm-day-route-day-plan/scripts/day_plan/facts.py`, `skills/osm-day-route-day-plan/scripts/day_plan/service.py`
- Test: `skills/osm-day-route-day-plan/tests/test_hardening.py`

**Interfaces:**
- Consumes: `Section`, `PlanWarning`, `SectionPlugin`, `SECTION_ORDER` (plan 1).
- Produces: `build_summary_section` tolerates an unknown severity (label = the capitalised severity, ranked last); `build_plan` survives a failing summary (recorded in `failures` as `("summary", reason)`); `run_plugins` raises `ValueError("duplicate plugin_id: <id>")` and `ValueError("plugin <id>: unknown section_id '<x>' ...")` before any plugin runs; failure reasons are one line of at most 200 characters; `assemble_markdown` keeps a section whose id is not in `SECTION_ORDER` under a `## <id>` heading; `load_facts`/`lookup` never raise on malformed content.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_hardening.py`:

```python
import datetime
import json

import pytest

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.facts import load_facts, lookup
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", raises=None, returns=None):
        self.plugin_id, self.section_id = plugin_id, section_id
        self._raises, self._returns = raises, returns

    def run(self, ctx, shared):
        if self._raises:
            raise self._raises
        return self._returns or Section(self.section_id, "body", "derived")


def _ctx(make_route, fixed_now, lang="en"):
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, http=lambda u: {}, now=fixed_now)


# 1. unknown severity must not crash the summary
def test_summary_tolerates_an_unknown_severity_and_ranks_it_last():
    warnings = [PlanWarning("mystery", "odd"), PlanWarning("danger", "D"), PlanWarning("info", "I")]
    summary = build_summary_section([Section("hazards", "x", "derived", warnings=warnings)], "en")
    lines = summary.markdown.splitlines()
    assert lines[0] == "- **Danger:** D"
    assert lines[1] == "- **Note:** I"
    assert lines[2] == "- **Mystery:** odd"


def test_build_plan_survives_a_summary_failure(make_route, fixed_now, monkeypatch):
    import day_plan.service as service

    def boom(sections, lang):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(service, "build_summary_section", boom)
    result = build_plan(_ctx(make_route, fixed_now), [Stub("a")])
    assert "## Summary" in result.markdown
    assert ("summary", "RuntimeError: summary exploded") in result.failures


# 2. plugin_failed reason is one short line
def test_failure_reason_is_collapsed_to_one_line_and_truncated(make_route, fixed_now):
    nasty = RuntimeError("HTTP 500\n<html>\n" + "x" * 500 + "\n</html>")
    sections, _, failures = run_plugins(_ctx(make_route, fixed_now), [Stub("bad", raises=nasty)])
    text = sections[0].markdown
    assert "\n" not in text
    assert len(text) < 320
    assert text.endswith("…).") or "…" in text
    assert failures[0][0] == "bad"


# 3. duplicate plugin ids are rejected before anything runs
def test_duplicate_plugin_id_is_rejected_before_any_plugin_runs(make_route, fixed_now):
    ran = []

    class Recording(Stub):
        def run(self, ctx, shared):
            ran.append(self.plugin_id)
            return super().run(ctx, shared)

    with pytest.raises(ValueError, match="duplicate plugin_id: a"):
        run_plugins(_ctx(make_route, fixed_now), [Recording("a"), Recording("b"), Recording("a")])
    assert ran == []


# 4. a section id outside SECTION_ORDER must not vanish
def test_plugin_with_unknown_section_id_is_rejected_at_registration(make_route, fixed_now):
    with pytest.raises(ValueError, match="unknown section_id 'nonsense'"):
        run_plugins(_ctx(make_route, fixed_now), [Stub("odd", section_id="nonsense")])


def test_section_returned_with_an_unknown_id_is_kept_under_a_fallback_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    stray = Section("stray", "kept text", "derived")
    text = assemble_markdown(ctx, [stray], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## stray\n\nkept text" in text


# 5. malformed facts.json
@pytest.mark.parametrize("payload", ['{"all": []}', '{"all": ["x"]}', '{"all": "text"}',
                                     '{"all": {"transit": "text"}}', '{"all": {"transit": []}}',
                                     '{"2026-06-21": null}', '[]', '"just a string"'])
def test_lookup_tolerates_malformed_but_valid_json(tmp_path, payload):
    (tmp_path / "facts.json").write_text(payload, encoding="utf-8")
    assert lookup(load_facts(tmp_path), "2026-06-21", "transit") is None


def test_load_facts_tolerates_non_utf8_and_directory(tmp_path):
    (tmp_path / "facts.json").write_bytes(b"\xff\xfe\x00 not utf8")
    assert load_facts(tmp_path) == {}
    other = tmp_path / "d"
    other.mkdir()
    (other / "facts.json").mkdir()
    assert load_facts(other) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_hardening.py -q`
Expected: FAIL (7 failed: the unknown severity raises `KeyError`, duplicate ids and unknown sections are not rejected, the failure reason is not shortened, a non-UTF-8 `facts.json` raises `UnicodeDecodeError`).

- [ ] **Step 3: Apply the fixes**

In `skills/osm-day-route-day-plan/scripts/day_plan/summary.py`:

**Replace:**

```python
    lines = [f"- **{tr('sev_' + w.severity, lang)}:** {w.text}" for w in warnings[:MAX_ITEMS]]
```

**With:**

```python
    lines = [f"- **{_severity_label(w.severity, lang)}:** {w.text}" for w in warnings[:MAX_ITEMS]]
```

**Replace:**

```python
def build_summary_section(
```

**With:**

```python
def _severity_label(severity: str, lang: str) -> str:
    """Localized label; an unknown severity falls back to its own name so one
    bad plugin cannot take the whole summary down."""
    try:
        return tr("sev_" + severity, lang)
    except KeyError:
        return str(severity).capitalize()


def build_summary_section(
```

In `skills/osm-day-route-day-plan/scripts/day_plan/facts.py`:

**Replace:**

```python
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
```

**With:**

```python
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}
```

**Replace:**

```python
    for scope in (date_iso, "all"):
        entry = (facts.get(scope) or {}).get(plugin_id)
        if isinstance(entry, dict) and entry.get("markdown"):
            return entry
    return None
```

**With:**

```python
    for scope in (date_iso, "all"):
        plugins = facts.get(scope)
        if not isinstance(plugins, dict):
            continue
        entry = plugins.get(plugin_id)
        if isinstance(entry, dict) and entry.get("markdown"):
            return entry
    return None
```

In `skills/osm-day-route-day-plan/scripts/day_plan/service.py`:

**Replace:**

```python
def run_plugins(ctx, plugins: list):
    """Returns (sections_in_registration_order, shared, failures)."""
    shared, failures, by_id = {}, [], {}
    for plugin in _ordered(plugins):
```

**With:**

```python
def _one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace and truncate, so a traceback or an HTTP error body
    cannot break the Markdown layout."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _validate_registration(plugins: list) -> None:
    seen = set()
    for plugin in plugins:
        if plugin.plugin_id in seen:
            raise ValueError(f"duplicate plugin_id: {plugin.plugin_id}")
        seen.add(plugin.plugin_id)
        if plugin.section_id not in SECTION_ORDER:
            raise ValueError(f"plugin {plugin.plugin_id}: unknown section_id {plugin.section_id!r} "
                             f"(known: {', '.join(SECTION_ORDER)})")


def run_plugins(ctx, plugins: list):
    """Returns (sections_in_registration_order, shared, failures)."""
    _validate_registration(plugins)
    shared, failures, by_id = {}, [], {}
    for plugin in _ordered(plugins):
```

**Replace:**

```python
            reason = f"{type(e).__name__}: {e}"
            failures.append((plugin.plugin_id, reason))
```

**With:**

```python
            reason = _one_line(f"{type(e).__name__}: {e}")
            failures.append((plugin.plugin_id, reason))
```

**Replace:**

```python
        parts.append(f"## {tr('h_' + section_id, lang)}\n\n" + "\n\n".join(body))
    return "\n\n".join(parts) + "\n"
```

**With:**

```python
        parts.append(f"## {tr('h_' + section_id, lang)}\n\n" + "\n\n".join(body))
    for s in sections:  # never drop a section whose id is not in SECTION_ORDER
        if s.section_id not in SECTION_ORDER:
            parts.append(f"## {s.section_id}\n\n{s.markdown}")
    return "\n\n".join(parts) + "\n"
```

**Replace:**

```python
    summary = build_summary_section(sections, ctx.lang)
    markdown
```

**With:**

```python
    try:
        summary = build_summary_section(sections, ctx.lang)
    except Exception as e:  # noqa: BLE001 — the summary is outside run_plugins' isolation
        failures.append(("summary", _one_line(f"{type(e).__name__}: {e}")))
        summary = Section("summary", "- " + tr("summary_none", ctx.lang), "derived")
    markdown
```


- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (102 passed: the 87 existing plus 15 new).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Harden day-plan: unknown severity, failure reasons, duplicate ids, unknown sections, malformed facts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Facts schema and route points in the context

**Files:**
- Replace: `skills/osm-day-route-day-plan/scripts/day_plan/facts.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/context.py`, `skills/osm-day-route-day-plan/tests/test_foundation.py`
- Test: `skills/osm-day-route-day-plan/tests/test_facts_and_points.py`

**Interfaces:**
- Consumes: `SEVERITIES` (plan 1), `lookup`/`load_facts` (Task 1).
- Produces: `normalize_entry(entry) -> dict | None` (validated copy: `markdown`, `sources` (http/https only), optional `last_departure_local`, `first_departure_local` (`H:MM`/`HH:MM`), `warnings` (`[{severity, text}]`), `day_type` (`holiday|weekend|workday`); `None` when there is no valid source or no text/day type); `lookup(facts, date_iso, plugin_id)` returns only normalised entries (a dated entry that is invalid falls back to the `all` entry); `DAY_TYPES`; `RoutePoint(name, type, lat, lon, role, opening_hours, access_notes, note, osm_id, ele)`; `ctx.access_points` (Point features with `type == "access"`) and `ctx.interest_points` (every other Point).

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_facts_and_points.py`:

```python
import datetime
import json

import pytest

from day_plan.context import RoutePoint, build_context
from day_plan.facts import load_facts, lookup, normalize_entry

URL = "https://example.org/timetable"


def _entry(**extra):
    return {"markdown": "Bus 41 every 20 min.", "sources": [URL], **extra}


# ---- facts schema -------------------------------------------------------------------------------

def test_entry_without_sources_is_dropped():
    assert normalize_entry({"markdown": "text"}) is None
    assert normalize_entry({"markdown": "text", "sources": []}) is None
    assert normalize_entry({"markdown": "text", "sources": ["not a url", 5, None]}) is None


def test_only_http_sources_are_kept():
    entry = normalize_entry(_entry(sources=[URL, "ftp://x", "javascript:alert(1)", "https://b.org"]))
    assert entry["sources"] == [URL, "https://b.org"]


def test_markdown_is_required_unless_a_day_type_is_given():
    assert normalize_entry({"sources": [URL]}) is None
    assert normalize_entry({"sources": [URL], "markdown": "   "}) is None
    assert normalize_entry({"sources": [URL], "day_type": "holiday"})["day_type"] == "holiday"


def test_structured_fields_are_validated():
    entry = normalize_entry(_entry(last_departure_local="23:40", first_departure_local="5:10"))
    assert entry["last_departure_local"] == "23:40"
    assert entry["first_departure_local"] == "5:10"
    bad = normalize_entry(_entry(last_departure_local="late", first_departure_local="25:99", day_type="funday"))
    assert "last_departure_local" not in bad and "first_departure_local" not in bad and "day_type" not in bad


def test_warnings_keep_only_valid_items():
    entry = normalize_entry(_entry(warnings=[
        {"severity": "danger", "text": "Last bus 21:10"},
        {"severity": "mystery", "text": "odd"},
        {"severity": "info"},
        "not a dict",
        {"severity": "caution", "text": ""},
    ]))
    assert entry["warnings"] == [{"severity": "danger", "text": "Last bus 21:10"}]


def test_non_dict_entry_is_dropped():
    assert normalize_entry("text") is None
    assert normalize_entry(None) is None
    assert normalize_entry([1]) is None


def test_lookup_returns_normalized_entries_and_prefers_the_date(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({
        "all": {"transit": _entry(markdown="generic")},
        "2026-06-21": {"transit": _entry(markdown="specific")},
        "2026-06-22": {"transit": {"markdown": "no sources here"}},
    }), encoding="utf-8")
    facts = load_facts(tmp_path)
    assert lookup(facts, "2026-06-21", "transit")["markdown"] == "specific"
    assert lookup(facts, "2026-06-23", "transit")["markdown"] == "generic"
    # a dated entry without sources is dropped, and the "all" entry is used instead
    assert lookup(facts, "2026-06-22", "transit")["markdown"] == "generic"
    assert lookup(facts, "2026-06-21", "poi_hours") is None


# ---- route points in the context ----------------------------------------------------------------

def _write_route(tmp_path, features):
    route_dir = tmp_path / "r"
    route_dir.mkdir()
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return route_dir


LINE = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-3.75, 40.42, 600], [-3.74, 40.43, 640]]},
        "properties": {"name": "R", "mode": "walk", "duration_estimate_hours": 3}}


def _point(name, type_, lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "type": type_, **props}}


def test_points_are_split_into_access_and_interest(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, [
        LINE,
        _point("Lago", "access", -3.7275, 40.4247, role="start", opening_hours="05:00-01:00", access_notes="Metro line 10"),
        _point("Fountain", "fountain", -3.74, 40.43, note="Drinking water"),
        _point("Museum", "sight", -3.741, 40.431, opening_hours="Tu-Su 10:00-18:00", osm_id="node/1"),
    ])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert [p.name for p in ctx.access_points] == ["Lago"]
    assert [p.name for p in ctx.interest_points] == ["Fountain", "Museum"]
    lago = ctx.access_points[0]
    assert isinstance(lago, RoutePoint)
    assert (lago.lat, lago.lon, lago.role) == (40.4247, -3.7275, "start")
    assert lago.opening_hours == "05:00-01:00" and lago.access_notes == "Metro line 10"
    museum = ctx.interest_points[1]
    assert museum.osm_id == "node/1" and museum.opening_hours == "Tu-Su 10:00-18:00"
    assert ctx.interest_points[0].note == "Drinking water"


def test_points_default_to_empty_lists_and_tolerate_odd_features(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, [
        LINE,
        {"type": "Feature", "geometry": None, "properties": {"name": "no geometry"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}, "properties": None},
    ])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.access_points == []
    assert [p.name for p in ctx.interest_points] == ["Waypoint"]   # unnamed point, only the well-formed one kept


def test_route_with_only_a_line_has_no_points(tmp_path, fixed_now):
    ctx = build_context(_write_route(tmp_path, [LINE]), datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.access_points == [] and ctx.interest_points == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_facts_and_points.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'RoutePoint' from 'day_plan.context'`.

- [ ] **Step 3: Write the implementation**

Replace the whole file `skills/osm-day-route-day-plan/scripts/day_plan/facts.py` with:

```python
"""facts.json: web-sourced material Claude gathered by searching and recorded
for the plan (spec, "Skill boundary"). Shape:

    {"<YYYY-MM-DD>" or "all": {"<plugin_id>": {
        "markdown": "...",                         # required unless day_type is given
        "sources": ["https://..."],                # required: an entry without a source is dropped
        "last_departure_local": "HH:MM",           # optional, transit: compared with the estimated return
        "first_departure_local": "HH:MM",          # optional, transit
        "warnings": [{"severity": "danger|caution|info", "text": "..."}],   # optional, reach the Summary
        "day_type": "holiday|weekend|workday"      # optional, plugin id "calendar": overrides the holiday source
    }}}

A date-specific entry wins over an "all" entry. Everything read back is
validated by normalize_entry: a malformed or source-less entry is ignored
(never shown), the rest of the file keeps working. The text ends up in
day-plan-<date>.md, a file meant to be forwarded: keep places at city,
station or stop level, never a street address or anything personal."""
import json
import re
from pathlib import Path

from .base import SEVERITIES

DAY_TYPES = ("holiday", "weekend", "workday")
_TIME = re.compile(r"^\d{1,2}:[0-5]\d$")


def load_facts(route_dir) -> dict:
    path = Path(route_dir) / "facts.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_time(value) -> bool:
    return isinstance(value, str) and bool(_TIME.match(value)) and int(value.split(":")[0]) <= 29


def normalize_entry(entry) -> dict | None:
    """Validated copy of a facts entry, or None when it must not be used."""
    if not isinstance(entry, dict):
        return None
    sources = [s.strip() for s in (entry.get("sources") or []) if isinstance(s, str)
               and s.strip().lower().startswith(("http://", "https://"))] if isinstance(entry.get("sources"), list) else []
    if not sources:
        return None
    markdown = entry.get("markdown")
    markdown = markdown.strip() if isinstance(markdown, str) else ""
    day_type = entry.get("day_type") if entry.get("day_type") in DAY_TYPES else None
    if not markdown and not day_type:
        return None
    clean = {"markdown": markdown, "sources": sources}
    if day_type:
        clean["day_type"] = day_type
    for key in ("last_departure_local", "first_departure_local"):
        if _valid_time(entry.get(key)):
            clean[key] = entry[key]
    warnings = []
    for item in entry.get("warnings") if isinstance(entry.get("warnings"), list) else []:
        if (isinstance(item, dict) and item.get("severity") in SEVERITIES
                and isinstance(item.get("text"), str) and item["text"].strip()):
            warnings.append({"severity": item["severity"], "text": item["text"].strip()})
    if warnings:
        clean["warnings"] = warnings
    return clean


def lookup(facts: dict, date_iso: str, plugin_id: str) -> dict | None:
    """The usable entry for this date and plugin: the dated one if it is valid,
    else the "all" one, else None."""
    for scope in (date_iso, "all"):
        plugins = facts.get(scope)
        if not isinstance(plugins, dict):
            continue
        entry = normalize_entry(plugins.get(plugin_id))
        if entry is not None:
            return entry
    return None
```

In `skills/osm-day-route-day-plan/scripts/day_plan/context.py`:

**Replace:**

```python
@dataclass
class PlanContext:
```

**With:**

```python
@dataclass
class RoutePoint:
    """A Point feature of route.geojson (access point or point of interest)."""
    name: str
    type: str
    lat: float
    lon: float
    role: str | None = None            # "start" | "end" for access points
    opening_hours: str | None = None   # raw OSM tag
    access_notes: str | None = None
    note: str | None = None
    osm_id: str | None = None
    ele: float | None = None


@dataclass
class PlanContext:
```

**Replace:**

```python
    now: datetime.datetime  # timezone-aware UTC
    today: datetime.date = field(init=False)

```

**With:**

```python
    now: datetime.datetime  # timezone-aware UTC
    today: datetime.date = field(init=False)
    access_points: list = field(default_factory=list)    # [RoutePoint] with type == "access"
    interest_points: list = field(default_factory=list)  # [RoutePoint], every other Point feature

```

**Replace:**

```python
def build_context(
```

**With:**

```python
def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _points(geojson: dict) -> tuple[list, list]:
    access, interest = [], []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        point = RoutePoint(
            name=_text(props.get("name")) or "Waypoint", type=_text(props.get("type")) or "waypoint",
            lat=coords[1], lon=coords[0], role=_text(props.get("role")),
            opening_hours=_text(props.get("opening_hours")), access_notes=_text(props.get("access_notes")),
            note=_text(props.get("note")), osm_id=_text(props.get("osm_id")),
            ele=coords[2] if len(coords) > 2 else None,
        )
        (access if point.type == "access" else interest).append(point)
    return access, interest


def build_context(
```

**Replace:**

```python
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return PlanContext(
```

**With:**

```python
    now = now or datetime.datetime.now(datetime.timezone.utc)
    access_points, interest_points = _points(geojson)
    return PlanContext(
```

**Replace:**

```python
        now=now,
    )
```

**With:**

```python
        now=now,
        access_points=access_points, interest_points=interest_points,
    )
```

In `skills/osm-day-route-day-plan/tests/test_foundation.py`:

**Replace:**

```python
        "all": {"transit": {"markdown": "generic"}},
        "2026-06-21": {"transit": {"markdown": "specific"}},
```

**With:**

```python
        "all": {"transit": {"markdown": "generic", "sources": ["https://example.org/a"]}},
        "2026-06-21": {"transit": {"markdown": "specific", "sources": ["https://example.org/b"]}},
```


- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (112 passed). The plan-1 test `test_facts_lookup_prefers_date_over_all` now needs `sources` in its fixtures (edited above) because an entry without a source is dropped by design.

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add facts schema (sourced-only) and route points to the day-plan context

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `opening_hours` evaluator

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/opening_hours.py`, `skills/osm-day-route-day-plan/tests/fixtures/opening_hours_real.json`
- Test: `skills/osm-day-route-day-plan/tests/test_opening_hours.py`

**Interfaces:**
- Produces: `evaluate(spec, day, holiday=None, sun=None) -> OpeningResult(status, intervals, note, uncertain)` where `status` is `open_hours | open_all_day | closed | unknown`, `intervals` are `[(start_min, end_min)]` for the date (an overnight end exceeds 1440; the previous night's spill appears as `(0, end)`), `uncertain` marks a `PH` rule evaluated with `holiday=None`; `format_intervals(intervals) -> str` (`09:00–18:00, 19:00–02:00 (+1)`, a midnight close is `24:00`); `open_at(result, minute)`; `latest_close(result)`. `sun` is `{"sunrise": minute, "sunset": minute}`.

- [ ] **Step 1: Write the fixture and the failing tests**

The fixture holds all 531 distinct `opening_hours` values fetched from Overpass for 2.5–3 km around central Madrid, Yekaterinburg and Moscow.

`skills/osm-day-route-day-plan/tests/fixtures/opening_hours_real.json`:

```json
[
"-24:00",
"06:00-21:40",
"07:00-00:00",
"07:00-20:00",
"07:30-00:00",
"07:30-02:00",
"08:00-20:00",
"08:00-21:00",
"08:00-22:00",
"08:00-23:00",
"08:30-21:30",
"09:00-20:00",
"09:00-21:00",
"09:00-22:00",
"09:00-23:00",
"10:00-00:00",
"10:00-02:00",
"10:00-20:00",
"10:00-21:00",
"10:00-22:00",
"12:00-00:00",
"12:00-02:00",
"12:00-21:00",
"12:00-24:00",
"14:00-17:00,20:00-24:00",
"16:00-20:00",
"19:00-02:30",
"24/7",
"24/7 off",
"8:00-20:00",
"8:00-22:00",
"8:00-2:30",
"9:00-20:00",
"Apr-Sep Mo-Su,PH 10:00-20:00; Oct-Mar Mo-Su,PH 10:00-18:00",
"Fr 09:00-17:00;Mo-Th 09:00-18:00",
"Fr 11:45-24:00; Mo-Th 11:45-22:00; Sa 11:00-24:00; Su 11:00-22:00",
"Fr 16:00-20:00; Sa 10:00-14:00,16:00-20:00; Su 10:00-14:00",
"Fr,Sa 12:00-06:00; Mo-Su 12:00-24:00",
"Fr-Sa 09:00-23:00; Mo-Th,Su 09:00-22:00",
"Fr-Sa 10:00-23:00; Mo-Th,Su 10:00-22:00",
"Fr-Sa 11:00-01:00; Mo-Th,Su 11:00-00:00",
"Fr-Sa 11:45-24:00; Mo-Th,Su 11:45-22:00",
"Fr-Sa 12:00-02:00; Mo-Th,Su 12:00-24:00",
"Fr-Sa 12:00-05:00; Mo-Th,Su 12:00-24:00",
"Fr-Sa 12:00-24:00;Mo-Th,Su 12:00-23:00",
"L-M19:00-24:00  J 13:30-17:00  20:00-23:30 V-D 13:30-01:00",
"Mo 08:00-16:00; Tu-Fr 08:00-20:00; PH,Sa,Su 09:00-20:00",
"Mo 08:00-23:00; Tu-Fr 08:00-24:00; Sa 10:00-24:00; Su 10:00-23:00",
"Mo 09:00-18:00; Tu-Fr 09:00-21:00; Sa-Su 10:00-21:00",
"Mo 09:00-20:00, Sa 10:00-20:00, Su 10:00-18:00",
"Mo 09:00-24:00; Tu-Fr 00:00-01:00,09:00-24:00; Sa 00:00-01:00,11:00-24:00; Su 00:00-02:00",
"Mo 10:00-20:00; Th 09:00-19:00; Fr,Sa 09:00-00:00; Su 10:00-24:00",
"Mo 11:00-05:00; Tu-Su 07:00-05:00",
"Mo 13:00-17:30, Tu-Su 13:00-17:30,20:30-24:00",
"Mo 13:00-23:30; Tu, We 13:00-23:00; Th-Sa 13:00-23:30; Su 13:00-17:30",
"Mo 17:00-20:00; Tu-Fr 11:00-14:00,17:00-20:00; Sa 11:00-15:00,16:00-20:00; Jan,Feb Su,PH 12:00-15:00,16:00-18:00",
"Mo off; Tu-Sa 09:30-20:00; Su 09:30-15:00; PH 09:30-15:00; Jan 01,06,May 01,Dec 24,25,31 off",
"Mo off; Tu-Sa 09:30-20:00; Su 10:00-15:00; Jan 01,06,May 01,Dec 24,25,31 off",
"Mo off; Tu-Su 12:00-17:00, 19:00-23:30",
"Mo, Fr 11:00-20:00; Tu-Th 10:00-18:00; Sa-Su 11:00-18:00",
"Mo, We-Fr 11:00-14:00, 17:00-21:00; Tu 17:00-21:00; Sa 11:00-21:00; Su 12:00-20:00",
"Mo,Su 12:00-24:00; Tu-Th 00:00-01:00,12:00-24:00; Fr,Sa 00:00-03:00,12:00-24:00",
"Mo,We,Fr 08:30-14:00; Tu,Th 16:30-18:30",
"Mo,We-Su 13:00-15:30,19:30-22:30",
"Mo-Fr 00:00-02:00,12:00-24:00; Sa,Su 00:00-03:00,14:00-24:00",
"Mo-Fr 06:00-23:00; Sa 12:00-23:00; Su 12:00-21:00",
"Mo-Fr 07:00-19:00; Sa-Su 08:00-17:00",
"Mo-Fr 07:00-21:30; Sa,Su 09:00-21:30",
"Mo-Fr 07:00-22:00;Sa 08:00-22:00;Su 08:00-21:00",
"Mo-Fr 07:00-22:00;Sa-Su 08:00-22:00",
"Mo-Fr 07:00-23:00;Sa-Su 08:00-23:00",
"Mo-Fr 07:30-18:00",
"Mo-Fr 07:30-18:30; Sa,Su 09:00-15:00",
"Mo-Fr 07:30-20:00",
"Mo-Fr 07:30-20:00; Sa-Su 09:00-15:00",
"Mo-Fr 07:30-21:00; Sa 08:30-21:00; Su 09:00-21:00",
"Mo-Fr 07:30-22:00,08:00-22:00",
"Mo-Fr 08:00-02:00; Sa,Su 09:30-02:00",
"Mo-Fr 08:00-13:00,14:00-20:00; Sa 09:00-13:00,14:00-18:00; Su off",
"Mo-Fr 08:00-13:30,15:30-19:00; Sa 08:00-13:00",
"Mo-Fr 08:00-17:00",
"Mo-Fr 08:00-19:00; Sa 10:00-18:00",
"Mo-Fr 08:00-19:00; Sa,Su 09:00-12:00",
"Mo-Fr 08:00-20:00",
"Mo-Fr 08:00-20:00; Sa 09:00-18:00",
"Mo-Fr 08:00-20:00; Sa 09:00-18:00; Su 09:00-14:00",
"Mo-Fr 08:00-20:00; Sa 09:00-18:00; Su off",
"Mo-Fr 08:00-20:00; Sa 10:00-18:00",
"Mo-Fr 08:00-20:00; Sa,Su off",
"Mo-Fr 08:00-20:00; Sa-Su 09:00-18:00",
"Mo-Fr 08:00-21:00; Sa 08:00-20:00; Su 09:00-18:00",
"Mo-Fr 08:00-21:00; Sa 09:00-18:00; Su 09:00-18:00",
"Mo-Fr 08:00-21:00; Sa 09:00-21:00; Su 09:00-20:00",
"Mo-Fr 08:00-21:00; Sa 09:00-21:00; Su 10:00-20:00",
"Mo-Fr 08:00-21:00; Sa,Su 09:00-21:00",
"Mo-Fr 08:00-21:00; Sa,Su 10:00-18:00",
"Mo-Fr 08:00-21:00; Sa,Su 10:00-21:00",
"Mo-Fr 08:00-21:00; Sa-Su 08:00-20:00",
"Mo-Fr 08:00-21:00; Sa-Su 09:00-21:00",
"Mo-Fr 08:00-22:00, Sa-Su 09:00-22:00",
"Mo-Fr 08:00-22:00,Sa 09:00-22:00,Su,PH 10:00-16:00",
"Mo-Fr 08:00-22:00; Sa,Su 09:00-21:00",
"Mo-Fr 08:00-22:00; Sa,Su 09:00-22:00",
"Mo-Fr 08:00-22:00; Sa-Su 09:00-21:00",
"Mo-Fr 08:00-22:00; Sa-Su 09:00-22:00",
"Mo-Fr 08:00-22:00; Sa-Su 10:00-21:00",
"Mo-Fr 08:00-23:00; Sa,Su 09:00-23:00",
"Mo-Fr 08:00-23:00; Sa,Su 10:00-23:00",
"Mo-Fr 08:00-23:00; Sa-Su 08:00-22:00",
"Mo-Fr 08:00-23:00; Sa-Su 10:00-23:00",
"Mo-Fr 08:00-24:00; Sa,Su 10:00-24:00",
"Mo-Fr 08:00-24:00; Sa-Su 10:00-24:00",
"Mo-Fr 08:15-14:00",
"Mo-Fr 08:30-02:00; Sa-Su 11:45-02:30",
"Mo-Fr 08:30-12:30,13:00-16:00",
"Mo-Fr 08:30-14:00; PH off",
"Mo-Fr 08:30-14:00; Sa 09:00-12:00; PH off",
"Mo-Fr 08:30-14:15",
"Mo-Fr 08:30-16:00",
"Mo-Fr 08:30-17:00",
"Mo-Fr 08:30-19:30; Sa 09:00-17:00",
"Mo-Fr 08:30-20:30; Sa 09:30-13:00; Aug: Mo-Fr 08:30-14:30; Aug: Sa 09:30-13:00; Dec 24,25,Jan 01,06 off",
"Mo-Fr 08:30-20:30; Sa 09:30-13:00; Aug: Mo-Fr 08:30-14:30; Aug: Sa 09:30-13:00; PH off; Dec 24,25,Jan 01,06 off",
"Mo-Fr 08:30-20:30; Sa 09:30-13:00; Aug: Mo-Fr 08:30-14:30; Aug: Sa 09:30-13:00; Su,PH off; Dec 24,25,Jan 01,06 off",
"Mo-Fr 08:30-21:00; Sa 09:00-18:00; Su 10:00-17:00",
"Mo-Fr 08:30-22:00; Sa,Su 09:30-21:30",
"Mo-Fr 08:30-22:00; Sa,Su 10:00-20:00",
"Mo-Fr 09:00-06:00; Sa,Su 11:00-06:00",
"Mo-Fr 09:00-12:00,13:30-18:30; Sa 09:00-17:00; PH closed",
"Mo-Fr 09:00-14:00",
"Mo-Fr 09:00-14:00, 16:00-20:00",
"Mo-Fr 09:00-16:00",
"Mo-Fr 09:00-18:00",
"Mo-Fr 09:00-18:00; Sa 10:00-17:00",
"Mo-Fr 09:00-19:00",
"Mo-Fr 09:00-19:00, Sa,Su 10:00-18:00",
"Mo-Fr 09:00-19:00; Sa 09:30-17:00",
"Mo-Fr 09:00-19:00; Sa 10:00-17:00",
"Mo-Fr 09:00-19:00; Sa 10:00-17:00; Su 09:30-17:00",
"Mo-Fr 09:00-19:00;Sa 10:00-17:00",
"Mo-Fr 09:00-20:00",
"Mo-Fr 09:00-20:00; Sa 09:00-19:00",
"Mo-Fr 09:00-20:00; Sa 09:00-19:00; Su 10:00-19:00",
"Mo-Fr 09:00-20:00; Sa 10:00-17:00",
"Mo-Fr 09:00-20:00; Sa 10:00-18:00; Su off",
"Mo-Fr 09:00-20:00; Sa 10:00-19:00; Su 10:00-18:00",
"Mo-Fr 09:00-20:00; Sa 10:00-20:00; Su 10:00-19:00",
"Mo-Fr 09:00-20:00; Sa-Su 10:00-18:00",
"Mo-Fr 09:00-20:00; Sa-Su 10:00-20:00",
"Mo-Fr 09:00-20:00; Sa-Su off",
"Mo-Fr 09:00-20:00;Sa 10:00-16:00",
"Mo-Fr 09:00-20:00;Sa 10:00-17:00",
"Mo-Fr 09:00-20:00;Sa-Su 10:00-17:00",
"Mo-Fr 09:00-21:00; Sa 10:00-19:00; Su off",
"Mo-Fr 09:00-21:00; Sa 10:00-20:00; Su 10:00-19:00",
"Mo-Fr 09:00-21:00; Sa 11:00-18:00",
"Mo-Fr 09:00-21:00; Sa,Su 10:00-21:00",
"Mo-Fr 09:00-21:00; Sa,Su,PH 09:30-15:00",
"Mo-Fr 09:00-21:00; Sa-Su 10:00-19:00",
"Mo-Fr 09:00-21:00; Sa-Su 10:00-20:00",
"Mo-Fr 09:00-21:00; Sa-Su 10:00-21:00",
"Mo-Fr 09:00-21:00; Su[1] 10:00-15:00",
"Mo-Fr 09:00-21:30; Sa-Su 10:00-14:30",
"Mo-Fr 09:00-22:00, Sa-Su 09:00-21:00",
"Mo-Fr 09:00-22:00; Sa-Su 10:00-22:00",
"Mo-Fr 09:00-24:00; Sa,Su 00:00-02:00,09:00-24:00",
"Mo-Fr 09:00-24:30; Sa-Su 10:00-24:30",
"Mo-Fr 09:30-12:00,13:30-15:30",
"Mo-Fr 09:30-13:45,17:00-20:00 \"al 15 de junio 2024\"; Sa 10:00-13:45 \"al 15 de junio 2024\"; PH off",
"Mo-Fr 09:30-13:45,17:00-20:00; Sa 10:00-13:45",
"Mo-Fr 09:30-14:00, 16:30-19:30; Sa 10:00-14:00",
"Mo-Fr 09:30-14:00, 17:00-20:30; Sa 10:00-14:00",
"Mo-Fr 09:30-14:00,16:30-20:00; Sa 10:00-14:00",
"Mo-Fr 09:30-14:00,16:30-20:30; Sa 09:00-14:00",
"Mo-Fr 09:30-17:00; Sa,Su off",
"Mo-Fr 09:30-17:30",
"Mo-Fr 09:30-17:45",
"Mo-Fr 09:30-18:30",
"Mo-Fr 09:30-20:00",
"Mo-Fr 09:30-20:30; Sa 10:00-14:00",
"Mo-Fr 09:35-17:30",
"Mo-Fr 10:00-01:00; Sa-Su 11:00-02:30",
"Mo-Fr 10:00-14:00",
"Mo-Fr 10:00-14:00,17:00-20:00; Sa 10:00-14:00",
"Mo-Fr 10:00-14:00,17:00-20:30; Sa 10:00-14:00",
"Mo-Fr 10:00-14:00,17:00-21:00; Sa 10:00-14:00",
"Mo-Fr 10:00-14:30,17:30-20:30; Sa 10:00-14:30",
"Mo-Fr 10:00-16:00,21:00-00:30; Sa 12:30-16:00,21:00-00:30; Su 12:00-16:30",
"Mo-Fr 10:00-18:00",
"Mo-Fr 10:00-19:00",
"Mo-Fr 10:00-19:00; Sa 09:00-18:00",
"Mo-Fr 10:00-19:00; Sa 10:00-14:00; Su off",
"Mo-Fr 10:00-19:00; Sa 10:00-15:00",
"Mo-Fr 10:00-19:00; Sa 10:00-17:00",
"Mo-Fr 10:00-19:00; Sa 10:00-18:00; Su 10:00-17:00",
"Mo-Fr 10:00-19:00; Sa 10:00-18:00; Su 11:00-17:00",
"Mo-Fr 10:00-19:00; Sa-Su 10:00-18:00",
"Mo-Fr 10:00-19:00; Sa-Su 10:00-19:00",
"Mo-Fr 10:00-19:00;Sa 10:00-18:00",
"Mo-Fr 10:00-20:00",
"Mo-Fr 10:00-20:00, Sa 10:00-18:00, Su 10:00-17:00",
"Mo-Fr 10:00-20:00; Sa 10:00-19:00",
"Mo-Fr 10:00-20:00; Sa 10:00-19:00; Su 10:00-17:00",
"Mo-Fr 10:00-20:00; Sa-Su 10:00-17:00",
"Mo-Fr 10:00-20:00; Sa-Su 10:00-18:00",
"Mo-Fr 10:00-20:00; Sa-Su 10:00-19:00",
"Mo-Fr 10:00-20:00;Sa 10:00-16:00",
"Mo-Fr 10:00-21:00; Sa 10:00-20:00; Su 11:00-19:00",
"Mo-Fr 10:00-21:00; Sa-Su 10:00-20:00",
"Mo-Fr 10:00-21:00;Sa 10:00-18:00",
"Mo-Fr 10:00-23:00; Sa,Su 11:00-23:00",
"Mo-Fr 10:00-24:00; Sa,Su 00:00-06:00,10:00-24:00",
"Mo-Fr 10:00-24:00; Sa,Su 11:00-24:00",
"Mo-Fr 10:30-14:30,17:30-20:30; Sa 10:30-14:00",
"Mo-Fr 11:00-19:00",
"Mo-Fr 11:00-20:00",
"Mo-Fr 11:00-23:00; Sa,Su 00:00-23:00",
"Mo-Fr 11:00-23:00; Sa,Su 12:00-23:00",
"Mo-Fr 11:30-06:00, Sa,Su 12:00-06:00",
"Mo-Fr 11:30-22:30; Sa-Su 11:30-23:00",
"Mo-Fr 12:00-16:00, 19:30-23:00; Sa 12:00-16:00",
"Mo-Fr 12:00-20:00; Sa-Su 11:00-21:00",
"Mo-Fr 12:00-24:00; Sa,Su 00:00-06:00,12:00-24:00",
"Mo-Fr 13:00-16:30,20:00-21:00, Fr,Sa 13:00-01:00, Su 13:00-24:00",
"Mo-Fr 13:15-16:00, 20:15-23:30",
"Mo-Fr 15:00-21:00; Sa,Su 11:00-13:30",
"Mo-Fr 16:00-20:00; Sa-Su 11:00-20:00",
"Mo-Fr 18:30-24:00; Sa,Su 00:00-02:00,10:30-24:00",
"Mo-Fr 19:00-27:00; Sa-Su 19:00-27:30; PH 00:00-03:30; SH 00:00-03:30",
"Mo-Fr 23:30-06:00; Sa-Su 23:30-06:00",
"Mo-Sa 07:00-22:00; Su 08:00-14:00",
"Mo-Sa 08:00-17:00",
"Mo-Sa 08:00-20:00; Su 09:00-14:00",
"Mo-Sa 08:00-20:00; Su 09:00-16:00",
"Mo-Sa 08:00-21:00; Su 09:00-20:00",
"Mo-Sa 08:00-21:00; Su 09:00-21:00",
"Mo-Sa 08:00-22:00; Su 09:00-21:00",
"Mo-Sa 08:00-22:00; Su 10:00-21:00",
"Mo-Sa 08:00-23:00; Su 09:00-20:00",
"Mo-Sa 08:00-23:00; Su 09:00-22:00",
"Mo-Sa 08:30-22:00; Su 09:00-22:00",
"Mo-Sa 08:30-23:00",
"Mo-Sa 09:00-15:00; Su off",
"Mo-Sa 09:00-20:00; Su 09:00-18:00",
"Mo-Sa 09:00-20:00; Su 10:00-19:00",
"Mo-Sa 09:00-21:00",
"Mo-Sa 09:00-21:00; Su 09:00-19:00",
"Mo-Sa 09:00-21:00;Su 09:00-19:00",
"Mo-Sa 09:00-21:30",
"Mo-Sa 09:00-21:30; PH,Su 09:00-15:00",
"Mo-Sa 09:00-21:30; Su 09:00-16:00",
"Mo-Sa 09:00-21:30; Su 10:00-15:00",
"Mo-Sa 09:00-21:30; Su 10:00-21:00",
"Mo-Sa 09:00-22:00",
"Mo-Sa 09:00-22:00; Su 09:00-15:00",
"Mo-Sa 09:00-22:00; Su 10:00-16:00",
"Mo-Sa 09:00-22:00; Su 10:00-22:00",
"Mo-Sa 09:00-22:00;Su 10:00-21:00",
"Mo-Sa 09:00-23:00; Su 10:00-23:00",
"Mo-Sa 09:00-23:00; Su 11:00-23:00",
"Mo-Sa 09:00-24:00",
"Mo-Sa 09:30-21:00; Su 10:00-15:00",
"Mo-Sa 09:30-21:30",
"Mo-Sa 09:30-21:30; Su 11:00-21:00",
"Mo-Sa 09:30-21:30; Su,PH 11:00-21:00",
"Mo-Sa 09:30-21:30; Th 11:00-21:00",
"Mo-Sa 09:30-22:00; Su 10:00-22:00",
"Mo-Sa 09:30-22:30; Su 10:00-22:00",
"Mo-Sa 10:00-1:00",
"Mo-Sa 10:00-20:00; Su 10:00-18:00",
"Mo-Sa 10:00-20:00; Su 10:00-19:00",
"Mo-Sa 10:00-20:00; Su 11:00-17:00",
"Mo-Sa 10:00-20:00; Su 11:00-18:00",
"Mo-Sa 10:00-20:30",
"Mo-Sa 10:00-21:00",
"Mo-Sa 10:00-21:00; Su 10:00-20:00",
"Mo-Sa 10:00-21:00; Su 11:00-21:00",
"Mo-Sa 10:00-21:00; Su 12:00-20:00",
"Mo-Sa 10:00-22:00; Su 10:00-21:00",
"Mo-Sa 10:00-22:00; Su 11:00-21:00",
"Mo-Sa 10:30-20:00",
"Mo-Sa 10:30-20:00; Su 11:00-19:00",
"Mo-Sa 10:30-20:30",
"Mo-Sa 10:30-21:30; Su 11:00-21:00",
"Mo-Sa 11:00-14:00,17:00-20:30",
"Mo-Sa 11:00-15:00,16:30-20:30",
"Mo-Sa 11:00-15:00,16:30-21:00",
"Mo-Sa 11:00-19:00; Su 12:00-19:00",
"Mo-Sa 11:00-21:00; Su 11:00-20:00",
"Mo-Sa 11:00-21:00; Su 12:00-20:00",
"Mo-Sa 11:00-23:00; Su 12:00-23:00",
"Mo-Sa 12:00-20:00; Su 12:00-18:00",
"Mo-Sa 12:00-23:00",
"Mo-Sa 13:00-15:30, 18:30-23:00",
"Mo-Sa 13:00-16:30,20:00-24:00",
"Mo-Sa 13:00-17:00, 20:00-00:00",
"Mo-Sa 13:30-00:30; Su 11:00-00:30",
"Mo-Sa 13:30-16:00,20:00-23:30; Su off",
"Mo-Sa 18:00-21:00",
"Mo-Su 00:00-06:00,09:00-24:00",
"Mo-Su 00:00-06:00,11:00-24:00",
"Mo-Su 00:00-06:00,12:00-24:00",
"Mo-Su 05:30-01:00",
"Mo-Su 06:00-01:00",
"Mo-Su 06:00-23:00",
"Mo-Su 06:00-24:00",
"Mo-Su 06:30-00:30",
"Mo-Su 06:30-23:00",
"Mo-Su 06:30-24:00",
"Mo-Su 07:00-21:30",
"Mo-Su 07:00-22:00",
"Mo-Su 07:00-23:00",
"Mo-Su 07:00-5:00",
"Mo-Su 07:30-01:30",
"Mo-Su 07:30-23:00",
"Mo-Su 08:00-00:00",
"Mo-Su 08:00-01:00",
"Mo-Su 08:00-02:00",
"Mo-Su 08:00-20:00",
"Mo-Su 08:00-20:30",
"Mo-Su 08:00-21:00",
"Mo-Su 08:00-22:00",
"Mo-Su 08:00-23:00",
"Mo-Su 08:00-23:30",
"Mo-Su 08:30-21:00",
"Mo-Su 08:30-22:00",
"Mo-Su 08:30-24:00",
"Mo-Su 09:00-12:30,13:00-16:30,20:00-24:00",
"Mo-Su 09:00-18:00",
"Mo-Su 09:00-19:00",
"Mo-Su 09:00-20:00",
"Mo-Su 09:00-21:00",
"Mo-Su 09:00-22:00",
"Mo-Su 09:00-22:05",
"Mo-Su 09:00-22:30",
"Mo-Su 09:00-23:00",
"Mo-Su 09:00-23:30",
"Mo-Su 09:00-24:00",
"Mo-Su 09:30-13:45,17:00-20:00",
"Mo-Su 09:30-18:00",
"Mo-Su 09:30-20:30",
"Mo-Su 09:30-21:30",
"Mo-Su 09:30-22:00",
"Mo-Su 09:30-23:00; Fr 09:30-16:00; Sa off",
"Mo-Su 10:00-05:00",
"Mo-Su 10:00-13:00,19:00-22:00",
"Mo-Su 10:00-15:00,15:40-21:45",
"Mo-Su 10:00-20:00",
"Mo-Su 10:00-21:00",
"Mo-Su 10:00-21:30",
"Mo-Su 10:00-22:00",
"Mo-Su 10:00-22:00; Fr,Sa 10:00-24:00",
"Mo-Su 10:00-22:00; Jan 01,06,Dec 25 off",
"Mo-Su 10:00-22:55",
"Mo-Su 10:00-23:00",
"Mo-Su 10:00-23:00; Fr,Sa 10:00-24:00",
"Mo-Su 10:00-24:00",
"Mo-Su 11:00-01:00",
"Mo-Su 11:00-06:00",
"Mo-Su 11:00-19:30",
"Mo-Su 11:00-20:00",
"Mo-Su 11:00-21:00",
"Mo-Su 11:00-22:00",
"Mo-Su 11:00-23:00",
"Mo-Su 11:00-24:00",
"Mo-Su 11:00-24:00; Fr 11:00-18:00; Sa off",
"Mo-Su 12:00-00:00",
"Mo-Su 12:00-00:30",
"Mo-Su 12:00-02:00",
"Mo-Su 12:00-02:00; Fr,Sa 12:00-03:00",
"Mo-Su 12:00-06:00",
"Mo-Su 12:00-16:00,19:30-23:30",
"Mo-Su 12:00-20:00",
"Mo-Su 12:00-22:00",
"Mo-Su 12:00-23:00",
"Mo-Su 12:00-23:30",
"Mo-Su 12:00-24:00",
"Mo-Su 12:00-24:00, Fr,Sa 00:00-02:00",
"Mo-Su 12:30-15:30,19:30+",
"Mo-Su 12:30-17:00, 19:30-00:00",
"Mo-Su 13:00-01:30",
"Mo-Su 13:00-16:00, 20:00-00:00",
"Mo-Su 13:00-16:00,20:00+",
"Mo-Su 13:00-17:00,19:30-00:30",
"Mo-Su 13:00-24:00",
"Mo-Su 13:30-16:00,20:00-23:00",
"Mo-Su 13:30-16:00,20:30-23:30",
"Mo-Su 16:00-01:00",
"Mo-Su 17:00-06:00",
"Mo-Su 19:00-06:00; Fr,Sa 18:00-06:00",
"Mo-Su 20:30-00:30; Sa-Su 13:00-16:30",
"Mo-Su 21:00-06:00; Fr,Sa 21:00-08:00",
"Mo-Su 8:30-01:00",
"Mo-Su,PH 00:00-00:00",
"Mo-Su,PH 07:00-10:30+",
"Mo-Su,PH 08:00-02:00",
"Mo-Su,PH 08:00-23:00",
"Mo-Su,PH 10:00-22:00",
"Mo-Th 08:00-02:00; Fr-Sa 08:00-02:30",
"Mo-Th 08:00-14:00,15:00-17:00; Fr 08:00-15:00",
"Mo-Th 08:00-24:00, Fr 08:00-01:00, Sa 09:00-01:00, Su 09:00-24:00",
"Mo-Th 08:00-24:00; Sa 09:00-01:00; Su 08:00-01:00; PH 09:00-24:00",
"Mo-Th 08:30-01:00; Fr-Su 08:30-02:00",
"Mo-Th 08:30-18:30; Fr 08:30-14:30",
"Mo-Th 08:30-23:00, Fr 08:30-24:00, Sa 09:30-24:00, Su,PH 09:30-23:00",
"Mo-Th 09:00-02:00; Fr 09:00-02:30; Sa 10:00-02:30; Su 10:00-02:00",
"Mo-Th 09:00-13:00, 14:00-18:00; Fr 09:00-13:00, 14:00-17:00",
"Mo-Th 09:00-14:30,15:30-18:30; Fr 09:00-14:30; PH off",
"Mo-Th 09:00-17:00; Fr 09:00-19:30; Sa-Su 10:00-19:30",
"Mo-Th 09:00-18:00, Fr 09:00-17:00",
"Mo-Th 09:00-18:00; Fr 09:00-16:45",
"Mo-Th 09:00-18:00; Fr 09:00-17:00",
"Mo-Th 09:00-24:00; Fr 09:00-01:00; Sa 12:00-01:00; Su 12:00-24:00",
"Mo-Th 09:00-24:00; Fr 09:00-03:00; Sa 11:00-03:00; Su 11:00-24:00",
"Mo-Th 09:30-17:00; Fr 09:30-16:00",
"Mo-Th 10:00-19:00; Fr 09:30-19:00; Sa 09:30-13:00",
"Mo-Th 10:00-19:00; Su 09:00-18:00",
"Mo-Th 10:00-21:00; Fr-Sa 10:00-22:00; Su 10:00-21:00",
"Mo-Th 10:00-24:00; Fr 10:00-01:30; PH,Sa 12:00-01:30; Su 12:00-00:30",
"Mo-Th 10:30-18:45; Fr 10:30-17:30",
"Mo-Th 11:30-01:00; Fr 11:30-02:00; Sa 11:30-02:00; Su 11:30-01:00",
"Mo-Th 12:00-01:00; Fr-Sa 12:00-07:00; Su 12:00-01:00",
"Mo-Th 12:00-02:00; Fr-Sa 12:00-02:30; Su 12:00-02:00",
"Mo-Th 12:00-24:00, Fr 12:00-02:00, Sa 15:00-02:00, Su 15:00-24:00",
"Mo-Th 13:00-01:00; Fr-Su 13:00-02:00",
"Mo-Th 13:00-16:00, 19:00-00:00; Fr-Su 13:00-00:00",
"Mo-Th 13:00-16:30,20:00-24:00, Fr,Sa 13:00-16:30,20:00-00:30, Su,PH 01:00-16:30,20:00-24:00",
"Mo-Th 13:00-17:00,20:00-00:00; Fr,Su 13:00-17:00,20:00-00:30; Sa 09:00-17:00,20:00-00:00",
"Mo-Th 15:30-02:00; Fr-Sa 15:30-02:30; Su 15:30-22:30",
"Mo-Th 17:00-01:00; Fr 17:00-02:30; Sa 11:00-02:30; Su 10:00-23:00",
"Mo-Th 17:00-02:00; Fr-Sa 17:00-02:30; Su 12:00-01:00",
"Mo-Th off; Fr 18:00-21:00; Sa 17:00-20:00; Su 16:00-19:00",
"Mo-Th, Su 12:00-24:00; Fr-Sa 12:00-02:00",
"Mo-Th,PH 12:00-13:30; Fr,Sa 12:00-14:30",
"Mo-Th,Su 12:00-00:00; Fr-Sa 12:00-02:00",
"Mo-Th,Su 12:00-24:00; Fr-Sa 12:00-02:00",
"Mo-We 09:00-01:00; Th 09:00-01:30; Fr 09:00-02:00; Sa 11:00-02:00; Su 11:00-01:00",
"Mo-We 11:00-21:00; Th,Fr 11:00-22:00; Sa 12:00-22:00; Su 12:00-21:00",
"Mo-We 11:30-24:00, Th 11:30-02:00, Fr 11:30-05:00, Sa 14:00-05:00, Su 14:00-24:00",
"Mo-We 18:00-00:00; Th 18:00-01:00; Fr 18:00-02:00; Sa 12:30-02:00; Su 12:30-00:00",
"Mo-We 18:00-00:00; Th 18:00-01:00; Fr 18:00-02:00; Sa 13:00-02:00; Su 13:00-00:00",
"Mo-We, Su 12:00-00:00; Th-Sa 12:00-02:00",
"MoTh, Su 09:00-02:00; Fr-Sa 09:00-06:00",
"Oct 01-May 31: Mo-Th 09:30-15:00; Oct 01-May 31: PH,Fr,Sa,Su 09:30-18:00; Jun 01-Sep 30: Tu-Su 10:00-15:00; Aug 16-31,Jan 01,06,May 01,Dec 25 off",
"Oct-Apr: Mo-Fr 08:15-14:15; Oct-Apr: Th 16:15-18:30; May-Sep: Mo-Fr 08:15-14:15",
"Oct-Apr: Mo-We,Fr 08:15-14:00; Oct-Apr: Th 08:15-13:45,16:15-18:00; May-Sep: Mo-Fr 08:15-14:00",
"PH off",
"PH,Mo-Su 06:00-02:00",
"PH,Mo-Su 08:00-02:00",
"PH,Mo-Su 08:00-22:00",
"PH,Mo-Su 08:00-23:00",
"PH,Mo-Su 09:00-21:30",
"PH,Mo-Su 09:00-22:05",
"PH,Mo-Su 09:00-23:00",
"PH,Mo-Su 10:00-22:00",
"Sa-Su 12:00-23:00; Mo-Fr 18:00-23:00",
"Sa-Su 13:00-16:30, 20:00-00:00; Mo-Fr 13:00-16:15, 20:00-00:00",
"Sep: Mo-Sa 09:00-20:30",
"Su 10:00-14:00; Tu-Sa 11:00-20:00; PH 10:00-14:00; Mo off; Jan 01,May 01,Dec 25 off; Dec 24,31: 10:00-14:00",
"Su 13:30-16:00; Tu-Sa 13:30-16:00, 20:30-23:30",
"Su, Mo, Tu, PH 10:00-21:30; We, Th, Sa 10:00-22:00",
"Su, Tu-Th 07:00-05:00; Mo 11:00-05:00; Fr-Sa 00:00-24:00",
"Su, We-Th 23:00-05:30; Fr-Sa 23:00-06:00",
"Su,Mo off",
"Su-Mo 12:00-17:00;Tu-Sa 12:00-00:00",
"Su-Mo 13:00-17:00; Tu-Sa 20:00-00:00",
"Su-Th 00:00-02:00,10:00-24:00; Fr-Sa 00:00-02:00, 10:00-24:00",
"Su-Th 07:00-23:59; Fr,Sa 07:00-01:00",
"Su-Th 07:30-23:00; Fr,Sa 07:30-24:00",
"Su-Th 08:00-02:00; Fr,Sa 08:00-02:30",
"Su-Th 09:00-23:30; Fr-Sa 09:00-00:30",
"Su-Th 10:00-00:00; Fr-Sa 10:00-01:00; PH off",
"Su-Th 10:00-01:00; Fr,Sa 10:00-02:30",
"Su-Th 10:00-23:00; Fr-Sa 10:00-24:00",
"Su-Th 10:00-24:00, Fr,Sa 10:00-01:00",
"Su-Th 11:00-24:00, Fr,Sa 11:00-06:00",
"Su-Th 12:00-00:00; Fr-Sa 12:00-00:30",
"Su-Th 12:00-01:00; Fr-Sa 12:00-03:00",
"Su-Th 12:00-01:30; Fr,Sa 12:00-02:00",
"Su-Th 12:00-0:00; Fr-Sa 12:00-2:00",
"Su-Th 12:00-24:00, Fr,Sa 12:00-01:00",
"Su-Th 12:00-24:00, Fr,Sa 12:00-02:00",
"Su-Th 12:00-24:00, Fr,Sa 12:00-03:00",
"Su-Th 12:00-24:00, Fr,Sa 12:00-06:00",
"Su-Th 12:00-24:00; Fr-Sa 12:00-01:00",
"Su-Th 12:30-24:00, Fr,Sa 12:30-00:30",
"Su-Th 13:00-16:00,20:00-23:00; Fr-Sa 13:00-16:00,20:00-24:00",
"Su-Th 13:00-24:00; Fr,Sa 13:00-00:30",
"Su-Th 13:30-16:30; Fr-Sa 13:30-16:30, 20:30-23:30",
"Su-Th 15:00-24:00, Fr,Sa 15:00-03:00",
"Su-Th 18:00-01:00; Fr-Sa 18:00-03:00",
"Th-Su 22:00-06:00+",
"Tu 09:00-14:00,15:00-20:00; We-Fr 09:00-14:00,15:00-18:00; Sa 09:00-14:00",
"Tu 11:00-19:30; Fr-Su 11:00-19:30; We-Th 12:00-20:30",
"Tu, Th, Sa 10:00-18:00; Su, Fr 10:00-17:00; We 10:00-20:00",
"Tu-Fr 09:00-16:00; Sa 09:00-15:00",
"Tu-Fr 11:00-14:00,17:00-21:00; Sa,Su 10:30-14:30",
"Tu-Fr 19:00-22:00; Sa-Su 18:00-22:00",
"Tu-Sa 09:00-13:00,14:00-18:00",
"Tu-Sa 10:00-20:00",
"Tu-Sa 10:00-21:00; Su 10:00-14:00",
"Tu-Sa 13:00-21:00",
"Tu-Sa 13:00-24:00",
"Tu-Sa 13:30-16:00,18:30-23:30; Su 19:30-23:30",
"Tu-Sa 14:00-23:00; Su 14:00-22:00",
"Tu-Sa 21:00-4:00",
"Tu-Su 09:00-17:00,19:00-23:00",
"Tu-Su 10:00-18:00",
"Tu-Su 11:00-01:30",
"Tu-Su 11:00-16:30,19:30-24:00",
"Tu-Su 13:00-16:00,20:00-24:00",
"Tu-Su 13:00-24:00",
"Tu-Su 13:30-16:00,20:30-24:00",
"Tu-Th 11:00-20:00; Fr-Su 11:00-19:00",
"Tu-Th 12:00-24:00; Fr,Sa 12:00-02:00; Su 12:00-18:00",
"Tu-Th 13:00-16:30,19:30-23:30; Fr-Su 13:00-17:00,19:30-23:30; Mo off",
"Tu-Th 13:30-23:30; Fr,Sa 13:30-01:30",
"Tu-Th 17:00-02:00; Fr,Sa 17:00-06:00",
"We 13:00-16:00,20:00-24:00",
"We,Fr-Su 10:30-18:00; Th 12:00-20:00",
"We,Th 20:00-03:00; Fr 19:00-03:30; Sa 18:00-03:30; Su 19:00-03:00",
"We-Fr 11:00-19:00; Sa-Su 11:00-18:00",
"We-Sa 11:00-00:30; Su-Tu 11:00-17:30",
"We-Sa 11:00-19:00; Th 12:00-21:00; Su 11:00-18:00",
"We-Su 11:00-18:00",
"We-Su 12:00-19:00",
"We-Th 09:00-17:00; Fr-Su 09:00-21:00",
"closed",
"lunes  - viernes : 15:00-22:00,sábado - domingo : 12:00-22:00",
"open \"By appointment only\";PH off",
"sunrise-sunset"
]
```

`skills/osm-day-route-day-plan/tests/test_opening_hours.py`:

```python
import datetime
import json
from pathlib import Path

import pytest

from day_plan.opening_hours import (
    OpeningResult, evaluate, format_intervals, latest_close, open_at,
)

SAT = datetime.date(2026, 6, 27)   # a Saturday
SUN = datetime.date(2026, 6, 28)
MON = datetime.date(2026, 6, 29)
WED = datetime.date(2026, 7, 1)
HERE = Path(__file__).parent


def hm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def test_simple_weekday_rules_and_later_rule_wins():
    spec = "Mo-Fr 09:00-18:00; Sa 10:00-14:00; Su off"
    assert evaluate(spec, WED).intervals == [(hm("09:00"), hm("18:00"))]
    assert evaluate(spec, SAT).intervals == [(hm("10:00"), hm("14:00"))]
    assert evaluate(spec, SUN).status == "closed"
    override = evaluate("Mo-Fr 09:00-18:00; We off", WED)
    assert override.status == "closed"


def test_several_time_ranges_in_one_rule():
    result = evaluate("Mo-Th 08:00-14:00,15:00-17:00; Fr 08:00-15:00", WED)
    assert result.intervals == [(hm("08:00"), hm("14:00")), (hm("15:00"), hm("17:00"))]
    assert format_intervals(result.intervals) == "08:00–14:00, 15:00–17:00"


def test_comma_before_a_new_weekday_selector_starts_a_new_rule():
    spec = "Su-Th 12:30-24:00, Fr,Sa 12:30-00:30"      # real Madrid string
    assert evaluate(spec, WED).intervals == [(hm("12:30"), 1440)]
    sat = evaluate(spec, SAT)                            # Friday's late close spills into Saturday morning
    assert sat.intervals == [(0, hm("00:30")), (hm("12:30"), 1440 + hm("00:30"))]
    assert format_intervals(sat.intervals) == "00:00–00:30, 12:30–00:30 (+1)"


def test_wrapping_weekday_range_and_single_digit_hours():
    assert evaluate("Su-Th 12:00-24:00", SUN).status == "open_hours"
    assert evaluate("Su-Th 12:00-24:00", SAT).status == "closed"
    assert evaluate("8:00-2:30", WED).intervals == [(0, hm("02:30")), (hm("08:00"), 1440 + hm("02:30"))]


def test_midnight_and_24_00_endings():
    assert evaluate("10:00-00:00", WED).intervals == [(hm("10:00"), 1440)]
    assert format_intervals(evaluate("12:30-24:00", WED).intervals) == "12:30–24:00"
    assert evaluate("Mo-Su 10:00-05:00", WED).intervals == [(0, hm("05:00")), (hm("10:00"), 1440 + hm("05:00"))]


def test_24_7_is_open_all_day():
    result = evaluate("24/7", SAT)
    assert result.status == "open_all_day" and result.intervals == [(0, 1440)]
    assert evaluate("Mo-Su 00:00-24:00", SAT).status == "open_all_day"


def test_open_ended_time_runs_to_midnight():
    result = evaluate("Mo-Su 12:30-15:30,19:30+", SAT)
    assert result.intervals == [(hm("12:30"), hm("15:30")), (hm("19:30"), 1440)]


def test_public_holiday_rules():
    spec = "Mo-Sa 09:30-21:30; Su,PH 11:00-21:00"
    assert evaluate(spec, WED, holiday=False).intervals == [(hm("09:30"), hm("21:30"))]
    holiday = evaluate(spec, WED, holiday=True)
    assert holiday.intervals == [(hm("11:00"), hm("21:00"))] and not holiday.uncertain
    unknown = evaluate(spec, WED, holiday=None)
    assert unknown.intervals == [(hm("09:30"), hm("21:30"))] and unknown.uncertain
    assert evaluate("Mo-Fr 09:00-18:00; PH off", WED, holiday=True).status == "closed"
    assert evaluate("Mo-Su,PH 08:00-23:00", SAT, holiday=False).status == "open_hours"


def test_month_ranges():
    spec = "Jun-Aug Mo-Su 10:00-20:00; Sep-May Mo-Su 10:00-17:00"
    assert evaluate(spec, WED).intervals == [(hm("10:00"), hm("20:00"))]
    assert evaluate(spec, datetime.date(2026, 12, 2)).intervals == [(hm("10:00"), hm("17:00"))]
    assert evaluate("Dec-Feb Mo-Su 09:00-15:00", datetime.date(2026, 1, 10)).status == "open_hours"   # wraps the year
    assert evaluate("Dec-Feb Mo-Su 09:00-15:00", WED).status == "closed"


def test_sunrise_and_sunset_bounds_need_the_light_data():
    sun = {"sunrise": hm("06:00"), "sunset": hm("21:00")}
    assert evaluate("sunrise-sunset", WED, sun=sun).intervals == [(hm("06:00"), hm("21:00"))]
    assert evaluate("Mo-Su 09:00-sunset", WED, sun=sun).intervals == [(hm("09:00"), hm("21:00"))]
    missing = evaluate("sunrise-sunset", WED)
    assert missing.status == "unknown" and "sunrise" in missing.note


@pytest.mark.parametrize("spec", [
    "Mo-Fr 09:00-18:00 \"by appointment\"", "Mo-Fr 09:00-21:00; Su[1] 10:00-15:00", "Mo-Fr 09:00-18:00; SH off",
    "Jan 01,06 off; Mo-Su 10:00-22:00", "Mo-Fr 19:00-27:00", "open \"By appointment only\"", "Mo-Fr 09:00-18:00 || open",
    "week 1-53 Mo 09:00-12:00", "Mo-Su 09:00", "Mo-Fr", "", "   ", "Mo-Fr 09:00-(sunrise+01:00)",
])
def test_unsupported_syntax_is_unknown_never_a_guess(spec):
    result = evaluate(spec, WED)
    assert result.status == "unknown" and result.intervals == [] and result.note


def test_a_list_of_closures_only_is_unknown_not_closed():
    assert evaluate("PH off", WED, holiday=True).status == "unknown"
    assert evaluate("off", WED).status == "closed"


def test_open_at_and_latest_close():
    result = evaluate("Mo-Su 09:00-18:00", WED)
    assert open_at(result, hm("12:00")) and not open_at(result, hm("18:00")) and not open_at(result, hm("08:59"))
    assert latest_close(result) == hm("18:00")
    assert latest_close(evaluate("Su off", SUN)) is None


def test_real_world_strings_never_raise_and_are_sane():
    strings = json.loads((HERE / "fixtures" / "opening_hours_real.json").read_text(encoding="utf-8"))
    assert len(strings) > 400          # Madrid, Yekaterinburg and Moscow, as fetched from Overpass
    sun = {"sunrise": hm("06:00"), "sunset": hm("21:00")}
    unknown = 0
    for spec in strings:
        for day in (SAT, SUN, WED):
            for holiday in (True, False, None):
                result = evaluate(spec, day, holiday, sun)
                assert isinstance(result, OpeningResult), spec
                assert result.status in ("open_hours", "open_all_day", "closed", "unknown"), spec
                for s, e in result.intervals:
                    assert 0 <= s < e <= 2880, (spec, result.intervals)
                if result.status == "unknown":
                    assert result.note, spec
        if evaluate(spec, WED, False, sun).status == "unknown":
            unknown += 1
    assert unknown / len(strings) < 0.06, f"{unknown} of {len(strings)} real strings are unsupported"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_opening_hours.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan.opening_hours'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/opening_hours.py`:

```python
"""A small evaluator for the OSM `opening_hours` tag, covering the syntax that
real data actually uses (checked against ~570 strings pulled from Madrid,
Yekaterinburg and Moscow): weekday lists and ranges (also wrapping, `Su-Th`),
several time ranges per rule, overnight ranges (`12:00-05:00`, `8:00-2:30`,
`24:00`), open-ended times (`19:30+`), `off`/`closed`, `24/7`, `PH`, month
ranges (`Jun-Aug`), `sunrise`/`sunset` bounds, and rules separated by `;` or by
a comma before a new weekday selector (`Su-Th 12:30-24:00, Fr,Sa 12:30-00:30`).

Anything else (`SH`, `week`, `[1]`, quoted comments, years, `easter`, `||`,
offsets such as `(sunrise+01:00)`) gives status "unknown" with the reason —
never a guess. A later rule overrides an earlier one on the days it matches
(OSM semantics)."""
import datetime
import re
from dataclasses import dataclass, field

WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SUN_BOUNDS = ("sunrise", "sunset")

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<comment>"[^"]*")
      | (?P<h247>24/7)
      | (?P<time>\d{1,2}:\d{2})
      | (?P<word>[A-Za-z]+)
      | (?P<sym>[,;\-+:])
      | (?P<other>\S)
    )""", re.VERBOSE)


@dataclass
class OpeningResult:
    status: str                      # open_hours | open_all_day | closed | unknown
    intervals: list = field(default_factory=list)   # [(start_min, end_min)] for the date; end may exceed 1440
    note: str | None = None          # the reason when status is "unknown"
    uncertain: bool = False          # a PH rule exists but the holiday status was not known


class _Unsupported(Exception):
    pass


@dataclass
class _Rule:
    days: set = field(default_factory=set)      # weekday indexes, Monday = 0
    ph: bool = False
    months: set = field(default_factory=set)    # 1..12
    times: list = field(default_factory=list)   # [(start, end)]; a bound is minutes, or a name in SUN_BOUNDS, or end == "open_end"
    off: bool = False
    has_selector: bool = False

    @property
    def finished(self) -> bool:
        return bool(self.times) or self.off


def _tokenize(text: str) -> list:
    tokens, pos = [], 0
    while pos < len(text.rstrip()):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _Unsupported(f"cannot read {text[pos:pos + 12].strip()!r}")
        pos = m.end()
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
    return tokens


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    if int(hours) > 24 or int(minutes) > 59:
        raise _Unsupported(f"bad time {clock!r}")
    return int(hours) * 60 + int(minutes)


def _expand(names: tuple, first: str, last: str | None) -> list:
    i, j = names.index(first), names.index(last if last else first)
    out = [i]
    while i != j:
        i = (i + 1) % len(names)
        out.append(i)
    return out


def _read_bound(tokens: list, i: int):
    """A time bound at tokens[i]: (minutes | 'sunrise' | 'sunset', next_index)."""
    if i >= len(tokens):
        raise _Unsupported("a time range without an end")
    kind, value = tokens[i]
    if kind == "time":
        return _minutes(value), i + 1
    if kind == "word" and value.lower() in SUN_BOUNDS:
        return value.lower(), i + 1
    raise _Unsupported("unsupported time range")


def _parse_chunk(tokens: list) -> list:
    """The tokens of one ';'-separated chunk -> [_Rule]."""
    rules, cur, i = [], _Rule(), 0

    def flush():
        nonlocal cur
        if cur.has_selector or cur.finished:
            rules.append(cur)
        cur = _Rule()

    while i < len(tokens):
        kind, value = tokens[i]
        if kind in ("comment", "other"):
            raise _Unsupported("unsupported syntax " + value)
        if kind == "h247":
            cur.times.append((0, 1440))
            i += 1
        elif kind == "sym":
            if value not in (",", ":"):   # ':' only as the separator in "Jun-Aug: 09:00-18:00"
                raise _Unsupported("unsupported syntax " + value)
            i += 1
        elif kind == "time":
            start = _minutes(value)
            if i + 1 < len(tokens) and tokens[i + 1] == ("sym", "+"):
                cur.times.append((start, "open_end"))
                i += 2
            elif i + 1 < len(tokens) and tokens[i + 1] == ("sym", "-"):
                end, i = _read_bound(tokens, i + 2)
                cur.times.append((start, end))
            else:
                raise _Unsupported("a single time without a range")
        elif value.lower() in SUN_BOUNDS:
            start = value.lower()
            if not (i + 1 < len(tokens) and tokens[i + 1] == ("sym", "-")):
                raise _Unsupported("unsupported sunrise/sunset usage")
            end, i = _read_bound(tokens, i + 2)
            cur.times.append((start, end))
        elif value.lower() in ("off", "closed"):
            cur.off = True
            i += 1
        elif value in WEEKDAYS or value in MONTHS or value == "PH":
            if cur.finished:              # a comma-separated new rule begins here
                flush()
            cur.has_selector = True
            if value == "PH":
                cur.ph = True
                i += 1
                continue
            names = WEEKDAYS if value in WEEKDAYS else MONTHS
            last = None
            if (i + 2 < len(tokens) and tokens[i + 1] == ("sym", "-")
                    and tokens[i + 2][0] == "word" and tokens[i + 2][1] in names):
                last = tokens[i + 2][1]
                i += 2
            indexes = _expand(names, value, last)
            if names is WEEKDAYS:
                cur.days.update(indexes)
            else:
                cur.months.update(m + 1 for m in indexes)
            i += 1
        else:
            raise _Unsupported("unsupported word " + value)
    flush()
    for rule in rules:
        if rule.has_selector and not rule.finished:
            raise _Unsupported("a selector without times is not read")
    return rules


class _NeedsSun(Exception):
    pass


def _resolve(times: list, sun: dict | None) -> list:
    out = []
    for start, end in times:
        def bound(b):
            if b in SUN_BOUNDS:
                if not sun or sun.get(b) is None:
                    raise _NeedsSun()
                return sun[b]
            return b
        s = bound(start)
        if end == "open_end":
            e = 1440
        else:
            e = bound(end)
            if e <= s and not (s == 0 and e == 0):
                e += 1440        # overnight, and "10:00-00:00" meaning midnight
            if s == 0 and e == 0:
                e = 1440
        out.append((int(s), int(e)))
    return out


def _matches(rule: _Rule, day: datetime.date, holiday) -> bool:
    if rule.months and day.month not in rule.months:
        return False
    if rule.days or rule.ph:
        return day.weekday() in rule.days or (rule.ph and holiday is True)
    return True


def _day_intervals(rules: list, day: datetime.date, holiday, sun) -> list:
    state = None
    for rule in rules:
        if _matches(rule, day, holiday):
            state = rule                 # a later matching rule overrides
    if state is None or state.off:
        return []
    return _resolve(state.times, sun)


def _merge(intervals: list) -> list:
    merged = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def evaluate(spec: str, day: datetime.date, holiday: bool | None = None, sun: dict | None = None) -> OpeningResult:
    """Opening status of `spec` on `day`. `holiday` is True/False, or None when
    unknown; `sun` is {"sunrise": minute, "sunset": minute} local minutes."""
    text = (spec or "").strip()
    if not text:
        return OpeningResult("unknown", note="empty value")
    try:
        tokens = _tokenize(text)
        rules = []
        chunk = []
        for token in tokens + [("sym", ";")]:
            if token == ("sym", ";"):
                if chunk:
                    rules.extend(_parse_chunk(chunk))
                chunk = []
            else:
                chunk.append(token)
        if not rules:
            return OpeningResult("unknown", note="empty value")
        if not any(r.times for r in rules) and any(r.has_selector for r in rules):
            return OpeningResult("unknown", note="only closures are listed, the opening hours are not")
        today = _day_intervals(rules, day, holiday, sun)
        previous = _day_intervals(rules, day - datetime.timedelta(days=1), None, sun)
    except _Unsupported as e:
        return OpeningResult("unknown", note=str(e))
    except _NeedsSun:
        return OpeningResult("unknown", note="needs sunrise/sunset times")
    spill = [(0, e - 1440) for _, e in previous if e > 1440]
    intervals = _merge(spill + today)
    uncertain = holiday is None and any(r.ph for r in rules)
    if any(s <= 0 and e >= 1440 for s, e in intervals):
        return OpeningResult("open_all_day", [(0, 1440)], uncertain=uncertain)
    if intervals:
        return OpeningResult("open_hours", intervals, uncertain=uncertain)
    return OpeningResult("closed", [], uncertain=uncertain)


def _clock(minute: int, end: bool = False) -> str:
    if end and minute == 1440:
        return "24:00"
    return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"


def format_intervals(intervals: list) -> str:
    """'09:00–18:00, 19:00–02:00 (+1)' (the +1 marks a close after midnight;
    a close exactly at midnight is written 24:00)."""
    parts = []
    for s, e in intervals:
        text = f"{_clock(s)}–{_clock(e, end=True)}"
        parts.append(text + (" (+1)" if e > 1440 else ""))
    return ", ".join(parts)


def open_at(result: OpeningResult, minute: int) -> bool:
    return any(s <= minute < e for s, e in result.intervals)


def latest_close(result: OpeningResult) -> int | None:
    """The last minute of the date at which the place is open (may exceed 1440), or None."""
    return max((e for _, e in result.intervals), default=None)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_opening_hours.py -q`
Expected: PASS (26 passed). About 96% of the real strings are understood; the rest (point dates such as `Jan 01,06`, quoted comments, `SH`, typos) are reported as `unknown` with a reason.

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/day_plan/opening_hours.py skills/osm-day-route-day-plan/tests/test_opening_hours.py skills/osm-day-route-day-plan/tests/fixtures/opening_hours_real.json
git commit -m "Add opening_hours evaluator tested against 531 real OSM strings

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The calendar — weekday, weekend, public holiday

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/calendar_info.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`, `skills/osm-day-route-day-plan/scripts/day_plan/http.py`
- Test: `skills/osm-day-route-day-plan/tests/test_calendar_info.py`

**Interfaces:**
- Consumes: `lookup` (Task 2), `HttpError`, `tr`, `ctx.centroid`, `ctx.cache`, `ctx.http`, `ctx.facts`.
- Produces: `DayType(weekday, is_weekend, holiday, holiday_name, source, country, note_key, regional_name, sources)` with `holiday` True/False/None (unknown); `resolve_day_type(ctx) -> DayType` (a `calendar` fact with `day_type` wins; else Nominatim country + Nager.Date list; a regional-only holiday gives `holiday=None` with `regional_name`); `country_code(ctx)`; `describe(day, ctx) -> str` (one Markdown line, with the "list can miss transferred days off" caveat when the source is Nager.Date).

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_calendar_info.py`:

```python
import datetime
import json

import pytest

from day_plan.calendar_info import DayType, country_code, describe, resolve_day_type
from day_plan.context import build_context
from day_plan.http import HttpError

MADRID_ROUTE = ((-3.75, 40.42, 600.0), (-3.74, 40.43, 640.0))
HOLIDAYS_ES = [
    {"date": "2026-06-24", "localName": "San Juan", "name": "St John", "global": False, "counties": ["ES-CT"]},
    {"date": "2026-08-15", "localName": "Asunción", "name": "Assumption", "global": True, "counties": None},
]


class FakeWeb:
    def __init__(self, country="es", holidays=HOLIDAYS_ES):
        self.calls, self.country, self.holidays = [], country, holidays

    def __call__(self, url):
        self.calls.append(url)
        if "nominatim" in url:
            if self.country is HttpError:
                raise HttpError("down")
            return {"address": {"country_code": self.country}} if self.country else {"error": "Unable to geocode"}
        if "date.nager.at" in url:
            if self.holidays is HttpError:
                raise HttpError("404")
            return self.holidays
        raise AssertionError(url)


def _ctx(make_route, fixed_now, web, date, lang="en", facts=None, folder="route"):
    route_dir = make_route(coords=MADRID_ROUTE, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return build_context(route_dir, date, lang=lang, http=web, now=fixed_now)


def test_saturday_that_is_not_a_holiday(make_route, fixed_now):
    web = FakeWeb()
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 6, 27))
    day = resolve_day_type(ctx)
    assert (day.weekday, day.is_weekend, day.holiday, day.source, day.country) == (5, True, False, "nager", "ES")
    assert describe(day, ctx).startswith("Date: Saturday 2026-06-27 — weekend; not a public holiday (Nager.Date, ES)")


def test_global_holiday_on_a_weekday(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 8, 15))   # a Saturday in 2026, still a holiday
    day = resolve_day_type(ctx)
    assert day.holiday is True and day.holiday_name == "Asunción"
    assert "public holiday: Asunción" in describe(day, ctx)


def test_regional_holiday_is_reported_as_possible_not_as_certain(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 24))
    day = resolve_day_type(ctx)
    assert day.holiday is None and day.regional_name == "San Juan"
    assert "possible regional holiday: San Juan" in describe(day, ctx)


def test_country_and_holiday_list_are_cached_between_runs(make_route, fixed_now):
    web = FakeWeb()
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 6, 27))
    resolve_day_type(ctx)
    resolve_day_type(ctx)
    assert sum("nominatim" in u for u in web.calls) == 1
    assert sum("nager" in u for u in web.calls) == 1
    assert "zoom=3" in web.calls[0]


def test_country_lookup_failure_is_not_cached_but_no_country_is(make_route, fixed_now):
    failing = FakeWeb(country=HttpError)
    ctx = _ctx(make_route, fixed_now, failing, datetime.date(2026, 6, 27))
    assert country_code(ctx) is None and country_code(ctx) is None
    assert sum("nominatim" in u for u in failing.calls) == 2     # a transient failure is retried
    ocean = FakeWeb(country="")
    ctx2 = _ctx(make_route, fixed_now, ocean, datetime.date(2026, 6, 27), folder="ocean")
    assert country_code(ctx2) is None and country_code(ctx2) is None
    assert sum("nominatim" in u for u in ocean.calls) == 1        # a definite "no country" is remembered


def test_unknown_when_the_country_or_the_list_is_unavailable(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(country=HttpError), datetime.date(2026, 6, 27))
    day = resolve_day_type(ctx)
    assert day.holiday is None and day.note_key == "cal_no_country"
    assert "public-holiday status unknown (the country of the route could not be determined)" in describe(day, ctx)
    ctx2 = _ctx(make_route, fixed_now, FakeWeb(holidays=HttpError), datetime.date(2026, 6, 27), folder="nolist")
    day2 = resolve_day_type(ctx2)
    assert day2.holiday is None and day2.country == "ES" and day2.note_key == "cal_list_unavailable"


def test_a_web_sourced_calendar_fact_overrides_the_list(make_route, fixed_now):
    facts = {"2026-05-11": {"calendar": {"day_type": "holiday", "sources": ["https://consultant.ru/x"]}}}
    web = FakeWeb(country="ru", holidays=[])
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 5, 11), facts=facts)
    day = resolve_day_type(ctx)
    assert day.holiday is True and day.source == "facts" and day.sources == ["https://consultant.ru/x"]
    assert web.calls == []                       # no network needed when Claude recorded the day type
    assert "(web-sourced)" in describe(day, ctx)


def test_working_saturday_fact(make_route, fixed_now):
    facts = {"all": {"calendar": {"day_type": "workday", "sources": ["https://consultant.ru/x"]}}}
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), facts=facts)
    day = resolve_day_type(ctx)
    assert day.is_weekend is False and day.holiday is False


def test_a_calendar_fact_without_sources_is_ignored(make_route, fixed_now):
    facts = {"2026-06-27": {"calendar": {"day_type": "holiday"}}}
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), facts=facts)
    assert resolve_day_type(ctx).source == "nager"


def test_russian_line_and_caveat(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), lang="ru")
    text = describe(resolve_day_type(ctx), ctx)
    assert text.startswith("Дата: суббота 2026-06-27 — выходной; не государственный праздник (Nager.Date, ES)")
    assert "перенесённые выходные" in text


def test_the_nominatim_request_identifies_the_app(make_route, fixed_now):
    from day_plan.http import USER_AGENT
    assert "osm-day-route-day-plan" in USER_AGENT and "github.com/cerocoder/osm-hike-route" in USER_AGENT
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_calendar_info.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan.calendar_info'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/calendar_info.py`:

```python
"""What kind of day is the plan for: weekday, weekend, public holiday.

Sources, in order: a `calendar` entry in facts.json with a `day_type` (Claude
looked it up on the web — the way to cover transferred days off, which the
free list is incomplete for Russia: it misses 8 January and the transferred
days off, for example 9 March and 11 May 2026); otherwise the route's country from
Nominatim (cached for good — a country does not move; one request per route)
and the public-holiday list from Nager.Date (keyless, cached 30 days). When
neither is available the holiday status is None (unknown), never assumed."""
import urllib.parse
from dataclasses import dataclass, field

from .facts import lookup
from .http import HttpError
from .i18n import tr

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays"
HOLIDAY_LIST_TTL_S = 30 * 86400


@dataclass
class DayType:
    weekday: int                       # Monday = 0
    is_weekend: bool
    holiday: bool | None               # None = unknown
    holiday_name: str | None = None
    source: str = "none"               # "facts" | "nager" | "none"
    country: str | None = None         # upper-case ISO 3166-1 alpha-2
    note_key: str | None = None        # i18n key explaining an unknown holiday status
    regional_name: str | None = None
    sources: list = field(default_factory=list)   # URLs when source == "facts"


def country_code(ctx) -> str | None:
    lat, lon = ctx.centroid
    key = f"country|{lat:.2f}|{lon:.2f}"
    cached = ctx.cache.get_entry(key)          # never expires
    if cached is not None:
        return cached[0] or None
    query = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.4f}", "lon": f"{lon:.4f}",
                                    "zoom": 3, "addressdetails": 1})
    try:
        data = ctx.http(f"{NOMINATIM_URL}?{query}")
    except HttpError:
        return None                            # transient: not cached
    code = ((data or {}).get("address") or {}).get("country_code") if isinstance(data, dict) else None
    code = code.upper() if isinstance(code, str) and len(code) == 2 else ""
    ctx.cache.put(key, code)
    return code or None


def _holidays(ctx, code: str) -> list | None:
    key = f"nager|{code}|{ctx.date.year}"
    cached = ctx.cache.get_entry(key, HOLIDAY_LIST_TTL_S)
    if cached is not None:
        return cached[0]
    try:
        data = ctx.http(f"{NAGER_URL}/{ctx.date.year}/{code}")
    except HttpError:
        return None
    if not isinstance(data, list):
        return None
    ctx.cache.put(key, data)
    return data


def resolve_day_type(ctx) -> DayType:
    weekday = ctx.date.weekday()
    weekend = weekday >= 5
    fact = lookup(ctx.facts, ctx.date_iso, "calendar")
    if fact and fact.get("day_type"):
        kind = fact["day_type"]
        return DayType(weekday, True if kind == "weekend" else False if kind == "workday" else weekend,
                       holiday=(kind == "holiday"), source="facts", sources=fact["sources"])
    code = country_code(ctx)
    if code is None:
        return DayType(weekday, weekend, None, note_key="cal_no_country")
    holidays = _holidays(ctx, code)
    if holidays is None:
        return DayType(weekday, weekend, None, country=code, note_key="cal_list_unavailable")
    today = [h for h in holidays if isinstance(h, dict) and h.get("date") == ctx.date_iso]
    for h in today:
        if h.get("global", True):
            return DayType(weekday, weekend, True, holiday_name=h.get("localName") or h.get("name"),
                           source="nager", country=code)
    if today:
        h = today[0]
        return DayType(weekday, weekend, None, source="nager", country=code,
                       regional_name=h.get("localName") or h.get("name"))
    return DayType(weekday, weekend, False, source="nager", country=code)


def describe(day: DayType, ctx) -> str:
    """One line for the plan: 'Date: Saturday 2026-06-27 — weekend; not a public holiday (Nager.Date, ES)'."""
    lang = ctx.lang
    if day.holiday is True:
        holiday = tr("cal_holiday_yes", lang, name=day.holiday_name or "?")
    elif day.holiday is False:
        holiday = tr("cal_holiday_no", lang)
    elif day.regional_name:
        holiday = tr("cal_holiday_regional", lang, name=day.regional_name)
    else:
        holiday = tr("cal_holiday_unknown", lang)
    if day.source == "nager":
        source = tr("cal_source_nager", lang, country=day.country)
    elif day.source == "facts":
        source = tr("cal_source_facts", lang)
    else:
        source = "(" + tr(day.note_key, lang, country=day.country or "?") + ")" if day.note_key else ""
    kind = tr("cal_weekend" if day.is_weekend else "cal_workday", lang)
    line = tr("cal_line", lang, weekday=tr("weekday_names", lang)[day.weekday], date=ctx.date_iso,
              kind=kind, holiday=holiday, source=source).rstrip()
    if day.source == "nager":
        line += " *" + tr("cal_caveat", lang) + "*"
    return line
```

Then the strings and the identifying User-Agent (Nominatim's usage policy):

In `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`:

**Replace:**

```python
        "compass": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    },
    "ru": {
```

**With:**

```python
        "compass": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
        # calendar (day type)
        "weekday_names": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "cal_line": "Date: {weekday} {date} — {kind}; {holiday} {source}",
        "cal_weekend": "weekend", "cal_workday": "working day",
        "cal_holiday_yes": "public holiday: {name}", "cal_holiday_no": "not a public holiday",
        "cal_holiday_unknown": "public-holiday status unknown",
        "cal_holiday_regional": "possible regional holiday: {name}",
        "cal_source_nager": "(Nager.Date, {country})", "cal_source_facts": "(web-sourced)",
        "cal_caveat": "The official list can miss regional holidays and transferred days off; for Russia and neighbouring countries, check the date and record it as a `calendar` fact.",
        "cal_no_country": "the country of the route could not be determined",
        "cal_list_unavailable": "the holiday list for {country} is unavailable",
    },
    "ru": {
```

**Replace:**

```python
        "compass": ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"],
    },
    "es": {
```

**With:**

```python
        "compass": ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"],
        "weekday_names": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
        "cal_line": "Дата: {weekday} {date} — {kind}; {holiday} {source}",
        "cal_weekend": "выходной", "cal_workday": "рабочий день",
        "cal_holiday_yes": "государственный праздник: {name}", "cal_holiday_no": "не государственный праздник",
        "cal_holiday_unknown": "статус праздника неизвестен",
        "cal_holiday_regional": "возможен региональный праздник: {name}",
        "cal_source_nager": "(Nager.Date, {country})", "cal_source_facts": "(по веб-источнику)",
        "cal_caveat": "Официальный список может не содержать региональные праздники и перенесённые выходные; для России и соседних стран проверьте дату и запишите её как факт `calendar`.",
        "cal_no_country": "страну маршрута определить не удалось",
        "cal_list_unavailable": "список праздников для {country} недоступен",
    },
    "es": {
```

In `skills/osm-day-route-day-plan/scripts/day_plan/http.py`:

**Replace:**

```python
USER_AGENT = "osm-day-route-day-plan/1.0"
```

**With:**

```python
# Nominatim's usage policy asks for an identifying User-Agent.
USER_AGENT = "osm-day-route-day-plan/1.0 (+https://github.com/cerocoder/osm-hike-route)"
```


- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (149 passed).

- [ ] **Step 5: Live check (one-off, needs internet)**

```bash
curl -s -A "osm-day-route-day-plan/1.0" "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=40.4247&lon=-3.7275&zoom=3&addressdetails=1" | head -c 300
curl -s "https://date.nager.at/api/v3/PublicHolidays/2026/RU" | head -c 400
```

Expected: `"country_code":"es"` in the first; a JSON list of holidays in the second. Verified when this plan was written; note that the Russian list is incomplete: it lacks 8 January (a fixed statutory holiday) and the transferred days off (for example 9 March and 11 May 2026).

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add day-type calendar: Nominatim country, Nager.Date holidays, calendar facts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The Overpass client (lines through an access point)

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/overpass.py`, `skills/osm-day-route-day-plan/tests/fixtures/overpass_routes_madrid.json`, `skills/osm-day-route-day-plan/tests/fixtures/overpass_routes_moscow.json`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`, `skills/osm-day-route-day-plan/tests/conftest.py`
- Test: `skills/osm-day-route-day-plan/tests/test_overpass.py`

**Interfaces:**
- Consumes: `HttpError`, `tr`, `ctx.http`, `ctx.cache`.
- Produces: `run(http, ql, mirrors=MIRRORS, retries=1, sleep=None, backoff=3.0) -> dict` (raises `OverpassError`); `RouteInfo(mode, ref, name, from_, to, interval, opening_hours, operator)`; `routes_query(lat, lon, radius=80)`; `parse_routes(data) -> [RouteInfo]` (de-duplicated, sorted by mode then natural line number); `routes_near(ctx, lat, lon) -> [RouteInfo]` (cached 7 days; raises `OverpassError`); `interval_minutes(raw)`, `format_interval(raw, lang)`. The suite gets an autouse fixture so the retry pause never sleeps for real.

- [ ] **Step 1: Write the fixtures and the failing tests**

Real Overpass answers, captured when this plan was written (`out tags` for relations through public-transport nodes within 80 m of Lago metro, Madrid; and eight relations with an `interval` tag around central Moscow).

`skills/osm-day-route-day-plan/tests/fixtures/overpass_routes_madrid.json`:

```json
{
 "version": 0.6,
 "generator": "Overpass API 0.7.62.11 87bfad18",
 "osm3s": {
  "timestamp_osm_base": "2026-09-29T23:01:19Z",
  "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."
 },
 "elements": [
  {
   "type": "relation",
   "id": 334739,
   "tags": {
    "colour": "#0072CE",
    "from": "Atocha",
    "gtfs:route_id": "41",
    "gtfs:shape_id": "041_A",
    "name": "Bus 41: Atocha → Colonia del Manzanares",
    "network": "Empresa Municipal de Transportes de Madrid",
    "network:short": "EMT Madrid",
    "network:wikidata": "Q1094755",
    "operator": "Empresa Municipal de Transportes de Madrid",
    "operator:short": "EMT Madrid",
    "operator:wikidata": "Q1094755",
    "public_transport:version": "2",
    "ref": "41",
    "route": "bus",
    "to": "Colonia del Manzanares",
    "type": "route"
   }
  },
  {
   "type": "relation",
   "id": 1760758,
   "tags": {
    "colour": "#0072CE",
    "from": "Callao",
    "gtfs:route_id": "75",
    "gtfs:shape_id": "075_A",
    "name": "Bus 75: Plaza de Callao → Colonia Manzanares",
    "network": "Empresa Municipal de Transportes de Madrid",
    "network:short": "EMT Madrid",
    "network:wikidata": "Q1094755",
    "operator": "Empresa Municipal de Transportes de Madrid",
    "operator:short": "EMT Madrid",
    "operator:wikidata": "Q1094755",
    "public_transport:version": "2",
    "ref": "75",
    "route": "bus",
    "source": "https://navegapormadrid.emtmadrid.es/app/",
    "to": "Colonia Manzanares",
    "type": "route"
   }
  },
  {
   "type": "relation",
   "id": 1760759,
   "tags": {
    "colour": "#0072CE",
    "from": "Colonia Manzanares",
    "gtfs:route_id": "75",
    "gtfs:shape_id": "075_B",
    "name": "Bus 75: Colonia Manzanares → Plaza de Callao",
    "network": "Empresa Municipal de Transportes de Madrid",
    "network:short": "EMT Madrid",
    "network:wikidata": "Q1094755",
    "operator": "Empresa Municipal de Transportes de Madrid",
    "operator:short": "EMT Madrid",
    "operator:wikidata": "Q1094755",
    "public_transport:version": "2",
    "ref": "75",
    "route": "bus",
    "source": "https://navegapormadrid.emtmadrid.es/app/",
    "to": "Plaza de Callao",
    "type": "route"
   }
  },
  {
   "type": "relation",
   "id": 2390660,
   "tags": {
    "colour": "#0072CE",
    "from": "Colonia del Manzanares",
    "gtfs:route_id": "41",
    "gtfs:shape_id": "041_B",
    "name": "Bus 41: Colonia del Manzanares → Atocha",
    "network": "Empresa Municipal de Transportes de Madrid",
    "network:short": "EMT Madrid",
    "network:wikidata": "Q1094755",
    "operator": "Empresa Municipal de Transportes de Madrid",
    "operator:short": "EMT Madrid",
    "operator:wikidata": "Q1094755",
    "public_transport:version": "2",
    "ref": "41",
    "route": "bus",
    "to": "Atocha",
    "type": "route"
   }
  }
 ]
}
```

`skills/osm-day-route-day-plan/tests/fixtures/overpass_routes_moscow.json`:

```json
{
 "version": 0.6,
 "generator": "Overpass API 0.7.62.11 87bfad18",
 "osm3s": {
  "timestamp_osm_base": "2026-09-29T23:01:19Z",
  "copyright": "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."
 },
 "elements": [
  {
   "type": "relation",
   "id": 374043,
   "tags": {
    "air_conditioning": "yes",
    "bicycle": "yes",
    "blind": "limited",
    "bus_class:length": "4",
    "charge:all-in-one": "90 RUB",
    "charge:cards": "83 RUB",
    "charge:sbp": "83 RUB",
    "charge:troika": "75 RUB",
    "charge:troika_qr": "75 RUB",
    "check_date": "2023-04-01",
    "colour": "#f13e82",
    "deaf": "yes",
    "description": "Маршрут обслуживается электробусами",
    "electric_bus": "yes",
    "electric_bus:type": "OC",
    "fee": "yes",
    "fine:ticketless": "5000 RUB",
    "from": "Метро «Озёрная»",
    "interval": "10",
    "name": "Автобус м16: Метро «Озёрная» => Метро «Октябрьская»",
    "name:uk": "Автобус м16: Метро \"Озерна\" => Метро \"Жовтнева\"",
    "network": "Московский транспорт",
    "operator": "ГУП «Мосгортранс»",
    "payment:cards": "yes",
    "payment:cash": "no",
    "payment:contactless": "yes",
    "payment:maestro": "no",
    "payment:mastercard": "no",
    "payment:mir": "yes",
    "payment:nfc": "yes",
    "payment:podorozhnik": "no",
    "payment:sbp": "yes",
    "payment:social_cards": "yes",
    "payment:strelka": "no",
    "payment:troika": "yes",
    "payment:visa": "no",
    "public_transport:version": "2",
    "ref": "м16",
    "route": "bus",
    "source": "Реестр маршрутов города Москвы",
    "source:description": "https://mosgortrans.ru/electrobus/map/",
    "to": "Метро «Октябрьская»",
    "type": "route",
    "website": "https://transport.mos.ru/transport/schedule/route/1318",
    "wheelchair": "yes"
   }
  },
  {
   "type": "relation",
   "id": 1762765,
   "tags": {
    "colour": "#DC143C",
    "from": "Москва-Пассажирская-Павелецкая",
    "interval": "30",
    "name": "Аэроэкспресс: Павелецкий вокзал => Аэропорт-Домодедово",
    "name:en": "Aeroexpress: Moscow -> Domodedovo Airport",
    "name:uk": "Аероекспрес: Москва -> Аеропорт-Домодєдово",
    "network": "Аэроэкспресс",
    "network:en": "Aeroexpress",
    "network:wikidata": "Q4073726",
    "opening_hours": "Mo-Su 05:30-00:10",
    "operator": "ОАО «Аэроэкспресс»",
    "public_transport:version": "2",
    "ref": "A",
    "route": "train",
    "service": "regional",
    "to": "Аэропорт-Домодедово",
    "type": "route",
    "wikidata": "Q118587129"
   }
  },
  {
   "type": "relation",
   "id": 3225737,
   "tags": {
    "air_conditioning": "yes",
    "bicycle": "yes",
    "blind": "limited",
    "bus_class:length": "4",
    "charge:all-in-one": "90 RUB",
    "charge:cards": "83 RUB",
    "charge:sbp": "83 RUB",
    "charge:troika": "75 RUB",
    "charge:troika_qr": "75 RUB",
    "check_date": "2023-04-01",
    "colour": "#f13e82",
    "deaf": "yes",
    "description": "Маршрут обслуживается электробусами",
    "electric_bus": "yes",
    "electric_bus:type": "OC",
    "fee": "yes",
    "fine:ticketless": "5000 RUB",
    "from": "Метро «Октябрьская»",
    "interval": "10",
    "name": "Автобус м16: Метро «Октябрьская» => Метро «Озёрная»",
    "name:uk": "Автобус м16: Метро \"Жовтнева\" => Метро \"Озерна\"",
    "network": "Московский транспорт",
    "operator": "ГУП «Мосгортранс»",
    "payment:cards": "yes",
    "payment:cash": "no",
    "payment:contactless": "yes",
    "payment:maestro": "no",
    "payment:mastercard": "no",
    "payment:mir": "yes",
    "payment:nfc": "yes",
    "payment:podorozhnik": "no",
    "payment:sbp": "yes",
    "payment:social_cards": "yes",
    "payment:strelka": "no",
    "payment:troika": "yes",
    "payment:visa": "no",
    "public_transport:version": "2",
    "ref": "м16",
    "route": "bus",
    "source": "Реестр маршрутов города Москвы",
    "source:description": "https://mosgortrans.ru/electrobus/map/",
    "to": "Метро «Озёрная»",
    "type": "route",
    "website": "https://transport.mos.ru/transport/schedule/route/1318",
    "wheelchair": "yes"
   }
  },
  {
   "type": "relation",
   "id": 3228821,
   "tags": {
    "air_conditioning": "yes",
    "bicycle": "yes",
    "blind": "limited",
    "bus_class:length": "4;5",
    "charge:all-in-one": "90 RUB",
    "charge:cards": "83 RUB",
    "charge:sbp": "83 RUB",
    "charge:troika": "75 RUB",
    "charge:troika_qr": "75 RUB",
    "check_date": "2023-03-30",
    "colour": "#01b400",
    "deaf": "yes",
    "fee": "yes",
    "fine:ticketless": "5000 RUB",
    "from": "Метро «Новаторская»",
    "interval": "10",
    "name": "Автобус м1: Метро «Новаторская» => Больница РЖД",
    "network": "Московский транспорт",
    "operator": "ГУП «Мосгортранс»",
    "payment:cards": "yes",
    "payment:cash": "no",
    "payment:contactless": "yes",
    "payment:maestro": "no",
    "payment:mastercard": "no",
    "payment:mir": "yes",
    "payment:nfc": "yes",
    "payment:podorozhnik": "no",
    "payment:sbp": "yes",
    "payment:social_cards": "yes",
    "payment:strelka": "no",
    "payment:troika": "yes",
    "payment:visa": "no",
    "public_transport:version": "2",
    "ref": "м1",
    "route": "bus",
    "source": "Реестр маршрутов города Москвы",
    "to": "Больница РЖД",
    "type": "route",
    "website": "https://transport.mos.ru/transport/schedule/route/141503209",
    "wheelchair": "yes"
   }
  },
  {
   "type": "relation",
   "id": 3228965,
   "tags": {
    "air_conditioning": "yes",
    "bicycle": "yes",
    "blind": "limited",
    "bus_class:length": "4;5",
    "charge:all-in-one": "90 RUB",
    "charge:cards": "83 RUB",
    "charge:sbp": "83 RUB",
    "charge:troika": "75 RUB",
    "charge:troika_qr": "75 RUB",
    "check_date": "2023-03-30",
    "colour": "#01b400",
    "deaf": "yes",
    "fee": "yes",
    "fine:ticketless": "5000 RUB",
    "from": "Больница РЖД",
    "interval": "10",
    "name": "Автобус м1: Больница РЖД => Метро «Новаторская»",
    "network": "Московский транспорт",
    "operator": "ГУП «Мосгортранс»",
    "payment:cards": "yes",
    "payment:cash": "no",
    "payment:contactless": "yes",
    "payment:maestro": "no",
    "payment:mastercard": "no",
    "payment:mir": "yes",
    "payment:nfc": "yes",
    "payment:podorozhnik": "no",
    "payment:sbp": "yes",
    "payment:social_cards": "yes",
    "payment:strelka": "no",
    "payment:troika": "yes",
    "payment:visa": "no",
    "public_transport:version": "2",
    "ref": "м1",
    "route": "bus",
    "source": "Реестр маршрутов города Москвы",
    "to": "Метро «Новаторская»",
    "type": "route",
    "website": "https://transport.mos.ru/transport/schedule/route/141503209",
    "wheelchair": "yes"
   }
  },
  {
   "type": "relation",
   "id": 3255502,
   "tags": {
    "colour": "#DC143C",
    "from": "Одинцово",
    "interval": "30",
    "name": "Аэроэкспресс: Одинцово -> Шереметьево",
    "name:en": "Aeroexpress: Odintsovo -> Sheremetyevo",
    "name:uk": "Аероекспрес: Одинцово -> Шереметьєво",
    "network": "Аэроэкспресс",
    "network:en": "Aeroexpress",
    "network:wikidata": "Q4073726",
    "opening_hours": "Mo-Su 05:30-00:10",
    "operator": "ОАО «Аэроэкспресс»",
    "public_transport:version": "2",
    "ref": "A",
    "route": "train",
    "service": "regional",
    "to": "Аэропорт Шереметьево",
    "type": "route",
    "wikidata": "Q118582119"
   }
  },
  {
   "type": "relation",
   "id": 3255503,
   "tags": {
    "colour": "#DC143C",
    "from": "Аэропорт Шереметьево",
    "interval": "30",
    "name": "Аэроэкспресс: Шереметьево -> Одинцово",
    "name:en": "Aeroexpress: Sheremetyevo -> Odintsovo",
    "name:uk": "Аероекспрес: Шереметьєво -> Одинцово",
    "network": "Аэроэкспресс",
    "network:en": "Aeroexpress",
    "network:wikidata": "Q4073726",
    "opening_hours": "Mo-Su 05:30-00:10",
    "operator": "ОАО «Аэроэкспресс»",
    "public_transport:version": "2",
    "ref": "A",
    "route": "train",
    "service": "regional",
    "to": "Одинцово",
    "type": "route",
    "wikidata": "Q118582119"
   }
  },
  {
   "type": "relation",
   "id": 10315788,
   "tags": {
    "colour": "#DC143C",
    "from": "Аэропорт-Домодедово",
    "interval": "30",
    "name": "Аэроэкспресс: Аэропорт-Домодедово => Павелецкий вокзал",
    "name:en": "Aeroexpress: Domodedovo Airport -> Moscow",
    "name:uk": "Аероекспрес: Аеропорт-Домодєдово -> Москва",
    "network": "Аэроэкспресс",
    "network:en": "Aeroexpress",
    "network:wikidata": "Q4073726",
    "opening_hours": "Mo-Su 05:30-00:10",
    "operator": "ОАО «Аэроэкспресс»",
    "public_transport:version": "2",
    "ref": "A",
    "route": "train",
    "service": "regional",
    "to": "Москва-Пассажирская-Павелецкая",
    "type": "route",
    "wikidata": "Q118587129"
   }
  }
 ]
}
```

`skills/osm-day-route-day-plan/tests/test_overpass.py`:

```python
import json
from pathlib import Path

import pytest

from day_plan.http import HttpError
from day_plan.overpass import (
    MIRRORS, OverpassError, RouteInfo, format_interval, interval_minutes, parse_routes, routes_near,
    routes_query, run,
)

FIXTURES = Path(__file__).parent / "fixtures"
MADRID = json.loads((FIXTURES / "overpass_routes_madrid.json").read_text(encoding="utf-8"))
MOSCOW = json.loads((FIXTURES / "overpass_routes_moscow.json").read_text(encoding="utf-8"))
GOOD = {"elements": [{"tags": {"route": "bus", "ref": "1"}}]}


class Web:
    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def __call__(self, url):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_first_mirror_that_answers_wins():
    web = Web(HttpError("HTTP Error 429"), GOOD)
    assert run(web, "QL", sleep=lambda s: None) == GOOD
    assert web.urls[0].startswith(MIRRORS[0] + "?data=") and web.urls[1].startswith(MIRRORS[1])


def test_html_error_pages_and_runtime_errors_are_skipped():
    web = Web(HttpError("Expecting value"), {"remark": "runtime error: Query timed out", "elements": []}, {"unexpected": 1}, GOOD)
    assert run(web, "QL", mirrors=MIRRORS + ("https://x/api",), sleep=lambda s: None) == GOOD


def test_all_mirrors_are_retried_once_after_a_pause_then_it_gives_up():
    naps = []
    web = Web(*[HttpError("504")] * 6)
    with pytest.raises(OverpassError, match="504"):
        run(web, "QL", sleep=naps.append, backoff=3.0)
    assert len(web.urls) == 6 and naps == [3.0]


def test_query_text_is_url_encoded():
    web = Web(GOOD)
    run(web, 'node["a"="b"];', sleep=lambda s: None)
    assert '%22' in web.urls[0] and ' ' not in web.urls[0]


def test_routes_query_mentions_the_point_and_the_route_types():
    ql = routes_query(40.4247, -3.7275)
    assert "node(around:80,40.42470,-3.72750)" in ql and "subway" in ql and "out tags" in ql


def test_parse_real_madrid_bus_relations():
    routes = parse_routes(MADRID)
    assert [(r.mode, r.ref) for r in routes] == [("bus", "41"), ("bus", "41"), ("bus", "75"), ("bus", "75")]
    assert routes[0].from_ or routes[0].name
    assert all(r.interval == "" and r.opening_hours == "" for r in routes)     # OSM has no schedule here


def test_parse_real_moscow_relations_with_interval_and_hours():
    routes = parse_routes(MOSCOW)
    train = [r for r in routes if r.mode == "train"]
    assert train and train[0].interval == "30" and train[0].opening_hours == "Mo-Su 05:30-00:10"
    assert [r.mode for r in routes] == sorted((r.mode for r in routes),
                                              key=("bus", "train").index)         # sorted by mode order


def test_duplicates_and_foreign_route_types_are_dropped():
    data = {"elements": [{"tags": {"route": "bus", "ref": "9", "name": "A"}}, {"tags": {"route": "bus", "ref": "9", "name": "A"}},
                         {"tags": {"route": "hiking", "ref": "GR"}}, {"tags": {"route": "bus", "ref": "10", "name": "B"}},
                         {"tags": {"route": "bus", "ref": "2", "name": "C"}}, {}]}
    assert [(r.ref) for r in parse_routes(data)] == ["2", "9", "10"]      # natural order: 2 < 9 < 10


def test_routes_near_caches_for_a_week(make_route, fixed_now):
    from day_plan.context import build_context
    import datetime
    web = Web(MADRID)
    ctx = build_context(make_route(), datetime.date(2026, 6, 27), http=web, now=fixed_now)
    first = routes_near(ctx, 40.4247, -3.7275)
    second = routes_near(ctx, 40.4247, -3.7275)
    assert len(web.urls) == 1 and first == second and isinstance(first[0], RouteInfo)


@pytest.mark.parametrize("raw,minutes", [("10", 10), ("00:10", 10), ("00:10:00", 10), ("1:30", 90), ("0", None),
                                         ("10-15", None), ("", None), ("often", None)])
def test_interval_minutes(raw, minutes):
    assert interval_minutes(raw) == minutes


def test_format_interval_is_localized_and_falls_back_to_the_raw_text():
    assert format_interval("30", "en") == "every 30 min"
    assert format_interval("30", "ru") == "каждые 30 мин"
    assert format_interval("10-15", "en") == "10-15"
    assert format_interval("", "en") == "–"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_overpass.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan.overpass'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/overpass.py`:

```python
"""Minimal Overpass client for the day plan: the public transport lines that
serve an access point. Mirrors and retries are copied from
osm-day-route-planning/scripts/overpass_query.py on purpose (the skills do not
import each other); measured while building this: overpass-api.de answered
429 and 504 under load, overpass.kumi.systems 504, overpass.private.coffee
sometimes returns HTML — so a failed mirror is skipped and the whole set is
retried once after a pause. Any failure ends as OverpassError, which the
plugin turns into a no-data section."""
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass

from .http import HttpError
from .i18n import tr

MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
ROUTE_TYPES = ("bus", "train", "subway", "tram", "light_rail", "trolleybus", "ferry")
ROUTES_TTL_S = 7 * 86400


class OverpassError(Exception):
    pass


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)          # its own function so tests can silence it without touching time.sleep


def run(http, ql: str, mirrors=MIRRORS, retries: int = 1, sleep=None, backoff: float = 3.0) -> dict:
    sleep = sleep or _default_sleep
    last = "no mirror tried"
    for attempt in range(retries + 1):
        for mirror in mirrors:
            try:
                data = http(f"{mirror}?data={urllib.parse.quote(ql)}")
            except HttpError as e:
                last = f"{mirror}: {e}"
                continue
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                last = f"{mirror}: unexpected response"
                continue
            if "runtime error" in str(data.get("remark", "")).lower():
                last = f"{mirror}: {data.get('remark')}"
                continue
            return data
        if attempt < retries:
            sleep(backoff * (attempt + 1))
    raise OverpassError(last)


@dataclass
class RouteInfo:
    mode: str
    ref: str
    name: str
    from_: str
    to: str
    interval: str
    opening_hours: str
    operator: str


def routes_query(lat: float, lon: float, radius: int = 80) -> str:
    types = "|".join(ROUTE_TYPES)
    return (f'[out:json][timeout:25];node(around:{radius},{lat:.5f},{lon:.5f})["public_transport"];'
            f'rel(bn)["route"~"^({types})$"];out tags;')


def parse_routes(data: dict) -> list:
    """Overpass `out tags` result -> de-duplicated RouteInfo list, sorted by
    mode and line number."""
    seen, routes = set(), []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        if tags.get("route") not in ROUTE_TYPES:
            continue
        info = RouteInfo(mode=tags["route"], ref=tags.get("ref", ""), name=tags.get("name", ""),
                         from_=tags.get("from", ""), to=tags.get("to", ""), interval=tags.get("interval", ""),
                         opening_hours=tags.get("opening_hours", ""), operator=tags.get("operator", ""))
        key = (info.mode, info.ref, info.name or (info.from_, info.to))
        if key in seen:
            continue
        seen.add(key)
        routes.append(info)

    def natural(text):
        return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]

    routes.sort(key=lambda r: (ROUTE_TYPES.index(r.mode), natural(r.ref), r.name))
    return routes


def routes_near(ctx, lat: float, lon: float) -> list:
    """RouteInfo list for the lines through public-transport nodes near a point
    (cached 7 days in the route folder). Raises OverpassError."""
    key = f"overpass|routes|{lat:.4f}|{lon:.4f}"
    cached = ctx.cache.get_entry(key, ROUTES_TTL_S)
    if cached is not None:
        return [RouteInfo(**r) for r in cached[0]]
    routes = parse_routes(run(ctx.http, routes_query(lat, lon)))
    ctx.cache.put(key, [asdict(r) for r in routes])
    return routes


_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def interval_minutes(raw: str) -> int | None:
    """OSM `interval`: '10' (minutes), '00:10' or '00:10:00' (h:mm[:ss])."""
    raw = (raw or "").strip()
    if raw.isdigit():
        return int(raw) or None
    m = _CLOCK.match(raw)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) or None
    return None


def format_interval(raw: str, lang: str) -> str:
    minutes = interval_minutes(raw)
    if minutes is not None:
        return tr("tr_every", lang, n=minutes)
    return raw or "–"
```

Strings for the transit and points-of-interest sections (used by Tasks 6 and 7) and the no-sleep fixture:

In `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`:

**Replace:**

```python
        "cal_list_unavailable": "the holiday list for {country} is unavailable",
    },
    "ru": {
```

**With:**

```python
        "cal_list_unavailable": "the holiday list for {country} is unavailable",
        # transit / points of interest
        "tr_access_points": "**Access points**",
        "tr_col_point": "Access point", "tr_col_role": "Role", "tr_col_hours": "Hours on this date (OSM)",
        "tr_role_start": "start", "tr_role_end": "end", "tr_role_none": "–",
        "tr_routes_title": "**Lines serving the access points (OSM)**",
        "tr_col_line": "Line", "tr_col_type": "Type", "tr_col_direction": "Direction",
        "tr_col_interval": "Interval", "tr_col_runs": "Runs on this date",
        "tr_type_bus": "bus", "tr_type_train": "train", "tr_type_subway": "metro", "tr_type_tram": "tram",
        "tr_type_light_rail": "light rail", "tr_type_trolleybus": "trolleybus", "tr_type_ferry": "ferry",
        "tr_every": "every {n} min",
        "tr_runs_yes": "yes: {hours}", "tr_runs_no": "no", "tr_runs_unknown": "not stated in OSM",
        "tr_hours_all_day": "open 24 h", "tr_hours_closed": "closed", "tr_hours_unknown": "not read: {raw}",
        "tr_hours_missing": "not in OSM", "tr_hours_uncertain": " (depends on the public-holiday rule)",
        "tr_no_access_points": "The route archive has no access point.",
        "tr_no_osm_lines": "OSM lists no lines for these access points (or the OSM service was unavailable).",
        "tr_web_title": "**Timetables and directions (web-sourced, not verified in person)**",
        "tr_sources": "Sources: {urls}",
        "tr_no_web": "No timetable or directions from the departure point are recorded for this date.",
        "tr_warn_closed_before_return": "{name} closes at {close}, the estimated return is at {finish}.",
        "tr_warn_last_departure": "The last departure ({last}) is before the estimated return at {finish}.",
        "tr_warn_last_departure_tight": "The last departure ({last}) is less than 30 min after the estimated return at {finish}.",
        "poi_col_point": "Point", "poi_col_type": "Type", "poi_col_hours": "Hours on this date (OSM)", "poi_col_note": "Note",
        "poi_none": "The route archive has no points of interest.",
        "poi_no_hours": "No opening hours in OSM for: {names}.",
        "poi_web_title": "**Opening days and special features (web-sourced, not verified in person)**",
        "poi_warn_closed": "{name} is closed on this date.",
    },
    "ru": {
```

**Replace:**

```python
        "cal_list_unavailable": "список праздников для {country} недоступен",
    },
    "es": {
```

**With:**

```python
        "cal_list_unavailable": "список праздников для {country} недоступен",
        "tr_access_points": "**Точки заброски**",
        "tr_col_point": "Точка заброски", "tr_col_role": "Роль", "tr_col_hours": "Часы работы в эту дату (OSM)",
        "tr_role_start": "старт", "tr_role_end": "финиш", "tr_role_none": "–",
        "tr_routes_title": "**Маршруты через точки заброски (OSM)**",
        "tr_col_line": "Маршрут", "tr_col_type": "Вид", "tr_col_direction": "Направление",
        "tr_col_interval": "Интервал", "tr_col_runs": "Ходит в эту дату",
        "tr_type_bus": "автобус", "tr_type_train": "поезд", "tr_type_subway": "метро", "tr_type_tram": "трамвай",
        "tr_type_light_rail": "лёгкое метро", "tr_type_trolleybus": "троллейбус", "tr_type_ferry": "паром",
        "tr_every": "каждые {n} мин",
        "tr_runs_yes": "да: {hours}", "tr_runs_no": "нет", "tr_runs_unknown": "в OSM не указано",
        "tr_hours_all_day": "круглосуточно", "tr_hours_closed": "закрыто", "tr_hours_unknown": "не разобрано: {raw}",
        "tr_hours_missing": "нет в OSM", "tr_hours_uncertain": " (зависит от правила про праздники)",
        "tr_no_access_points": "В архиве маршрута нет точек заброски.",
        "tr_no_osm_lines": "В OSM нет маршрутов для этих точек заброски (или сервис OSM был недоступен).",
        "tr_web_title": "**Расписание и как добраться (по веб-источникам, лично не проверено)**",
        "tr_sources": "Источники: {urls}",
        "tr_no_web": "Расписание и путь от точки отправления на эту дату не записаны.",
        "tr_warn_closed_before_return": "{name} закрывается в {close}, расчётное возвращение в {finish}.",
        "tr_warn_last_departure": "Последний рейс ({last}) уходит раньше расчётного возвращения в {finish}.",
        "tr_warn_last_departure_tight": "Последний рейс ({last}) уходит менее чем через 30 мин после расчётного возвращения в {finish}.",
        "poi_col_point": "Точка", "poi_col_type": "Вид", "poi_col_hours": "Часы работы в эту дату (OSM)", "poi_col_note": "Примечание",
        "poi_none": "В архиве маршрута нет точек интереса.",
        "poi_no_hours": "В OSM нет часов работы для: {names}.",
        "poi_web_title": "**Дни работы и особенности (по веб-источникам, лично не проверено)**",
        "poi_warn_closed": "{name} закрыто в эту дату.",
    },
    "es": {
```

In `skills/osm-day-route-day-plan/tests/conftest.py`:

**Replace:**

```python
@pytest.fixture
def make_route(tmp_path):
```

**With:**

```python
@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Overpass retries pause between rounds; tests must never wait for real."""
    monkeypatch.setattr("day_plan.overpass._default_sleep", lambda seconds: None)


@pytest.fixture
def make_route(tmp_path):
```


- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (167 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add Overpass client for the lines serving an access point

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The transit plugin ("Getting there")

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py`, `skills/osm-day-route-day-plan/scripts/day_plan/plugins/transit.py`
- Modify: `skills/osm-day-route-day-plan/tests/conftest.py`
- Test: `skills/osm-day-route-day-plan/tests/test_transit.py`

**Interfaces:**
- Consumes: `ctx.access_points`, `ctx.facts`, `ctx.start_time`, `ctx.duration_hours` (Task 2); `resolve_day_type`, `describe` (Task 4); `evaluate`, `format_intervals`, `latest_close` (Task 3); `routes_near`, `format_interval`, `OverpassError` (Task 5); `lookup` (Task 2); `shared["light"]["sunrise_local_min"/"sunset_local_min"]` (plan 1).
- Produces: `TransitPlugin` (`plugin_id="transit"`, `section_id="transit"`, `depends_on=("light",)`); `plugins/common.py`: `cell`, `sun_from_light`, `finish_minute`, `hours_on_date`, `sources_line`. Section confidence: `web-sourced` when a facts entry is used, else `tag-backed` when any OSM hours or lines are shown, else `no-data`. Warnings: caution when the return access point closes before the estimated return; danger when a recorded `last_departure_local` is before it; caution when under 30 minutes after it; plus any warnings recorded in the fact. The "return point" is the access point with role `end`, or the only one; with several ambiguous ones no cross-check is made. Test fixture `make_route_with_points(points, folder, name, mode, duration_hours, coords)`.

- [ ] **Step 1: Write the fixture and the failing tests**

In `skills/osm-day-route-day-plan/tests/conftest.py`:

**Replace:**

```python
@pytest.fixture
def weather_response():
```

**With:**

```python
@pytest.fixture
def make_route_with_points(tmp_path):
    """Like make_route, plus Point features: points = [(name, type, lon, lat, {extra properties}), ...]."""
    def _make(points, folder="proute", name="Test route", mode="walk", duration_hours=4.0,
              coords=((-3.75, 40.42, 600.0), (-3.74, 40.43, 640.0))):
        route_dir = tmp_path / folder
        route_dir.mkdir()
        features = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
                     "properties": {"name": name, "mode": mode, "duration_estimate_hours": duration_hours}}]
        for pname, ptype, lon, lat, props in points:
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                             "properties": {"name": pname, "type": ptype, **props}})
        (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                                                 encoding="utf-8")
        return route_dir
    return _make


@pytest.fixture
def weather_response():
```


`skills/osm-day-route-day-plan/tests/test_transit.py`:

```python
import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.transit import TransitPlugin

FIXTURES = Path(__file__).parent / "fixtures"
MADRID = json.loads((FIXTURES / "overpass_routes_madrid.json").read_text(encoding="utf-8"))
MOSCOW = json.loads((FIXTURES / "overpass_routes_moscow.json").read_text(encoding="utf-8"))
SAT = datetime.date(2026, 6, 27)
URL = "https://www.crtm.es/horarios"


class Web:
    """Answers Nominatim, Nager.Date and Overpass; `overpass` may be a dict or an exception."""
    def __init__(self, overpass=MADRID, country="es", holidays=()):
        self.overpass, self.country, self.holidays, self.calls = overpass, country, list(holidays), []

    def __call__(self, url):
        self.calls.append(url)
        if "nominatim" in url:
            return {"address": {"country_code": self.country}}
        if "date.nager.at" in url:
            return self.holidays
        if "overpass" in url:
            if isinstance(self.overpass, Exception):
                raise self.overpass
            return self.overpass
        raise AssertionError(url)


def _plugin_run(make_route_with_points, fixed_now, points, web=None, lang="en", start=None, duration=4.0,
                facts=None, date=SAT, light=None):
    route_dir = make_route_with_points(points, duration_hours=duration)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, start_time=start, http=web or Web(), now=fixed_now)
    return TransitPlugin().run(ctx, {"light": light} if light else {})


LAGO = ("Lago", "access", -3.7275, 40.4247, {"role": "start", "opening_hours": "Mo-Su 06:00-01:30"})
ATOCHA = ("Atocha", "access", -3.6906, 40.4065, {"role": "end", "opening_hours": "Mo-Su 05:30-22:00"})


def test_no_access_points_is_a_no_data_section_that_still_says_what_day_it_is(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [])
    assert section.confidence == "no-data"
    assert "Date: Saturday 2026-06-27 — weekend" in section.markdown
    assert "The route archive has no access point." in section.markdown
    assert section.warnings == []


def test_hours_and_lines_come_from_osm_and_are_tag_backed(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO])
    md = section.markdown
    assert section.confidence == "tag-backed"
    assert "| Lago | start | 00:00–01:30, 06:00–01:30 (+1) |" in md
    assert md.count("| Lago | 41 | bus |") == 2 and "| Lago | 75 | bus |" in md
    assert "Atocha → Colonia del Manzanares" in md
    assert "No timetable or directions from the departure point are recorded" in md


def test_overpass_failure_degrades_to_a_note_and_keeps_the_hours(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=HttpError("504")))
    assert "OSM lists no lines for these access points" in section.markdown
    assert "| Lago | start | 00:00–01:30, 06:00–01:30 (+1) |" in section.markdown
    assert section.confidence == "tag-backed"           # the station hours are still OSM data


def test_access_point_without_any_osm_data_is_no_data(make_route_with_points, fixed_now):
    bare = ("Stop", "access", -3.7, 40.4, {})
    section = _plugin_run(make_route_with_points, fixed_now, [bare], web=Web(overpass={"elements": []}))
    assert section.confidence == "no-data"
    assert "| Stop | – | not in OSM |" in section.markdown


def test_interval_and_operating_hours_of_a_line_are_evaluated_for_the_date(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=MOSCOW))
    md = section.markdown
    assert "every 30 min" in md and "yes: 00:00–00:10, 05:30–00:10 (+1)" in md
    assert "every 10 min" in md and "not stated in OSM" in md


def test_a_line_that_does_not_run_on_the_date(make_route_with_points, fixed_now):
    data = {"elements": [{"tags": {"route": "bus", "ref": "7", "from": "A", "to": "B", "opening_hours": "Mo-Fr 06:00-22:00"}}]}
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=data))
    assert "| Lago | 7 | bus | A → B | – | no |" in section.markdown


def test_unreadable_hours_are_shown_verbatim_and_pipes_cannot_break_the_table(make_route_with_points, fixed_now):
    odd = ("Odd | stop", "access", -3.7, 40.4, {"opening_hours": 'Mo-Fr 09:00-18:00 "by | appointment"'})
    section = _plugin_run(make_route_with_points, fixed_now, [odd], web=Web(overpass={"elements": []}))
    row = next(l for l in section.markdown.splitlines() if l.startswith("| Odd"))
    assert row.count("|") == 4                       # 3 cells: no stray pipe from the name or the raw hours
    assert "not read:" in row


def test_public_holiday_rule_without_holiday_data_is_flagged(make_route_with_points, fixed_now):
    stop = ("Ph", "access", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; Su,PH 11:00-21:00"})
    web = Web(overpass={"elements": []})
    web.country = ""        # the country cannot be determined -> holiday unknown
    section = _plugin_run(make_route_with_points, fixed_now, [stop], web=web)
    assert "(depends on the public-holiday rule)" in section.markdown


def test_return_point_closing_before_the_estimated_return_is_a_caution(make_route_with_points, fixed_now):
    import datetime as dt
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO, ATOCHA], start=dt.time(16, 0), duration=6.5)
    assert [w.severity for w in section.warnings] == ["caution"]
    assert "Atocha closes at 22:00, the estimated return is at 22:30" in section.warnings[0].text


def test_no_start_time_means_no_cross_check(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO, ATOCHA])
    assert section.warnings == []


def test_ambiguous_return_point_is_not_checked(make_route_with_points, fixed_now):
    import datetime as dt
    first = ("A", "access", -3.7, 40.4, {"opening_hours": "Mo-Su 06:00-20:00"})
    second = ("B", "access", -3.6, 40.5, {"opening_hours": "Mo-Su 06:00-20:00"})
    section = _plugin_run(make_route_with_points, fixed_now, [first, second], start=dt.time(16, 0), duration=6.0,
                          web=Web(overpass={"elements": []}))
    assert section.warnings == []


FACT = {"markdown": "From Madrid: metro line 10 to Lago (about 25 min). Bus 41 back from Colonia every 20 min.",
        "sources": [URL, "https://www.metromadrid.es/"]}


def test_web_facts_are_shown_with_sources_and_make_the_section_web_sourced(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], facts={"2026-06-27": {"transit": FACT}})
    md = section.markdown
    assert section.confidence == "web-sourced"
    assert "**Timetables and directions (web-sourced, not verified in person)**" in md
    assert "metro line 10 to Lago" in md
    assert "Sources: [www.crtm.es](https://www.crtm.es/horarios), [www.metromadrid.es](https://www.metromadrid.es/)" in md
    assert "No timetable or directions" not in md
    assert section.sources == FACT["sources"]


def test_a_fact_without_sources_is_not_used(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO],
                          facts={"2026-06-27": {"transit": {"markdown": "unsourced claim"}}})
    assert "unsourced claim" not in section.markdown and section.confidence == "tag-backed"


@pytest.mark.parametrize("last,severity", [("21:10", "danger"), ("22:40", "caution"), ("23:30", None)])
def test_last_departure_versus_the_estimated_return(make_route_with_points, fixed_now, last, severity):
    import datetime as dt
    fact = dict(FACT, last_departure_local=last)
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], start=dt.time(16, 0), duration=6.5,   # returns 22:30
                          facts={"all": {"transit": fact}})
    got = [w.severity for w in section.warnings]
    assert got == ([severity] if severity else [])
    if severity == "danger":
        assert "last departure (21:10) is before the estimated return at 22:30" in section.warnings[0].text


def test_a_departure_after_midnight_counts_as_the_night_after_the_date(make_route_with_points, fixed_now):
    import datetime as dt
    fact = dict(FACT, last_departure_local="00:20")
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], start=dt.time(16, 0), duration=6.5,
                          facts={"all": {"transit": fact}})
    assert section.warnings == []               # 00:20 the next night is after 22:30


def test_warnings_from_facts_reach_the_section(make_route_with_points, fixed_now):
    fact = dict(FACT, warnings=[{"severity": "caution", "text": "Line 10 is closed for works on Saturdays."}])
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], facts={"all": {"transit": fact}})
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Line 10 is closed for works on Saturdays.")]


def test_russian_output(make_route_with_points, fixed_now):
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], lang="ru", web=Web(overpass=MOSCOW))
    md = section.markdown
    assert "Дата: суббота 2026-06-27 — выходной" in md
    assert "**Точки заброски**" in md and "каждые 30 мин" in md and "автобус" in md


def test_sunrise_bounds_in_line_hours_use_the_light_plugin(make_route_with_points, fixed_now):
    data = {"elements": [{"tags": {"route": "bus", "ref": "N1", "opening_hours": "sunset-sunrise"}}]}
    section = _plugin_run(make_route_with_points, fixed_now, [LAGO], web=Web(overpass=data),
                          light={"sunrise_local_min": 400, "sunset_local_min": 1300})
    assert "yes: 00:00–06:40, 21:40–06:40 (+1)" in section.markdown
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_transit.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan.plugins.transit'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/common.py`:

```python
"""Helpers shared by the transit and poi_hours plugins."""
import urllib.parse

from ..i18n import tr
from ..opening_hours import OpeningResult, evaluate, format_intervals


def cell(text) -> str:
    """Safe content for a Markdown table cell."""
    return " ".join(str(text).replace("|", "/").split())


def sun_from_light(light_shared: dict | None) -> dict | None:
    """{'sunrise': minute, 'sunset': minute} from the light plugin's shared data."""
    if not light_shared or light_shared.get("sunrise_local_min") is None:
        return None
    return {"sunrise": int(light_shared["sunrise_local_min"]), "sunset": int(light_shared["sunset_local_min"])}


def finish_minute(ctx) -> int | None:
    """Estimated end of the route, in minutes after midnight, when both a start time and a duration are known."""
    if ctx.start_time is None or not ctx.duration_hours:
        return None
    return ctx.start_time.hour * 60 + ctx.start_time.minute + int(round(ctx.duration_hours * 60))


def hours_on_date(spec: str | None, ctx, holiday, sun) -> tuple[str, OpeningResult | None]:
    """(text for a table cell, the evaluation or None when OSM has no hours)."""
    lang = ctx.lang
    if not spec:
        return tr("tr_hours_missing", lang), None
    result = evaluate(spec, ctx.date, holiday, sun)
    if result.status == "open_all_day":
        text = tr("tr_hours_all_day", lang)
    elif result.status == "open_hours":
        text = format_intervals(result.intervals)
    elif result.status == "closed":
        text = tr("tr_hours_closed", lang)
    else:
        text = tr("tr_hours_unknown", lang, raw=spec)
    if result.uncertain:
        text += tr("tr_hours_uncertain", lang)
    return cell(text), result


def sources_line(urls: list, lang: str) -> str:
    links = []
    for url in urls:
        host = urllib.parse.urlparse(url).netloc or url
        links.append(f"[{host}]({url})")
    return tr("tr_sources", lang, urls=", ".join(links))
```

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/transit.py`:

```python
"""The "Getting there" section: the route's access points, their hours on the
date, the public-transport lines serving them (OSM, via Overpass), the kind of
day (weekday/holiday), and — when Claude recorded them from the web — the
timetables and directions from the departure point (facts.json, plugin id
"transit"). Confidence: tag-backed for OSM data, web-sourced as soon as a
facts entry is used; no-data when there is neither."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import describe, resolve_day_type
from ..facts import lookup
from ..i18n import tr
from ..opening_hours import evaluate, format_intervals, latest_close
from ..overpass import OverpassError, format_interval, routes_near
from .common import cell, finish_minute, hours_on_date, sources_line, sun_from_light

CLOSING_MARGIN_MIN = 30


def _clock(minute: int) -> str:
    return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"


def _to_minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _return_point(points: list):
    """The access point the person comes back to: the one with role 'end', or
    the only one; None when that is ambiguous (no cross-check is made then)."""
    for point in points:
        if point.role == "end":
            return point
    return points[0] if len(points) == 1 else None


class TransitPlugin(SectionPlugin):
    plugin_id = "transit"
    section_id = "transit"
    depends_on = ("light",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        day = resolve_day_type(ctx)
        sun = sun_from_light(shared.get("light"))
        finish = finish_minute(ctx)
        lines = ["- " + describe(day, ctx)]
        warnings, has_osm = [], False
        return_point = _return_point(ctx.access_points)

        if not ctx.access_points:
            lines.append("- " + tr("tr_no_access_points", lang))
        else:
            rows = [f"| {tr('tr_col_point', lang)} | {tr('tr_col_role', lang)} | {tr('tr_col_hours', lang)} |",
                    "|---|---|---|"]
            for point in ctx.access_points:
                text, result = hours_on_date(point.opening_hours, ctx, day.holiday, sun)
                has_osm = has_osm or result is not None
                role = tr("tr_role_" + point.role, lang) if point.role in ("start", "end") else tr("tr_role_none", lang)
                rows.append(f"| {cell(point.name)} | {role} | {text} |")
                if (point is return_point and finish is not None and result is not None
                        and result.status == "open_hours"):
                    close = latest_close(result)
                    if close is not None and close < finish:
                        warnings.append(PlanWarning("caution", tr(
                            "tr_warn_closed_before_return", lang, name=point.name, close=_clock(close),
                            finish=_clock(finish))))
            lines += ["", tr("tr_access_points", lang), "", *rows]

            route_rows, failed = [], False
            for point in ctx.access_points:
                try:
                    routes = routes_near(ctx, point.lat, point.lon)
                except OverpassError:
                    failed = True
                    continue
                for r in routes:
                    runs = tr("tr_runs_unknown", lang)
                    if r.opening_hours:
                        res = evaluate(r.opening_hours, ctx.date, day.holiday, sun)
                        if res.status in ("open_hours", "open_all_day"):
                            runs = tr("tr_runs_yes", lang, hours=(tr("tr_hours_all_day", lang)
                                                                  if res.status == "open_all_day"
                                                                  else format_intervals(res.intervals)))
                        elif res.status == "closed":
                            runs = tr("tr_runs_no", lang)
                    direction = f"{r.from_} → {r.to}" if r.from_ and r.to else r.name
                    route_rows.append(
                        f"| {cell(point.name)} | {cell(r.ref or r.name)} | {tr('tr_type_' + r.mode, lang)} | "
                        f"{cell(direction)} | {cell(format_interval(r.interval, lang))} | {cell(runs)} |")
            if route_rows:
                has_osm = True
                header = [tr(k, lang) for k in ("tr_col_point", "tr_col_line", "tr_col_type", "tr_col_direction",
                                                "tr_col_interval", "tr_col_runs")]
                lines += ["", tr("tr_routes_title", lang), "",
                          "| " + " | ".join(header) + " |", "|" + "---|" * len(header), *route_rows]
            else:
                lines += ["", "- " + tr("tr_no_osm_lines", lang)]

        fact = lookup(ctx.facts, ctx.date_iso, "transit")
        if fact:
            lines += ["", tr("tr_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
            last_text = fact.get("last_departure_local")
            if last_text and finish is not None:
                last = _to_minutes(last_text)
                if last < 240:          # a departure at 00:30 belongs to the night after this date
                    last += 1440
                if finish > last:
                    warnings.append(PlanWarning("danger", tr("tr_warn_last_departure", lang, last=last_text,
                                                             finish=_clock(finish))))
                elif last - finish < CLOSING_MARGIN_MIN:
                    warnings.append(PlanWarning("caution", tr("tr_warn_last_departure_tight", lang,
                                                              last=last_text, finish=_clock(finish))))
        else:
            lines += ["", "- " + tr("tr_no_web", lang)]

        confidence = "web-sourced" if fact else "tag-backed" if has_osm else "no-data"
        sources = list(fact["sources"]) if fact else []
        return Section("transit", "\n".join(lines), confidence, sources=sources, warnings=warnings)
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (187 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add transit plugin: access-point hours, lines, day type, web facts, return checks

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The points-of-interest plugin

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/poi_hours.py`
- Test: `skills/osm-day-route-day-plan/tests/test_poi_hours.py`

**Interfaces:**
- Consumes: `ctx.interest_points`, `resolve_day_type`, `hours_on_date`, `sources_line`, `sun_from_light`, `cell` (Tasks 2, 4, 6), `lookup`.
- Produces: `PoiHoursPlugin` (`plugin_id="poi_hours"`, `section_id="pois"`, `depends_on=("light",)`). A point closed on the date (and not depending on an unknown holiday) gives a caution; points with neither hours nor a note are only listed by name; notes are cut at 160 characters; pipes become `/`; facts add a labelled web-sourced block, sources and warnings.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_poi_hours.py`:

```python
import datetime
import json

from day_plan.context import build_context
from day_plan.plugins.poi_hours import PoiHoursPlugin

SAT = datetime.date(2026, 6, 27)
SUN = datetime.date(2026, 6, 28)
MON = datetime.date(2026, 6, 29)


class Web:
    def __call__(self, url):
        if "nominatim" in url:
            return {"address": {"country_code": "es"}}
        if "date.nager.at" in url:
            return [{"date": "2026-06-29", "localName": "Fiesta", "name": "Fiesta", "global": True}]
        raise AssertionError(url)


MUSEUM = ("Museo", "sight", -3.74, 40.43, {"opening_hours": "Tu-Su 10:00-18:00", "note": "Free on Sundays"})
CAVE = ("Cueva", "cave", -3.73, 40.44, {"opening_hours": "Mo-Fr 09:00-14:00"})
SPRING = ("Fuente", "spring", -3.72, 40.45, {})
VIEW = ("Mirador", "viewpoint", -3.71, 40.46, {"note": "Best at sunset"})


def _run(make_route_with_points, fixed_now, points, date=SAT, facts=None, lang="en", light=None, folder="proute"):
    route_dir = make_route_with_points(points, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=Web(), now=fixed_now)
    return PoiHoursPlugin().run(ctx, {"light": light} if light else {})


def test_hours_status_and_notes_on_the_date(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM, CAVE, SPRING, VIEW], date=SAT)
    md = section.markdown
    assert section.confidence == "tag-backed" and section.section_id == "pois"
    assert "| Museo | sight | 10:00–18:00 | Free on Sundays |" in md
    assert "| Cueva | cave | closed |  |" in md
    assert "| Mirador | viewpoint | not in OSM | Best at sunset |" in md
    assert "No opening hours in OSM for: Fuente, Mirador." in md


def test_a_closed_point_is_a_caution_and_an_open_one_is_not(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM, CAVE], date=SAT)
    assert [(w.severity, w.text) for w in section.warnings] == [("caution", "Cueva is closed on this date.")]
    monday = _run(make_route_with_points, fixed_now, [MUSEUM], date=MON, folder="monday")   # Monday: the museum is closed
    assert [w.text for w in monday.warnings] == ["Museo is closed on this date."]


def test_holiday_rules_use_the_calendar(make_route_with_points, fixed_now):
    shop = ("Tienda", "sight", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; Su,PH off"})
    on_holiday = _run(make_route_with_points, fixed_now, [shop], date=MON)      # 2026-06-29 is listed as a holiday
    assert "| Tienda | sight | closed |" in on_holiday.markdown
    assert [w.severity for w in on_holiday.warnings] == ["caution"]


def test_a_closure_that_depends_on_an_unknown_holiday_is_not_a_closed_warning(make_route_with_points, fixed_now):
    class NoCountry(Web):
        def __call__(self, url):
            if "nominatim" in url:
                return {"error": "no country"}
            return super().__call__(url)

    shop = ("Tienda", "sight", -3.7, 40.4, {"opening_hours": "Mo-Sa 09:00-21:00; PH off"})
    ctx = build_context(make_route_with_points([shop]), SAT, http=NoCountry(), now=fixed_now)
    section = PoiHoursPlugin().run(ctx, {})
    assert "09:00–21:00 (depends on the public-holiday rule)" in section.markdown
    assert section.warnings == []


def test_no_points_of_interest(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [("Lago", "access", -3.7, 40.4, {})])
    assert section.confidence == "no-data" and "no points of interest" in section.markdown


def test_points_without_hours_or_notes_are_only_listed_by_name(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [SPRING])
    assert section.confidence == "no-data"
    assert "No opening hours in OSM for: Fuente." in section.markdown and "|" not in section.markdown


def test_web_facts_add_special_features_and_warnings(make_route_with_points, fixed_now):
    fact = {"markdown": "The museum closes early on 27 June for a private event.", "sources": ["https://museo.example/agenda"],
            "warnings": [{"severity": "caution", "text": "Museo closes at 14:00 on 27 June."}]}
    section = _run(make_route_with_points, fixed_now, [MUSEUM], facts={"2026-06-27": {"poi_hours": fact}})
    assert section.confidence == "web-sourced"
    assert "closes early on 27 June" in section.markdown and "Sources: [museo.example](https://museo.example/agenda)" in section.markdown
    assert [w.text for w in section.warnings] == ["Museo closes at 14:00 on 27 June."]


def test_a_fact_without_sources_is_ignored(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM], facts={"all": {"poi_hours": {"markdown": "rumour"}}})
    assert "rumour" not in section.markdown


def test_long_notes_are_truncated_and_pipes_are_neutralised(make_route_with_points, fixed_now):
    point = ("Museo", "sight", -3.7, 40.4, {"opening_hours": "Mo-Su 10:00-18:00", "note": "a|b " + "x" * 300})
    row = next(l for l in _run(make_route_with_points, fixed_now, [point]).markdown.splitlines() if l.startswith("| Museo"))
    assert row.count("|") == 5 and row.endswith("… |") and "a/b" in row


def test_sun_bounds_use_the_light_data(make_route_with_points, fixed_now):
    park = ("Parque", "sight", -3.7, 40.4, {"opening_hours": "sunrise-sunset"})
    section = _run(make_route_with_points, fixed_now, [park], light={"sunrise_local_min": 400, "sunset_local_min": 1300})
    assert "| Parque | sight | 06:40–21:40 |" in section.markdown


def test_russian_headers(make_route_with_points, fixed_now):
    section = _run(make_route_with_points, fixed_now, [MUSEUM], lang="ru")
    assert section.markdown.splitlines()[0].startswith("| Точка | Вид | Часы работы в эту дату (OSM) | Примечание |")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_poi_hours.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan.plugins.poi_hours'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/poi_hours.py`:

```python
"""The "Points of interest" section: are the route's points of interest open
on the date (their OSM `opening_hours`), their notes from the route archive,
and — when Claude recorded them from the web — opening days and special
features (facts.json, plugin id "poi_hours"). Confidence like the transit
section: tag-backed for OSM hours, web-sourced once a facts entry is used,
no-data when there is neither."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import resolve_day_type
from ..facts import lookup
from ..i18n import tr
from .common import cell, hours_on_date, sources_line, sun_from_light

NOTE_LIMIT = 160


class PoiHoursPlugin(SectionPlugin):
    plugin_id = "poi_hours"
    section_id = "pois"
    depends_on = ("light",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        day = resolve_day_type(ctx)
        sun = sun_from_light(shared.get("light"))
        lines, warnings, has_osm, without_hours = [], [], False, []

        if not ctx.interest_points:
            lines.append("- " + tr("poi_none", lang))
        else:
            header = [tr(k, lang) for k in ("poi_col_point", "poi_col_type", "poi_col_hours", "poi_col_note")]
            rows = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            for point in ctx.interest_points:
                if not point.opening_hours and not point.note:
                    without_hours.append(point.name)
                    continue
                text, result = hours_on_date(point.opening_hours, ctx, day.holiday, sun)
                if result is None and not point.opening_hours:
                    without_hours.append(point.name)
                has_osm = has_osm or result is not None
                if result is not None and result.status == "closed" and not result.uncertain:
                    warnings.append(PlanWarning("caution", tr("poi_warn_closed", lang, name=point.name)))
                note = point.note or ""
                if len(note) > NOTE_LIMIT:
                    note = note[: NOTE_LIMIT - 1] + "…"
                rows.append(f"| {cell(point.name)} | {cell(point.type)} | {text} | {cell(note)} |")
            if len(rows) > 2:
                lines += rows
            if without_hours:
                lines += ["", "- " + tr("poi_no_hours", lang, names=", ".join(cell(n) for n in without_hours))]

        fact = lookup(ctx.facts, ctx.date_iso, "poi_hours")
        if fact:
            lines += ["", tr("poi_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))

        confidence = "web-sourced" if fact else "tag-backed" if has_osm else "no-data"
        sources = list(fact["sources"]) if fact else []
        return Section("pois", "\n".join(lines), confidence, sources=sources, warnings=warnings)
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (198 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add points-of-interest plugin: opening hours on the date, notes, web facts

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `record_fact.py` and the CLI

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/record_fact.py`
- Modify: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`, `skills/osm-day-route-day-plan/tests/test_cli.py`
- Test: `skills/osm-day-route-day-plan/tests/test_record_fact.py`

**Interfaces:**
- Consumes: `normalize_entry`, `DAY_TYPES` (Task 2), `SEVERITIES`, both plugins.
- Produces: `record_fact.record(route_dir, date, plugin, markdown, sources, last_departure=None, first_departure=None, warnings=None, day_type=None) -> dict` (raises `ValueError` with a readable reason; merges into `facts.json`, replaced atomically, an unparsable or non-object file is never overwritten) and its CLI `main(argv) -> int`; `build_day_plan.default_plugins()` returns weather, light, transit, poi_hours; `missing_web_facts(ctx)`; the CLI prints a `hint:` line naming the sections that still lack web facts for the date. The written file header gains `<!-- plugins: weather 1, light 1, transit 1, poi_hours 1 -->`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_record_fact.py`:

```python
import json

import pytest

import record_fact
from day_plan.facts import load_facts, lookup

URL = "https://www.crtm.es/horarios"


def _run(route_dir, *args):
    return record_fact.main([str(route_dir), *args])


def test_records_a_fact_that_the_plan_can_read_back(tmp_path, capsys):
    code = _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "Bus 41 every 20 min.",
                "--source", URL, "--source", "https://metromadrid.es", "--last-departure", "23:10",
                "--warning", "caution:Line 10 closed for works")
    assert code == 0 and "recorded transit for 2026-06-27 (2 source(s))" in capsys.readouterr().out
    entry = lookup(load_facts(tmp_path), "2026-06-27", "transit")
    assert entry["markdown"] == "Bus 41 every 20 min." and entry["last_departure_local"] == "23:10"
    assert entry["warnings"] == [{"severity": "caution", "text": "Line 10 closed for works"}]
    assert entry["sources"] == [URL, "https://metromadrid.es"]


def test_later_facts_are_merged_not_overwritten(tmp_path):
    _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "general", "--source", URL)
    _run(tmp_path, "--date", "2026-06-27", "--plugin", "poi_hours", "--markdown", "museum", "--source", URL)
    _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "specific", "--source", URL)
    facts = json.loads((tmp_path / "facts.json").read_text(encoding="utf-8"))
    assert facts["all"]["transit"]["markdown"] == "general"
    assert facts["2026-06-27"]["poi_hours"]["markdown"] == "museum"
    assert facts["2026-06-27"]["transit"]["markdown"] == "specific"


def test_markdown_can_come_from_a_file(tmp_path):
    (tmp_path / "note.md").write_text("From a file, with ünïcode.", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown-file", str(tmp_path / "note.md"),
                "--source", URL) == 0
    assert "ünïcode" in (tmp_path / "facts.json").read_text(encoding="utf-8")   # not escaped to ü


def test_calendar_fact_needs_only_a_day_type_and_a_source(tmp_path):
    assert _run(tmp_path, "--date", "2026-05-11", "--plugin", "calendar", "--day-type", "holiday",
                "--source", "https://www.consultant.ru/x") == 0
    assert lookup(load_facts(tmp_path), "2026-05-11", "calendar")["day_type"] == "holiday"


@pytest.mark.parametrize("args,reason", [
    (["--date", "2026-06-27", "--plugin", "transit", "--markdown", "no source"], "at least one http(s) --source"),
    (["--date", "2026-06-27", "--plugin", "transit", "--markdown", "x", "--source", "ftp://x"], "at least one http(s)"),
    (["--date", "2026-06-27", "--plugin", "transit", "--source", URL], "non-empty text"),
    (["--date", "27-06-2026", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "all", "--plugin", "weather", "--markdown", "x", "--source", URL], "unknown plugin"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--last-departure", "late"], "bad last_departure_local"),
    (["--date", "all", "--plugin", "calendar", "--day-type", "funday", "--markdown", "x", "--source", URL], "bad day type"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--warning", "mystery:oops"], "bad warning"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--warning", "no separator"], "bad warning"),
])
def test_invalid_facts_are_refused_and_nothing_is_written(tmp_path, capsys, args, reason):
    assert _run(tmp_path, *args) == 1
    assert reason in capsys.readouterr().err
    assert not (tmp_path / "facts.json").exists()


def test_an_unparsable_facts_file_is_never_overwritten(tmp_path, capsys):
    (tmp_path / "facts.json").write_text("{broken", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert (tmp_path / "facts.json").read_text(encoding="utf-8") == "{broken"


def test_a_non_object_facts_file_is_never_overwritten(tmp_path, capsys):
    (tmp_path / "facts.json").write_text("[1, 2]", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 1
    assert (tmp_path / "facts.json").read_text(encoding="utf-8") == "[1, 2]"


def test_a_scope_that_is_not_an_object_is_replaced_safely(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({"all": ["junk"]}), encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 0
    assert lookup(load_facts(tmp_path), "2026-06-27", "transit")["markdown"] == "x"


def test_no_temporary_file_is_left_behind(tmp_path):
    _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL)
    assert [p.name for p in tmp_path.iterdir()] == ["facts.json"]


def test_bad_arguments(tmp_path, capsys):
    assert record_fact.main([str(tmp_path / "missing"), "--date", "all", "--plugin", "transit"]) == 1
    assert "is not a directory" in capsys.readouterr().err
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "a", "--markdown-file", "b") == 1
    assert "not both" in capsys.readouterr().err
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown-file", str(tmp_path / "nope.md"),
                "--source", URL) == 1
```

Append to the end of `skills/osm-day-route-day-plan/tests/test_cli.py`:

````python
# ---- plan 2: transit and points-of-interest sections, web-fact hints ------------------------------

def _web(weather_response, date="2026-06-21"):
    def http(url):
        if "nominatim" in url:
            return {"address": {"country_code": "es"}}
        if "date.nager.at" in url:
            return []
        if "overpass" in url:
            return {"elements": [{"tags": {"route": "bus", "ref": "41", "from": "Atocha", "to": "Colonia"}}]}
        return weather_response(date=date)
    return http


def _route_with_points(make_route_with_points):
    return make_route_with_points([
        ("Lago", "access", -3.7275, 40.4247, {"role": "start", "opening_hours": "Mo-Su 06:00-23:00"}),
        ("Museo", "sight", -3.74, 40.43, {"opening_hours": "Tu-Su 10:00-18:00"}),
    ])


def test_default_plan_has_getting_there_and_points_of_interest(make_route_with_points, weather_response, fixed_now):
    route_dir = _route_with_points(make_route_with_points)
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Summary", "## Daylight", "## Weather by hour", "## Getting there", "## Points of interest"]
    assert "| Lago | start |" in text and "| Museo | sight | 10:00–18:00 |" in text and "| Lago | 41 | bus |" in text
    assert "<!-- plugins: weather 1, light 1, transit 1, poi_hours 1 -->" in text


def test_hint_asks_for_web_facts_until_they_are_recorded(make_route_with_points, weather_response, fixed_now, capsys):
    route_dir = _route_with_points(make_route_with_points)
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit, poi_hours on 2026-06-21" in out and "record_fact.py" in out

    import record_fact
    for plugin in ("transit", "poi_hours"):
        record_fact.record(route_dir, "2026-06-21", plugin, "Found on the web.", ["https://example.org/x"])
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
    out2 = capsys.readouterr().out
    assert "hint:" not in out2
    assert "Found on the web." in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")


def test_hint_mentions_only_what_the_route_needs(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()                        # a route without points of interest
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), now=fixed_now)
    assert "recorded for transit on" in capsys.readouterr().out


def test_a_broken_overpass_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now):
    from day_plan.http import HttpError
    route_dir = _route_with_points(make_route_with_points)
    inner = _web(weather_response)

    def http(url):
        if "overpass" in url:
            raise HttpError("504")
        return inner(url)

    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=http, now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "OSM lists no lines for these access points" in text and "## Points of interest" in text
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_record_fact.py tests/test_cli.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'record_fact'`; the new CLI tests fail because the plan has no "Getting there" section yet).

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/record_fact.py`:

```python
#!/usr/bin/env python3
"""Record one web-sourced fact for a day plan in <route_dir>/facts.json.

Standard-library only. Usage:
    python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar>
        (--markdown TEXT | --markdown-file PATH) --source URL [--source URL ...]
        [--last-departure HH:MM] [--first-departure HH:MM]
        [--warning danger|caution|info:TEXT ...] [--day-type holiday|weekend|workday]

Every fact needs at least one http(s) source: an entry without one is refused
(and would be ignored when the plan is built). The text ends up in
day-plan-<date>.md, which is embedded in map.html and meant to be forwarded:
write places at city, station or stop level, never a street address, phone
number or anything personal. The file is replaced atomically; a facts.json
that is not valid JSON is never overwritten."""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from day_plan.base import SEVERITIES
from day_plan.facts import DAY_TYPES, normalize_entry

PLUGINS = ("transit", "poi_hours", "calendar")


def record(route_dir, date: str, plugin: str, markdown: str, sources: list, last_departure: str | None = None,
           first_departure: str | None = None, warnings: list | None = None, day_type: str | None = None) -> dict:
    """Validates and stores the fact; returns the stored entry. Raises ValueError with a readable reason."""
    if plugin not in PLUGINS:
        raise ValueError(f"unknown plugin {plugin!r} (use one of: {', '.join(PLUGINS)})")
    if date != "all":
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ValueError(f"bad date {date!r}: use YYYY-MM-DD or 'all'") from None
    entry = {"markdown": markdown, "sources": sources}
    for key, value in (("last_departure_local", last_departure), ("first_departure_local", first_departure),
                       ("day_type", day_type)):
        if value is not None:
            entry[key] = value
    if warnings:
        entry["warnings"] = warnings
    clean = normalize_entry(entry)
    if clean is None:
        raise ValueError("refused: a fact needs a non-empty text (or --day-type) and at least one http(s) --source")
    for key in ("last_departure_local", "first_departure_local"):
        if key in entry and key not in clean:
            raise ValueError(f"bad {key}: use HH:MM")
    if day_type is not None and "day_type" not in clean:
        raise ValueError(f"bad day type {day_type!r}: use one of {', '.join(DAY_TYPES)}")
    if warnings and len(clean.get("warnings", [])) != len(warnings):
        raise ValueError("bad warning: use severity:text with severity one of " + ", ".join(SEVERITIES))

    path = Path(route_dir) / "facts.json"
    facts = {}
    if path.exists():
        try:
            facts = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix or remove it first — it was not changed") from None
        if not isinstance(facts, dict):
            raise ValueError(f"{path} does not hold a JSON object; fix or remove it first — it was not changed")
    scope = facts.get(date)
    if not isinstance(scope, dict):
        scope = facts[date] = {}
    scope[plugin] = clean
    fd, tmp = tempfile.mkstemp(dir=str(Path(route_dir)), prefix=".facts-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(facts, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return clean


def _parse_warning(text: str) -> dict:
    severity, _, body = text.partition(":")
    return {"severity": severity.strip(), "text": body.strip()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("route_dir")
    parser.add_argument("--date", required=True)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--markdown", default=None)
    parser.add_argument("--markdown-file", default=None)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--last-departure", default=None)
    parser.add_argument("--first-departure", default=None)
    parser.add_argument("--warning", action="append", default=[])
    parser.add_argument("--day-type", default=None)
    args = parser.parse_args(argv)
    if not Path(args.route_dir).is_dir():
        print(f"error: {args.route_dir} is not a directory", file=sys.stderr)
        return 1
    if args.markdown is not None and args.markdown_file is not None:
        print("error: use --markdown or --markdown-file, not both", file=sys.stderr)
        return 1
    try:
        markdown = args.markdown if args.markdown is not None else (
            Path(args.markdown_file).read_text(encoding="utf-8") if args.markdown_file else "")
        record(args.route_dir, args.date, args.plugin, markdown, args.source, args.last_departure,
               args.first_departure, [_parse_warning(w) for w in args.warning], args.day_type)
    except (ValueError, OSError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"recorded {args.plugin} for {args.date} ({len(args.source)} source(s)) in "
          f"{Path(args.route_dir).resolve() / 'facts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In `skills/osm-day-route-day-plan/scripts/build_day_plan.py`:

**Replace:**

```python
from day_plan.context import build_context
from day_plan.http import get_json
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import build_plan


def default_plugins() -> list:
    return [WeatherPlugin(), LightPlugin()]

```

**With:**

```python
from day_plan.context import build_context
from day_plan.facts import lookup
from day_plan.http import get_json
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.poi_hours import PoiHoursPlugin
from day_plan.plugins.transit import TransitPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import build_plan


def default_plugins() -> list:
    return [WeatherPlugin(), LightPlugin(), TransitPlugin(), PoiHoursPlugin()]


def missing_web_facts(ctx) -> list:
    """Plugin ids whose web-sourced facts Claude has not recorded yet for this date."""
    wanted = ["transit"] + (["poi_hours"] if ctx.interest_points else [])
    return [pid for pid in wanted if lookup(ctx.facts, ctx.date_iso, pid) is None]

```

**Replace:**

```python
    for plugin_id, reason in result.failures:
        print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
    return 0
```

**With:**

```python
    for plugin_id, reason in result.failures:
        print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
    missing = missing_web_facts(ctx)
    if missing:
        print(f"hint: no web-sourced facts recorded for {', '.join(missing)} on {date.isoformat()}: search the "
              f"web (timetables, directions from the departure point, opening days), record what you find with "
              f"record_fact.py, then run this command again")
    return 0
```


- [ ] **Step 4: Run the suite to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (220 passed: everything above plus the record-fact tests and the four new CLI tests).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add record_fact.py and register transit and points-of-interest plugins in the CLI

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Documentation

**Files:**
- Replace: `skills/osm-day-route-day-plan/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: Rewrite the skill document**

Replace the whole file `skills/osm-day-route-day-plan/SKILL.md` with:

````markdown
---
name: osm-day-route-day-plan
description: Use when the user wants a briefing for a specific date for a route already saved by osm-day-route-planning (a routes/<slug>-<date>/ folder with route.geojson) — sunrise/sunset and daylight, hourly weather (wind speed and direction, precipitation, temperature, cloud/fog, snow cover), how to get to the access points and whether the buses/metro run and the points of interest are open on that date (weekday, weekend, public holiday) — or asks "what will the weather/daylight be on <date>", "до скольки ходит автобус", "открыт ли музей", "план на день", "когда рассвет и закат", "погода по часам".
---

# OSM Day Route Day Plan

## Overview

Turns a saved route plus a date into `day-plan-<YYYY-MM-DD>.md` in the route
folder. `osm-day-route-show` embeds every such file into `map.html` (sidebar
summary, full-plan panel, `.md` download, print to PDF), so the single map
file can be forwarded with all planned days inside.

Design: `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`.
The plan has these sections, always in this order:

1. **Summary** — the highest-severity warnings of every section.
2. **Daylight** — sunrise, sunset, day length, margin to the route's finish.
3. **Weather by hour** — Open-Meteo, with wind speed, direction and gusts.
4. **Getting there** — the kind of day (weekday / weekend / public holiday),
   the access points and their OSM hours on the date, the public-transport
   lines serving them (OSM), and — from `facts.json` — timetables and
   directions from the departure point.
5. **Points of interest** — open or closed on the date (OSM hours), notes
   from the route archive, and — from `facts.json` — opening days and special
   features.

Hazards (ticks, biting insects, mountains, air, radiation, fire) and mobile
coverage are separate follow-up plans; until they exist the plan simply has
no such sections — never invent them by hand.

Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
keys, same rule as the other two skills. Sources: Open-Meteo (weather),
Overpass (lines through the access points; mirrors and one retry, because the
public servers answer 429/504 under load), Nominatim (the route's country,
asked once per route and remembered) and Nager.Date (public holidays).

## When to Use

- A route exists in `routes/` and the user names a date (or asks about
  "tomorrow", "Saturday" — convert to `YYYY-MM-DD` first).
- The user asks for sunrise/sunset, day length, hourly weather, how to reach
  the start, whether the last bus/metro fits the return, or whether a point of
  interest is open.

**Not for:** planning or changing the route (osm-day-route-planning),
showing it on a map (osm-day-route-show), astronomical events (not covered),
live navigation, multi-day plans.

## How to Use

1. Find the route folder and the date. Ask if either is unclear.
2. **Departure point:** ask only if it is not already in the conversation or
   the route's `notes.md`. Write it at **city / station / stop level** — the
   plan is embedded in `map.html`, a file meant to be forwarded, so never a
   street address. The script drops any `--departure` containing digits and
   says so on stderr.
3. Optional `--start HH:MM` if the person gave a start time; without it the
   plan reports the latest start that still ends 60 minutes before sunset, and
   no return-time checks against buses or opening hours are made (they need
   the estimated finish).
4. Run (from this skill's `scripts/` directory):
   ```bash
   python3 build_day_plan.py <route_dir> <YYYY-MM-DD> \
       --lang <ISO 639-1 of the person's language> \
       [--departure "<city or station>"] [--start HH:MM]
   ```
   Re-running for the same date overwrites that date's file; other dates are
   kept. Network results are cached in `<route_dir>/day_plan_cache.json`
   (forecasts 3 hours, Overpass lines 7 days, holiday lists 30 days, the
   route's country for good).
5. **Web facts.** The script ends with a `hint:` line for every section that
   has no web-sourced facts for the date. Then search the web for what OSM
   cannot tell (see **Recording facts** below), record each finding with
   `record_fact.py`, and run step 4 again. Skip only what the person did not
   ask about; a section without facts says so plainly, which is honest.
6. Report the file path and read the **Summary** section back to the person.
   If the plan shows the route does not fit the day (finish after sunset,
   thunderstorm, last bus before the return, a point closed), say so and offer
   to go back to osm-day-route-planning — this skill never changes the route.
7. Offer to re-render the map so the new date is inside it:
   `python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang <code>`.
   A `map.html` is a snapshot; a plan added later does not appear until it is
   re-rendered. Tell the person which dates the map will contain.

## Recording facts

Web-sourced material goes into `<route_dir>/facts.json` through the helper —
never by hand-editing JSON:

```bash
python3 record_fact.py <route_dir> --date <YYYY-MM-DD|all> --plugin <transit|poi_hours|calendar> \
    --markdown "text" | --markdown-file note.md \
    --source https://... [--source https://...] \
    [--last-departure HH:MM] [--first-departure HH:MM] \
    [--warning caution:"text"] [--day-type holiday|weekend|workday]
```

- `--plugin transit`: timetables and **directions from the departure point**
  (which train/metro/bus, how long, where to change), frequencies on that
  weekday/holiday. `--last-departure` is the last bus/train/metro *back from
  the route's end point*, as local `HH:MM` (a departure after midnight, like
  `00:20`, is read as the night after the date): the plan compares it with the
  estimated return and warns (danger if the return is later, caution if the
  margin is under 30 minutes). Use `--warning` for anything the person must
  see in the Summary (works, replacement buses, closed stations).
- `--plugin poi_hours`: opening days and special features of the points of
  interest for that date (closed for an event, free days, reservations).
- `--plugin calendar` with `--day-type`: the real kind of day when the free
  holiday list is wrong. **For Russia and neighbouring countries always check
  the date** (official calendar, `consultant.ru` or similar): the free list
  is incomplete for Russia: it misses 8 January and the transferred days off
  (for example 9 March and 11 May 2026), and working Saturdays are not marked.
  Record `holiday`, `weekend`
  or `workday`; it overrides the list and feeds the opening-hours rules (`PH`).
- Every fact needs at least one `http(s)` source, or it is refused (and, if
  found in the file, ignored). Say only what the source says.
- **Privacy:** facts end up in `day-plan-<date>.md`, embedded in a `map.html`
  meant to be forwarded. Places at city, station or stop level only — never a
  street address, phone number or anything personal.
- `--date all` applies to every date without a dated entry; a dated entry wins.

## Confidence and honesty

Sections carry a tier like the rest of the project. Light and weather are
`derived` (computed / model output). Hours and lines taken from OSM are
`tag-backed`; anything from `facts.json` is `web-sourced` (unverified in
person) and is labelled as such in the text, with its sources. A section that
could not be built says `no data`. OSM rarely carries schedules: lines through
a stop usually have no `interval` or `opening_hours`, so expect "not stated in
OSM" and rely on recorded web facts for timetables.

A forecast is only as good as its horizon: beyond 15 days the weather table is
a **climatology** (average of the same date over five previous years) and says
so in the file.

`opening_hours` is read for the syntax real data uses (weekday lists and
ranges, several time ranges, overnight ranges, `24:00`, `19:30+`, `off`,
`24/7`, `PH`, months, `sunrise`/`sunset`). Anything else (`SH`, `week`,
point dates like `Jan 01`, quoted comments) is shown verbatim as "not read" —
never guessed. Public-holiday rules (`PH`) are marked "depends on the
public-holiday rule" when the holiday status is unknown.

## Limitations

- Body text of the sections is translated for English and Russian; other
  languages get English body text (headings, metadata and severity labels are
  localized in all seven languages).
- Open-Meteo applies no elevation correction to wind: ridge gusts are likely
  underestimated.
- Weekends are Saturday and Sunday; countries with another weekend are not
  handled.
- Pollen, radiation, fire danger, insects, mountain hazards and mobile
  coverage are not in this version.

## Common Mistakes

- Writing a street address as the departure point or in a fact (it ends up in
  a forwarded file).
- Trusting the holiday list for Russia without checking the date.
- Recording a fact without reading its source, or a last departure for the
  wrong direction (it must be the departure *back* from the end point).
- Editing `day-plan-*.md` by hand and forgetting that re-running the script
  overwrites the file.
- Editing `facts.json` by hand (use `record_fact.py`: it validates, refuses
  source-less facts and never overwrites a file it cannot parse).
- Forgetting to re-render `map.html` after adding a plan.
````

- [ ] **Step 2: Update the README**

In `README.md`:

**Replace:**

```python
| `osm-day-route-day-plan` | For a saved route and a date, writes a day plan: sunrise, sunset, daylight, hourly weather. Needs a route from the planning skill. |
```

**With:**

```python
| `osm-day-route-day-plan` | For a saved route and a date, writes a day plan: sunrise, sunset, daylight, hourly weather, how to get to the access points, and whether the lines and points of interest work that day. Needs a route from the planning skill. |
```

**Replace:**

```python
- **Weather by hour:** temperature and feels-like, precipitation and its probability, cloud cover, visibility, **wind speed and the direction it blows from**, gusts, snow cover, and a plain-language sky description.

```

**With:**

```python
- **Weather by hour:** temperature and feels-like, precipitation and its probability, cloud cover, visibility, **wind speed and the direction it blows from**, gusts, snow cover, and a plain-language sky description.
- **Getting there:** what kind of day it is (weekday, weekend, public holiday), the opening hours of your access points on that date, the bus / train / metro lines that stop there (from OpenStreetMap, which rarely has schedules), and — when Claude has looked them up on the web and recorded them with sources — timetables and directions from where you start. If the last departure home is before your estimated return, the summary says so.
- **Points of interest:** whether each one is open on that date (from its OpenStreetMap opening hours), your notes, and web-sourced opening days and special features when recorded.

```

**Replace:**

```python
- This is the first version: daylight, weather and the summary. Transit and opening hours, hazards (ticks, mosquitoes, mountains, air, radiation, fire) and mobile coverage are planned next.
```

**With:**

```python
- Everything that comes from the web rather than from OpenStreetMap is labelled *web-sourced* and carries its sources; a fact without a source is refused. For Russia and its neighbours, Claude checks the date against the official calendar, because the free holiday list misses transferred days off.
- Hazards (ticks, mosquitoes, mountains, air, radiation, fire) and mobile coverage are planned next.
```

**Replace:**

```python
| `day-plan-<YYYY-MM-DD>.md` | A day plan for one date (daylight, hourly weather). One file per planned date. |
```

**With:**

```python
| `day-plan-<YYYY-MM-DD>.md` | A day plan for one date (daylight, hourly weather, transport, opening hours). One file per planned date. |
| `facts.json` | Web-sourced facts Claude recorded for your day plans (timetables, directions, opening days), each with its sources. |
```


- [ ] **Step 3: Run every suite**

```bash
(cd skills/osm-day-route-day-plan && python3 -m pytest tests -q)
(cd skills/osm-day-route-show && python3 -m pytest tests -q)
(cd skills/osm-day-route-planning && python3 -m pytest tests -q)
```

Expected: all pass (the show and planning suites are unchanged: 139 and 139).

- [ ] **Step 4: Commit**

```bash
git add skills/osm-day-route-day-plan/SKILL.md README.md
git commit -m "Document transit, opening hours and the facts workflow

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Live smoke test with real services

No code: this task is the check that the earlier per-task reviews cannot make (in plan 1 the real defects were found by real-browser and real-data checks, not by reading diffs).

- [ ] **Step 1: Two routes, real services (needs internet)**

In a scratch folder (not in the repository) create two folders with a minimal `route.geojson` each (a `LineString` with `name`, `mode`, `duration_estimate_hours`, plus `Point` features): one around Casa de Campo, Madrid (access point `Lago (metro)`, `type: access`, `role: start`, `opening_hours: Mo-Su 06:00-01:30`, a sight with `opening_hours: Tu-Su 10:00-18:00` and a `note`, a spring without hours), one in Yekaterinburg (an access point `Динамо (метро)` with `opening_hours: Mo-Su 05:30-00:00`, a sight with only a `note`). Run for a Saturday within two weeks, with a start time:

```bash
cd skills/osm-day-route-day-plan/scripts
python3 build_day_plan.py <madrid-folder> <YYYY-MM-DD> --lang en --departure "Madrid" --start 09:00
python3 build_day_plan.py <ekb-folder> <YYYY-MM-DD> --lang ru --departure "Екатеринбург" --start 10:00
python3 record_fact.py <ekb-folder> --date <YYYY-MM-DD> --plugin transit \
    --markdown "От центра: метро до станции «Динамо». Обратно — автобусы до 23:30." \
    --source https://example.org/transport --last-departure 23:30
python3 build_day_plan.py <ekb-folder> <YYYY-MM-DD> --lang ru --departure "Екатеринбург" --start 10:00
```

Expected: both plans have `## Getting there` and `## Points of interest`; the date line says weekend and names the source (`Nager.Date, ES` / `RU`, with the Russian caveat); the Madrid access-point row reads `00:00–01:30, 06:00–01:30 (+1)`; the Madrid lines table lists buses 41 and 75 with `not stated in OSM`; the museum row reads `10:00–18:00`; the second Yekaterinburg run shows the recorded fact with its source link and no `transit` hint. Verified when this plan was written (2026-09-29, date 2026-10-03).

- [ ] **Step 2: The map, in a real browser**

Render each folder with `osm-day-route-show/scripts/render_map.py`, open the page (headless Chromium over a file inside your home directory works; the snap build cannot read private `/tmp`), click "Open full plan" and confirm the panel shows the new tables (3 tables for Yekaterinburg, 4 for Madrid), the bold sub-titles, the source link, and the download name `<route>-day-plan-<date>.md`. Verified when this plan was written.

- [ ] **Step 3: Failure modes**

Run once with no network (or `--departure` only): the plan must still be written, each network-dependent part degrading to a note (`OSM lists no lines ...`, `public-holiday status unknown (...)`), and the CLI must not hang: an all-mirror Overpass failure costs at most one 3-second pause.

---

## Self-Review Notes

- **Spec coverage:** transit (hours from OSM, lines from Overpass, weekday/holiday, web timetables, return checks) — Tasks 4, 5, 6; poi_hours (evaluator, notes, facts) — Tasks 3, 7; `facts.json` schema, sources-required rule and `record_fact.py` — Tasks 2, 8; privacy for facts — Global Constraints and SKILL.md; the five carried-over items — Task 1. Deliberately not here: hazards and mobile coverage (plan 3); a `notes.md` parser (the same information reaches the plan from `route.geojson` point properties `note`, `access_notes`, `opening_hours`).
- **Deviations from the spec text, decided with evidence:** the spec's "Overpass for access-point hours" is narrowed to lines through the stop, because the hours tags are already stored in `route.geojson` by the planning skill; holidays come from Nager.Date with a web-sourced override because the free list is incomplete for Russia.
- **Cross-plan contract:** plugin ids `transit`, `poi_hours`, `calendar` are the keys of `facts.json`; section ids `transit` and `pois` are the `SECTION_ORDER` slots reserved in plan 1; `osm-day-route-show` needs no change.
