# Day Plan — Core (light, weather, summary, map embedding) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the new `osm-day-route-day-plan` skill with its core — plugin orchestrator, daylight and hourly-weather sections, summary, `day-plan-<date>.md` output — and make `osm-day-route-show` embed every day plan in `map.html` (sidebar summary, full-plan panel, `.md` download, print to PDF).

**Architecture:** A `day_plan` package mirrors `place_info/` and `tile_providers/`: a `SectionPlugin` interface, a service that runs plugins in dependency order with per-plugin fault isolation, and an assembler that writes fixed-order Markdown. Light (local NOAA solar math) and weather (Open-Meteo) are the first two plugins; the summary is built after them from their warnings. The show skill gains a small `day_plan_view` module and a whole-file Markdown converter, and inlines every plan into the page so the file is self-contained.

**Tech Stack:** Python 3.10+ standard library only (`urllib`, `json`, `zoneinfo`, `argparse`), pytest, inline JS/CSS in the generated HTML.

**Spec:** `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`

**Scope note:** the spec covers about ten plugins. This is plan 1 of 3. Plan 2 will add transit and points-of-interest opening hours (uses `facts.json`, already loadable here via `day_plan.facts`). Plan 3 will add the hazards group (ticks and biting insects, mountain, people, air, radiation, fire) and mobile coverage. This plan reserves their headings and `SECTION_ORDER` slots so plans 2 and 3 only register plugins.

## Global Constraints

- Every script is **standard-library only**; no `requests`, no third-party HTTP client; Python 3.10 or newer.
- **No API key is required** for anything in this plan (Open-Meteo forecast and archive are free and keyless).
- Every claim carries a confidence tier: `tag-backed`, `web-sourced`, `derived`, `no-data`. A missing datum is `no-data`, never invented.
- The plan file is `day-plan-<YYYY-MM-DD>.md` in the route folder; re-running a date overwrites that date only; other dates are untouched.
- Section order in the file is fixed: Summary, Daylight, Weather by hour, then (later plans) Getting there, Points of interest, Hazards, Mobile coverage. Headings are localized in `en`, `ru`, `es`, `fr`, `de`, `pt`, `it`.
- The departure point is recorded at **city, station or stop level only**, never a street address, because the plan is embedded in `map.html`, a file meant to be forwarded.
- Only sunrise, sunset and day length: **no astronomical events** (twilight tables, moon, eclipses, meteors).
- Weather source by date: today+15 days and earlier (down to today-7 days) use the forecast API; older dates use the archive; later than today+15 days use climatology (the average of the same date over the last 5 years) and must say it is not a forecast. Forecast cache lifetime is 3 hours.
- Wind direction is reported as the direction the wind blows **from**; wind speed is in m/s.
- `map.html` embeds **every** `day-plan-*.md` of the route folder with no external file needed; PDF is produced by the browser's print (`window.print()`), no PDF library.
- Tests never use the live network.

## Review Focus

Inputs the spec implies that no headline task exercises, most likely first; each has a test in the task that owns the code.

1. A route that crosses the antimeridian (Chukotka, Wrangel Island): the naive bbox centre lands near 0° longitude and gives the wrong sun times. Expected: centre near ±180°. (Task 1)
2. A weather response with wind speed but no wind direction: the table must still render the speed, not crash. (Task 4)
3. A daylight-saving change day where the API returns 23 hourly rows: the plan must build. (Task 4)
4. A plan file that was hand-edited and saved with a BOM and CRLF line endings: it must load with a clean first heading. (Task 7)
5. Plan text containing `</script>` or HTML: it must not break the page or inject markup. (Tasks 7, 8, 9)

Also covered: a `--departure` containing digits (probably a street address) is dropped with a warning (Task 6); Open-Meteo's `utc_offset_seconds` reports the moment of the request, not the requested date, so the offset is taken from the zone name (Task 4).

---

## File Structure

New skill `skills/osm-day-route-day-plan/`:

| File | Responsibility |
|---|---|
| `SKILL.md` | How the agent uses the skill. |
| `scripts/build_day_plan.py` | CLI: route folder + date -> `day-plan-<date>.md`. |
| `scripts/day_plan/base.py` | `PlanWarning`, `Section`, `SectionPlugin`, `SECTION_ORDER`. |
| `scripts/day_plan/context.py` | `PlanContext` and `build_context` (reads `route.geojson`). |
| `scripts/day_plan/http.py` | `get_json` (stdlib) and `HttpError`. |
| `scripts/day_plan/cache.py` | `JsonCache` with optional max age. |
| `scripts/day_plan/facts.py` | `load_facts`, `lookup` for `facts.json` (used by plan 2). |
| `scripts/day_plan/i18n.py` | Strings in seven languages, `tr`, `compass`. |
| `scripts/day_plan/sun.py` | Pure NOAA sunrise/sunset math. |
| `scripts/day_plan/plugins/light.py` | Daylight section and margin warnings. |
| `scripts/day_plan/plugins/weather.py` | Open-Meteo hourly weather section and warnings. |
| `scripts/day_plan/summary.py` | Summary section from all warnings. |
| `scripts/day_plan/service.py` | Ordering, fault isolation, Markdown assembly. |
| `tests/conftest.py`, `tests/test_*.py` | Fixtures and tests. |

Changed in `skills/osm-day-route-show/`: `scripts/day_plan_view.py` (new), `scripts/render_map.py` (wiring + `plan_markdown_to_html`), `tests/test_day_plan_view.py`, `tests/test_plan_markdown_to_html.py`, `tests/test_day_plan_embed.py` (new), `SKILL.md` (docs). Also `README.md`.

All commands below are run from the repository root unless a `cd` is shown.

---

### Task 1: Foundation — types, i18n, HTTP, cache, facts, context

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/__init__.py`, `base.py`, `http.py`, `cache.py`, `facts.py`, `context.py`, `i18n.py`
- Create: `skills/osm-day-route-day-plan/tests/conftest.py`, `skills/osm-day-route-day-plan/tests/test_foundation.py`

**Interfaces:**
- Produces: `PlanWarning(severity, text)`; `Section(section_id, markdown, confidence, sources, warnings, shared, title)`; `SectionPlugin` (`plugin_id`, `section_id`, `depends_on`, `run(ctx, shared) -> Section`); `SECTION_ORDER`; `JsonCache(path, now).get_entry(key, max_age) -> (value, stored_at) | None`, `.put(key, value) -> stored_at`; `get_json(url, timeout) -> dict` raising `HttpError`; `load_facts(route_dir)`, `lookup(facts, date_iso, plugin_id)`; `tr(key, lang, **fmt)`, `compass(degrees, lang)`; `PlanContext` and `build_context(route_dir, date, lang, departure, start_time, http, cache, now) -> PlanContext` (fields: `route_dir, date, lang, departure, start_time, mode, route_name, coords, distance_km, duration_hours, centroid=(lat, lon), facts, http, cache, now, today, date_iso`).

- [ ] **Step 1: Write the fixtures and the failing tests**

`skills/osm-day-route-day-plan/tests/conftest.py`:

```python
import datetime
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def block_real_network():
    """No test may touch the network. Tests pass a fake `http` callable via
    the context; a test of the real helper patches day_plan.http._open
    itself, which takes precedence over this outer patch."""
    with patch("day_plan.http._open", side_effect=RuntimeError("real network access attempted in tests")):
        yield


@pytest.fixture
def make_route(tmp_path):
    """Writes a minimal route.geojson (London-ish, 3D coords) and returns the folder."""
    def _make(name="Test route", mode="walk", duration_hours=5.0, distance_km=15.0,
              coords=((-0.20, 51.45, 30.0), (-0.05, 51.55, 60.0)), folder="route"):
        route_dir = tmp_path / folder
        route_dir.mkdir()
        geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
            "properties": {"name": name, "mode": mode, "distance_km": distance_km,
                           "duration_estimate_hours": duration_hours},
        }]}
        (route_dir / "route.geojson").write_text(json.dumps(geojson), encoding="utf-8")
        return route_dir
    return _make


@pytest.fixture
def weather_response():
    """Factory for an Open-Meteo hourly response for one date. Every hour
    gets the same values unless `overrides` maps a variable name to either a
    scalar (all hours) or a {hour: value} dict."""
    def _make(date="2026-06-21", utc_offset_seconds=3600, timezone=None, **overrides):
        base = {
            "temperature_2m": 18.0, "apparent_temperature": 17.0, "precipitation": 0.0,
            "precipitation_probability": 10, "cloud_cover": 40, "visibility": 24000.0,
            "weather_code": 1, "wind_speed_10m": 3.0, "wind_direction_10m": 270,
            "wind_gusts_10m": 6.0, "snow_depth": 0.0,
        }
        hourly = {"time": [f"{date}T{h:02d}:00" for h in range(24)]}
        for var, default in base.items():
            spec = overrides.get(var, default)
            hourly[var] = [spec.get(h, default) if isinstance(spec, dict) else spec for h in range(24)]
        response = {"utc_offset_seconds": utc_offset_seconds, "hourly": hourly}
        if timezone:
            response["timezone"] = timezone
        return response
    return _make


@pytest.fixture
def fixed_now():
    return datetime.datetime(2026, 6, 20, 12, 0, tzinfo=datetime.timezone.utc)
```

`skills/osm-day-route-day-plan/tests/test_foundation.py`:

```python
import datetime
import json

import pytest

from day_plan.cache import JsonCache
from day_plan.context import build_context
from day_plan.facts import load_facts, lookup
from day_plan.http import HttpError, get_json
from day_plan.i18n import STRINGS, compass, tr


def test_tr_falls_back_to_english_for_missing_key_and_unknown_language():
    assert tr("h_summary", "xx") == "Summary"
    assert tr("w_warn_fog", "de") == tr("w_warn_fog", "en")
    assert tr("h_summary", "ru") == "Главное на день"


def test_tr_formats_placeholders():
    assert "5" in tr("light_warn_tight", "en", buffer=5)


def test_headings_exist_in_all_seven_languages():
    for lang in ("en", "ru", "es", "fr", "de", "pt", "it"):
        for key in ("h_summary", "h_light", "h_weather", "h_transit", "h_pois", "h_hazards", "h_cell_coverage"):
            assert key in STRINGS[lang], (lang, key)


def test_compass_points():
    assert compass(0, "en") == "N"
    assert compass(270, "en") == "W"
    assert compass(359, "en") == "N"
    assert compass(45, "ru") == "СВ"


def test_cache_roundtrip_and_expiry(tmp_path):
    clock = [1000.0]
    cache = JsonCache(tmp_path / "c.json", now=lambda: clock[0])
    assert cache.get_entry("k") is None
    cache.put("k", {"a": 1})
    assert cache.get_entry("k") == ({"a": 1}, 1000.0)
    clock[0] = 1000.0 + 50
    assert cache.get_entry("k", max_age=100) is not None
    assert cache.get_entry("k", max_age=10) is None
    reloaded = JsonCache(tmp_path / "c.json", now=lambda: clock[0])
    assert reloaded.get_entry("k") == ({"a": 1}, 1000.0)


def test_cache_ignores_corrupt_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    assert JsonCache(path).get_entry("k") is None


def test_facts_lookup_prefers_date_over_all(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({
        "all": {"transit": {"markdown": "generic"}},
        "2026-06-21": {"transit": {"markdown": "specific"}},
    }), encoding="utf-8")
    facts = load_facts(tmp_path)
    assert lookup(facts, "2026-06-21", "transit")["markdown"] == "specific"
    assert lookup(facts, "2026-06-22", "transit")["markdown"] == "generic"
    assert lookup(facts, "2026-06-22", "poi") is None


def test_load_facts_missing_or_invalid_is_empty(tmp_path):
    assert load_facts(tmp_path) == {}
    (tmp_path / "facts.json").write_text("[]", encoding="utf-8")
    assert load_facts(tmp_path) == {}


def test_get_json_wraps_transport_errors():
    import urllib.error
    from unittest.mock import patch
    with patch("day_plan.http._open", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(HttpError):
            get_json("https://example.invalid/")


def test_build_context_reads_route(make_route, fixed_now):
    route_dir = make_route(name="Loop", mode="bike", duration_hours=3.5)
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), lang="ru", now=fixed_now)
    assert ctx.route_name == "Loop"
    assert ctx.mode == "bike"
    assert ctx.duration_hours == 3.5
    assert ctx.centroid == pytest.approx((51.5, -0.125))
    assert ctx.coords[0] == (-0.20, 51.45, 30.0)
    assert ctx.today == datetime.date(2026, 6, 20)
    assert ctx.date_iso == "2026-06-21"


def test_build_context_tolerates_2d_coordinates_and_missing_properties(make_route, fixed_now):
    route_dir = make_route(coords=((10.0, 50.0), (10.2, 50.2)))
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.coords[0] == (10.0, 50.0, None)


def test_build_context_rejects_route_without_linestring(tmp_path, fixed_now):
    (tmp_path / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    with pytest.raises(ValueError):
        build_context(tmp_path, datetime.date(2026, 6, 21), now=fixed_now)


def test_centroid_of_a_route_crossing_the_antimeridian_is_near_180(make_route, fixed_now):
    route_dir = make_route(coords=((179.5, 66.0, None), (-179.5, 66.2, None)))
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert abs(abs(ctx.centroid[1]) - 180.0) < 0.6
    assert ctx.centroid[0] == pytest.approx(66.1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_foundation.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'day_plan'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/__init__.py`:

```python
"""Day-plan builder: one Markdown briefing per (route, date). See
docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md."""
```

`skills/osm-day-route-day-plan/scripts/day_plan/base.py`:

```python
"""Shared types for the day-plan plugin system. Mirrors the shape of
place_info/ and tile_providers/: one plugin per topic, a service that runs
them with per-plugin fault isolation."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

SEVERITIES = ("info", "caution", "danger")
CONFIDENCE_TIERS = ("tag-backed", "web-sourced", "derived", "no-data")

# Fixed order of section groups in day-plan-<date>.md (spec, "Output").
# "hazards" is a group: several plugins contribute to it.
SECTION_ORDER = ("summary", "light", "weather", "transit", "pois", "hazards", "cell_coverage")


@dataclass
class PlanWarning:
    severity: str  # one of SEVERITIES
    text: str


@dataclass
class Section:
    section_id: str  # one of SECTION_ORDER
    markdown: str
    confidence: str = "no-data"  # one of CONFIDENCE_TIERS
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    shared: dict = field(default_factory=dict)  # data for dependent plugins
    title: str | None = None  # sub-heading, used when a group has >1 plugin


class SectionPlugin(ABC):
    plugin_id: str
    section_id: str
    version: str = "1"
    depends_on: tuple = ()

    @abstractmethod
    def run(self, ctx, shared: dict) -> Section:
        """`shared` maps plugin_id -> that plugin's Section.shared for every
        plugin in depends_on that ran successfully (a failed or missing
        dependency is simply absent — handle that). Return a no-data Section
        for an ordinary 'nothing found' outcome; only a genuine
        programming error should raise (the service isolates it)."""
        raise NotImplementedError
```

`skills/osm-day-route-day-plan/scripts/day_plan/http.py`:

```python
"""One stdlib JSON GET helper. Plugins receive it as ctx.http so tests can
pass a fake instead of patching urllib."""
import json
import urllib.error
import urllib.request

USER_AGENT = "osm-day-route-day-plan/1.0"


class HttpError(Exception):
    pass


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e
```

`skills/osm-day-route-day-plan/scripts/day_plan/cache.py`:

```python
"""Per-route JSON cache with optional max age. Written on every put, same
incremental-write reasoning as place_info/cache.py."""
import json
import time
from pathlib import Path


class JsonCache:
    def __init__(self, path, now=time.time):
        self._path = Path(path)
        self._now = now
        self._data = {}
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except json.JSONDecodeError:
                self._data = {}

    def get_entry(self, key: str, max_age: float | None = None):
        """Returns (value, stored_at_epoch) or None if absent or older than
        max_age seconds (max_age=None means never expires)."""
        entry = self._data.get(key)
        if not isinstance(entry, dict) or "v" not in entry or "t" not in entry:
            return None
        if max_age is not None and self._now() - entry["t"] > max_age:
            return None
        return entry["v"], entry["t"]

    def put(self, key: str, value) -> float:
        stored_at = self._now()
        self._data[key] = {"t": stored_at, "v": value}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        return stored_at
```

`skills/osm-day-route-day-plan/scripts/day_plan/facts.py`:

```python
"""facts.json: web-sourced material Claude gathered by searching and
recorded for the plan (spec, "Skill boundary"). Shape:

    {"<YYYY-MM-DD>" or "all": {"<plugin_id>": {
        "markdown": "...", "confidence": "web-sourced",
        "sources": ["https://..."]}}}

A date-specific entry wins over an "all" entry."""
import json
from pathlib import Path


def load_facts(route_dir) -> dict:
    path = Path(route_dir) / "facts.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def lookup(facts: dict, date_iso: str, plugin_id: str) -> dict | None:
    for scope in (date_iso, "all"):
        entry = (facts.get(scope) or {}).get(plugin_id)
        if isinstance(entry, dict) and entry.get("markdown"):
            return entry
    return None
```

`skills/osm-day-route-day-plan/scripts/day_plan/context.py`:

```python
"""PlanContext: everything a plugin may read. Built once per run from the
route archive (route.geojson) and the CLI arguments."""
import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cache import JsonCache
from .facts import load_facts
from .http import get_json


@dataclass
class PlanContext:
    route_dir: Path
    date: datetime.date
    lang: str
    departure: str | None
    start_time: datetime.time | None
    mode: str
    route_name: str
    coords: list  # [(lon, lat, ele_or_None), ...] of the route LineString
    distance_km: float | None
    duration_hours: float | None
    centroid: tuple  # (lat, lon), bbox center of the route
    facts: dict
    http: Callable
    cache: JsonCache
    now: datetime.datetime  # timezone-aware UTC
    today: datetime.date = field(init=False)

    def __post_init__(self):
        self.today = self.now.date()

    @property
    def date_iso(self) -> str:
        return self.date.isoformat()


def _line_feature(geojson: dict) -> dict:
    for feature in geojson.get("features", []):
        if (feature.get("geometry") or {}).get("type") == "LineString":
            return feature
    raise ValueError("route.geojson has no LineString feature")


def build_context(route_dir, date: datetime.date, lang: str = "en", departure: str | None = None,
                  start_time: datetime.time | None = None, http: Callable = get_json,
                  cache: JsonCache | None = None, now: datetime.datetime | None = None) -> PlanContext:
    route_dir = Path(route_dir)
    geojson = json.loads((route_dir / "route.geojson").read_text(encoding="utf-8"))
    line = _line_feature(geojson)
    props = line.get("properties") or {}
    coords = []
    for c in line["geometry"]["coordinates"]:
        coords.append((c[0], c[1], c[2] if len(c) > 2 else None))
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    if max(lons) - min(lons) > 180.0:  # crosses the antimeridian (e.g. Chukotka)
        lons = [lon + 360.0 if lon < 0 else lon for lon in lons]
    center_lon = (min(lons) + max(lons)) / 2.0
    if center_lon > 180.0:
        center_lon -= 360.0
    centroid = ((min(lats) + max(lats)) / 2.0, center_lon)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return PlanContext(
        route_dir=route_dir, date=date, lang=lang, departure=departure, start_time=start_time,
        mode=props.get("mode") or "walk",
        route_name=props.get("name") or route_dir.name,
        coords=coords,
        distance_km=props.get("distance_km"),
        duration_hours=props.get("duration_estimate_hours"),
        centroid=centroid,
        facts=load_facts(route_dir),
        http=http,
        cache=cache if cache is not None else JsonCache(route_dir / "day_plan_cache.json", now=now.timestamp),
        now=now,
    )
```

`skills/osm-day-route-day-plan/scripts/day_plan/i18n.py` (holds every string this plan's plugins and assembler use, so later tasks do not edit it):

```python
"""Localized strings for the plan text. Section headings, the metadata line
and severity labels exist in all seven languages of osm-day-route-show
(en/ru/es/fr/de/pt/it); the body strings of light/weather are translated for
en and ru only and fall back to English for the rest (same fallback rule as
osm-day-route-show's UI_STRINGS). The summary heading is also listed in
osm-day-route-show's SECTION_ALIASES["day_plan_summary"] — keep them in sync."""

LANGS = ("en", "ru", "es", "fr", "de", "pt", "it")

STRINGS = {
    "en": {
        "h_summary": "Summary",
        "h_light": "Daylight",
        "h_weather": "Weather by hour",
        "h_transit": "Getting there",
        "h_pois": "Points of interest",
        "h_hazards": "Hazards",
        "h_cell_coverage": "Mobile coverage",
        "sev_danger": "Danger", "sev_caution": "Caution", "sev_info": "Note",
        "summary_none": "No warnings for this date.",
        "summary_no_data": "Sections without data: {names}.",
        "no_data_section": "No data available for this section.",
        "plugin_failed": "This section could not be built ({reason}).",
        "meta": "Forecast fetched {fetched} UTC · Mode: {mode}",
        "meta_from": " · From: {departure}",
        "mode_walk": "walking", "mode_bike": "cycling",
        # light
        "light_line": "Sunrise **{sunrise}**, sunset **{sunset}**, daylight **{length}**.",
        "light_tz_approx": "Times use a time zone estimated from longitude (weather data was unavailable).",
        "light_polar_day": "Polar day: the sun does not set on this date.",
        "light_polar_night": "Polar night: the sun does not rise on this date.",
        "light_finish": "Start {start} → estimated finish {finish}; margin to sunset: **{margin}**.",
        "light_latest_start": "To finish {buffer} min before sunset, start no later than **{latest}**.",
        "light_no_duration": "The route duration is not in the archive, so the finish margin is not estimated.",
        "light_warn_after_sunset": "The route is estimated to end {minutes} min after sunset — carry a headlamp or start earlier.",
        "light_warn_tight": "Less than {buffer} min of daylight will be left after the estimated finish.",
        "light_warn_not_fit": "The route (about {hours} h) does not fit into the daylight ({length}) — shorten it or plan for a headlamp.",
        "light_warn_polar_night": "The sun does not rise on this date — plan for artificial light all day.",
        "unit_h": "h", "unit_min": "min",
        # weather
        "w_time": "Time", "w_temp": "°C", "w_feels": "Feels °C", "w_precip": "Precip mm (prob %)",
        "w_cloud": "Cloud %", "w_vis": "Vis km", "w_wind": "Wind m/s (from)", "w_gust": "Gusts m/s",
        "w_snow": "Snow cm", "w_sky": "Sky",
        "w_source_forecast": "Source: Open-Meteo forecast (model output).",
        "w_source_archive": "Source: Open-Meteo historical archive (actual past weather).",
        "w_source_climate": "No forecast exists this far ahead: values are the average of this date over the last {years} years (climatology), not a forecast.",
        "w_unavailable": "The weather service could not be reached ({reason}).",
        "w_warn_thunder": "Thunderstorms are forecast — avoid ridges, open ground and lone trees.",
        "w_warn_fog": "Fog or visibility under 1 km is expected — navigation will be harder.",
        "w_warn_gust": "Gusts up to {value} m/s ({label}).",
        "w_warn_cold": "Feels-like temperature down to {value} °C — risk of hypothermia and frostbite.",
        "w_warn_heat": "Feels-like temperature up to {value} °C — carry extra water and avoid midday exertion.",
        "w_warn_rain": "Heavy precipitation expected (up to {value} mm/h).",
        "w_warn_snow": "Snow cover of about {value} cm is expected on the ground.",
        "w_warn_climate": "Beyond the forecast horizon: this is climatology, not a forecast.",
        "gust_strong": "strong wind", "gust_storm": "storm-force wind",
        "sky_clear": "clear", "sky_partly": "partly cloudy", "sky_overcast": "overcast", "sky_fog": "fog",
        "sky_drizzle": "drizzle", "sky_rain": "rain", "sky_snow": "snow", "sky_showers": "showers",
        "sky_thunder": "thunderstorm", "sky_unknown": "–",
        "compass": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    },
    "ru": {
        "h_summary": "Главное на день",
        "h_light": "Световой день",
        "h_weather": "Погода по часам",
        "h_transit": "Как добраться",
        "h_pois": "Точки интереса",
        "h_hazards": "Опасности",
        "h_cell_coverage": "Сотовая связь",
        "sev_danger": "Опасно", "sev_caution": "Осторожно", "sev_info": "К сведению",
        "summary_none": "Предупреждений на эту дату нет.",
        "summary_no_data": "Разделы без данных: {names}.",
        "no_data_section": "Для этого раздела нет данных.",
        "plugin_failed": "Раздел не удалось построить ({reason}).",
        "meta": "Прогноз получен {fetched} UTC · Режим: {mode}",
        "meta_from": " · Откуда: {departure}",
        "mode_walk": "пешком", "mode_bike": "на велосипеде",
        "light_line": "Рассвет **{sunrise}**, закат **{sunset}**, световой день **{length}**.",
        "light_tz_approx": "Время указано по часовому поясу, оценённому по долготе (данных погоды не было).",
        "light_polar_day": "Полярный день: в эту дату солнце не заходит.",
        "light_polar_night": "Полярная ночь: в эту дату солнце не восходит.",
        "light_finish": "Старт {start} → расчётный финиш {finish}; запас до заката: **{margin}**.",
        "light_latest_start": "Чтобы закончить за {buffer} мин до заката, стартуйте не позже **{latest}**.",
        "light_no_duration": "Длительности маршрута нет в архиве, поэтому запас до заката не оценён.",
        "light_warn_after_sunset": "Маршрут, по оценке, закончится через {minutes} мин после заката — возьмите налобный фонарь или стартуйте раньше.",
        "light_warn_tight": "После расчётного финиша останется меньше {buffer} мин светлого времени.",
        "light_warn_not_fit": "Маршрут (около {hours} ч) не помещается в световой день ({length}) — сократите его или рассчитывайте на фонарь.",
        "light_warn_polar_night": "В эту дату солнце не восходит — рассчитывайте на искусственный свет весь день.",
        "unit_h": "ч", "unit_min": "мин",
        "w_time": "Время", "w_temp": "°C", "w_feels": "Ощущ. °C", "w_precip": "Осадки мм (вер. %)",
        "w_cloud": "Облачн. %", "w_vis": "Вид. км", "w_wind": "Ветер м/с (откуда)", "w_gust": "Порывы м/с",
        "w_snow": "Снег см", "w_sky": "Небо",
        "w_source_forecast": "Источник: прогноз Open-Meteo (расчёт модели).",
        "w_source_archive": "Источник: архив Open-Meteo (фактическая погода в прошлом).",
        "w_source_climate": "Прогноза на такую дату нет: значения — среднее за эту дату за последние {years} лет (климатика), а не прогноз.",
        "w_unavailable": "Сервис погоды недоступен ({reason}).",
        "w_warn_thunder": "Ожидается гроза — избегайте гребней, открытых мест и одиноких деревьев.",
        "w_warn_fog": "Ожидается туман или видимость меньше 1 км — ориентироваться будет труднее.",
        "w_warn_gust": "Порывы до {value} м/с ({label}).",
        "w_warn_cold": "Ощущаемая температура до {value} °C — риск переохлаждения и обморожения.",
        "w_warn_heat": "Ощущаемая температура до {value} °C — возьмите больше воды, избегайте нагрузки в полдень.",
        "w_warn_rain": "Ожидаются сильные осадки (до {value} мм/ч).",
        "w_warn_snow": "Ожидается снежный покров около {value} см.",
        "w_warn_climate": "За горизонтом прогноза: это климатика, а не прогноз.",
        "gust_strong": "сильный ветер", "gust_storm": "штормовой ветер",
        "sky_clear": "ясно", "sky_partly": "переменная облачность", "sky_overcast": "пасмурно", "sky_fog": "туман",
        "sky_drizzle": "морось", "sky_rain": "дождь", "sky_snow": "снег", "sky_showers": "ливни",
        "sky_thunder": "гроза", "sky_unknown": "–",
        "compass": ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"],
    },
    "es": {
        "h_summary": "Resumen del día", "h_light": "Luz diurna", "h_weather": "Tiempo por horas",
        "h_transit": "Cómo llegar", "h_pois": "Puntos de interés", "h_hazards": "Peligros",
        "h_cell_coverage": "Cobertura móvil",
        "sev_danger": "Peligro", "sev_caution": "Precaución", "sev_info": "Nota",
        "meta": "Previsión obtenida {fetched} UTC · Modo: {mode}", "meta_from": " · Desde: {departure}",
        "mode_walk": "a pie", "mode_bike": "en bicicleta",
        "compass": ["N", "NE", "E", "SE", "S", "SO", "O", "NO"],
    },
    "fr": {
        "h_summary": "L'essentiel du jour", "h_light": "Lumière du jour", "h_weather": "Météo heure par heure",
        "h_transit": "Comment s'y rendre", "h_pois": "Points d'intérêt", "h_hazards": "Dangers",
        "h_cell_coverage": "Couverture mobile",
        "sev_danger": "Danger", "sev_caution": "Prudence", "sev_info": "Remarque",
        "meta": "Prévision récupérée {fetched} UTC · Mode : {mode}", "meta_from": " · Depuis : {departure}",
        "mode_walk": "à pied", "mode_bike": "à vélo",
        "compass": ["N", "NE", "E", "SE", "S", "SO", "O", "NO"],
    },
    "de": {
        "h_summary": "Das Wichtigste", "h_light": "Tageslicht", "h_weather": "Wetter nach Stunden",
        "h_transit": "Anreise", "h_pois": "Sehenswürdigkeiten", "h_hazards": "Gefahren",
        "h_cell_coverage": "Mobilfunkempfang",
        "sev_danger": "Gefahr", "sev_caution": "Vorsicht", "sev_info": "Hinweis",
        "meta": "Vorhersage abgerufen {fetched} UTC · Modus: {mode}", "meta_from": " · Von: {departure}",
        "mode_walk": "zu Fuß", "mode_bike": "mit dem Rad",
        "compass": ["N", "NO", "O", "SO", "S", "SW", "W", "NW"],
    },
    "pt": {
        "h_summary": "Resumo do dia", "h_light": "Luz do dia", "h_weather": "Tempo hora a hora",
        "h_transit": "Como chegar", "h_pois": "Pontos de interesse", "h_hazards": "Perigos",
        "h_cell_coverage": "Cobertura móvel",
        "sev_danger": "Perigo", "sev_caution": "Cuidado", "sev_info": "Nota",
        "meta": "Previsão obtida {fetched} UTC · Modo: {mode}", "meta_from": " · De: {departure}",
        "mode_walk": "a pé", "mode_bike": "de bicicleta",
        "compass": ["N", "NE", "L", "SE", "S", "SO", "O", "NO"],
    },
    "it": {
        "h_summary": "In breve", "h_light": "Luce del giorno", "h_weather": "Meteo ora per ora",
        "h_transit": "Come arrivare", "h_pois": "Punti di interesse", "h_hazards": "Pericoli",
        "h_cell_coverage": "Copertura cellulare",
        "sev_danger": "Pericolo", "sev_caution": "Attenzione", "sev_info": "Nota",
        "meta": "Previsione ottenuta {fetched} UTC · Modalità: {mode}", "meta_from": " · Da: {departure}",
        "mode_walk": "a piedi", "mode_bike": "in bici",
        "compass": ["N", "NE", "E", "SE", "S", "SO", "O", "NO"],
    },
}


def tr(key: str, lang: str, **fmt):
    """String for `key` in `lang`, English fallback for any missing key or
    unknown language. Formats with **fmt when given (lists are returned
    as-is)."""
    value = STRINGS.get(lang, {}).get(key)
    if value is None:
        value = STRINGS["en"][key]
    if fmt and isinstance(value, str):
        return value.format(**fmt)
    return value


def compass(degrees: float, lang: str) -> str:
    """8-point compass label for a bearing in degrees (direction the wind
    blows FROM)."""
    names = tr("compass", lang)
    return names[int(((degrees % 360) + 22.5) // 45) % 8]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_foundation.py -q`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "Add day-plan foundation: types, i18n, http, cache, facts, context

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sunrise and sunset math

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/sun.py`
- Test: `skills/osm-day-route-day-plan/tests/test_sun.py`

**Interfaces:**
- Produces: `sun_times(date, lat, lon) -> SunTimes(kind, sunrise_utc_min, sunset_utc_min)` where `kind` is `"normal" | "polar_day" | "polar_night"` and the times are minutes after 00:00 UTC of `date` (negative or above 1440 at extreme longitudes); `date` is the local solar date.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_sun.py`:

```python
import datetime

import pytest

from day_plan.sun import sun_times


def _hm(minutes):
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def test_london_summer_solstice_matches_published_times():
    s = sun_times(datetime.date(2026, 6, 21), 51.5074, -0.1278)
    assert s.kind == "normal"
    assert s.sunrise_utc_min == pytest.approx(3 * 60 + 43, abs=3)   # 04:43 BST
    assert s.sunset_utc_min == pytest.approx(20 * 60 + 21, abs=3)   # 21:21 BST


def test_london_winter_solstice_matches_published_times():
    s = sun_times(datetime.date(2026, 12, 21), 51.5074, -0.1278)
    assert s.sunrise_utc_min == pytest.approx(8 * 60 + 4, abs=3)
    assert s.sunset_utc_min == pytest.approx(15 * 60 + 53, abs=3)


def test_equator_equinox_day_is_about_twelve_hours_seven_minutes():
    s = sun_times(datetime.date(2026, 3, 20), 0.0, 0.0)
    assert s.sunset_utc_min - s.sunrise_utc_min == pytest.approx(12 * 60 + 7, abs=4)


def test_polar_day_and_night_above_the_arctic_circle():
    assert sun_times(datetime.date(2026, 6, 21), 69.65, 18.96).kind == "polar_day"
    assert sun_times(datetime.date(2026, 12, 21), 69.65, 18.96).kind == "polar_night"


def test_far_east_sunrise_is_on_the_previous_utc_day():
    # Kamchatka, UTC+12: local morning is the previous UTC evening.
    s = sun_times(datetime.date(2026, 6, 21), 53.0, 158.65)
    assert s.sunrise_utc_min < 0
    assert s.sunset_utc_min > 0


def test_southern_hemisphere_has_short_june_days():
    s = sun_times(datetime.date(2026, 6, 21), -33.87, 151.21)  # Sydney
    assert 9 * 60 + 30 < (s.sunset_utc_min - s.sunrise_utc_min) < 10 * 60 + 30
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_sun.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'day_plan.sun'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/sun.py`:

```python
"""Sunrise/sunset from the NOAA solar-position equations. Pure math, no
network. Times are minutes after 00:00 UTC of the given date (they may be
negative or above 1440 at extreme longitudes), where `date` is the local
solar date — the caller adds the UTC offset."""
import datetime
import math
from dataclasses import dataclass

_ZENITH_DEG = 90.833  # sunrise/sunset: refraction + solar disc radius


@dataclass(frozen=True)
class SunTimes:
    kind: str  # "normal" | "polar_day" | "polar_night"
    sunrise_utc_min: float | None = None
    sunset_utc_min: float | None = None


def _julian_century(date: datetime.date, minutes_utc: float) -> float:
    jd = date.toordinal() + 1721424.5 + minutes_utc / 1440.0
    return (jd - 2451545.0) / 36525.0


def _solar(t: float) -> tuple[float, float]:
    """(declination in radians, equation of time in minutes)."""
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    seconds = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    eps = math.radians(23.0 + (26.0 + seconds / 60.0) / 60.0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2.0) ** 2
    l0r = math.radians(l0)
    eqtime = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr)
    )
    return decl, eqtime


def _cos_hour_angle(lat: float, decl: float) -> float:
    latr = math.radians(lat)
    return (math.cos(math.radians(_ZENITH_DEG)) / (math.cos(latr) * math.cos(decl))
            - math.tan(latr) * math.tan(decl))


def sun_times(date: datetime.date, lat: float, lon: float) -> SunTimes:
    decl, eq = _solar(_julian_century(date, 720.0 - 4.0 * lon))
    cos_ha = _cos_hour_angle(lat, decl)
    if cos_ha > 1.0:
        return SunTimes("polar_night")
    if cos_ha < -1.0:
        return SunTimes("polar_day")

    def event(sign: int) -> float:
        # sign=+1 sunrise, -1 sunset; refine at the event's own time.
        minutes = 720.0 - 4.0 * lon - eq
        for _ in range(3):
            decl_i, eq_i = _solar(_julian_century(date, minutes))
            ha = math.degrees(math.acos(max(-1.0, min(1.0, _cos_hour_angle(lat, decl_i)))))
            minutes = 720.0 - 4.0 * (lon + sign * ha) - eq_i
        return minutes

    return SunTimes("normal", sunrise_utc_min=event(+1), sunset_utc_min=event(-1))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_sun.py -q`
Expected: PASS (6 passed). The London checks compare against published solstice times (04:43/21:21 BST in June, 08:04/15:53 in December) within 3 minutes.

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/day_plan/sun.py skills/osm-day-route-day-plan/tests/test_sun.py
git commit -m "Add NOAA sunrise/sunset calculation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Light plugin

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/__init__.py`, `skills/osm-day-route-day-plan/scripts/day_plan/plugins/light.py`
- Test: `skills/osm-day-route-day-plan/tests/test_light.py`

**Interfaces:**
- Consumes: `SectionPlugin`, `Section`, `PlanWarning` (Task 1); `tr` (Task 1); `sun_times` (Task 2); `ctx.centroid`, `ctx.date`, `ctx.lang`, `ctx.duration_hours`, `ctx.start_time`; `shared["weather"]["utc_offset_seconds"]` when the weather plugin ran.
- Produces: `LightPlugin` (`plugin_id="light"`, `section_id="light"`, `depends_on=("weather",)`); its `Section.shared` has `kind`, and for a normal day `sunrise_local_min`, `sunset_local_min`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_light.py`:

```python
import datetime

from day_plan.plugins.light import LightPlugin


class Ctx:
    lang = "en"
    centroid = (51.5074, -0.1278)
    date = datetime.date(2026, 6, 21)
    duration_hours = 5.0
    start_time = None


def _run(shared=None, **overrides):
    ctx = Ctx()
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return LightPlugin().run(ctx, shared if shared is not None else {"weather": {"utc_offset_seconds": 3600}})


def test_reports_sunrise_sunset_and_length_in_local_time():
    section = _run()
    assert "**04:43**" in section.markdown or "**04:44**" in section.markdown
    assert "**21:21**" in section.markdown or "**21:22**" in section.markdown
    assert "16 h 3" in section.markdown
    assert section.confidence == "derived"
    assert section.shared["kind"] == "normal"


def test_without_start_time_reports_latest_start():
    section = _run()
    assert "start no later than" in section.markdown


def test_start_time_reports_finish_and_margin_without_warning():
    section = _run(start_time=datetime.time(9, 0))
    assert "estimated finish 14:00" in section.markdown
    assert section.warnings == []


def test_finish_after_sunset_is_a_danger_warning():
    section = _run(start_time=datetime.time(18, 0))
    assert [w.severity for w in section.warnings] == ["danger"]
    assert "after sunset" in section.warnings[0].text


def test_tight_margin_is_a_caution():
    section = _run(start_time=datetime.time(15, 30))  # ends 20:30, sunset ~21:21
    assert [w.severity for w in section.warnings] == ["caution"]


def test_route_longer_than_daylight_is_danger():
    section = _run(duration_hours=17.0)
    assert any(w.severity == "danger" and "does not fit" in w.text for w in section.warnings)


def test_latest_start_before_sunrise_is_a_caution():
    section = _run(duration_hours=16.0)  # 16 h + 60 min buffer > 16 h 38 min of light
    assert any(w.severity == "caution" for w in section.warnings)
    assert not any(w.severity == "danger" for w in section.warnings)


def test_missing_duration_skips_margin_and_says_so():
    section = _run(duration_hours=None)
    assert "not in the archive" in section.markdown
    assert section.warnings == []


def test_missing_weather_falls_back_to_longitude_offset_and_says_so():
    section = _run(shared={})
    assert "estimated from longitude" in section.markdown


def test_polar_night_is_a_danger_and_polar_day_is_info():
    night = _run(centroid=(69.65, 18.96), date=datetime.date(2026, 12, 21))
    assert night.warnings[0].severity == "danger"
    day = _run(centroid=(69.65, 18.96), date=datetime.date(2026, 6, 21))
    assert day.warnings[0].severity == "info"


def test_russian_output():
    section = _run(lang="ru")
    assert "Рассвет" in section.markdown and "ч" in section.markdown
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_light.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'day_plan.plugins'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/__init__.py` is an empty file.

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/light.py`:

```python
"""Sunrise, sunset, day length and the margin between sunset and the
route's estimated finish. Confidence: derived (computed locally, no
network). Astronomical events beyond these times are out of scope (spec)."""
import datetime
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..i18n import tr
from ..sun import sun_times

SAFETY_BUFFER_MIN = 60  # finish this long before sunset by default


def _hhmm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _duration(minutes: float, lang: str) -> str:
    total = int(round(abs(minutes)))
    sign = "-" if minutes < 0 else ""
    return f"{sign}{total // 60} {tr('unit_h', lang)} {total % 60:02d} {tr('unit_min', lang)}"


class LightPlugin(SectionPlugin):
    plugin_id = "light"
    section_id = "light"
    depends_on = ("weather",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        sun = sun_times(ctx.date, lat, lon)

        if sun.kind == "polar_day":
            return Section("light", "- " + tr("light_polar_day", lang), "derived",
                           warnings=[PlanWarning("info", tr("light_polar_day", lang))],
                           shared={"kind": sun.kind})
        if sun.kind == "polar_night":
            return Section("light", "- " + tr("light_polar_night", lang), "derived",
                           warnings=[PlanWarning("danger", tr("light_warn_polar_night", lang))],
                           shared={"kind": sun.kind})

        weather = shared.get("weather") or {}
        offset_s = weather.get("utc_offset_seconds")
        approximate = offset_s is None
        if approximate:
            offset_s = round(lon / 15.0 * 2) / 2 * 3600  # nearest half hour
        sunrise = sun.sunrise_utc_min + offset_s / 60.0
        sunset = sun.sunset_utc_min + offset_s / 60.0
        length = sunset - sunrise

        lines = ["- " + tr("light_line", lang, sunrise=_hhmm(sunrise), sunset=_hhmm(sunset),
                           length=_duration(length, lang))]
        warnings = []
        if approximate:
            lines.append("- " + tr("light_tz_approx", lang))

        duration_min = ctx.duration_hours * 60.0 if ctx.duration_hours else None
        if duration_min is None:
            lines.append("- " + tr("light_no_duration", lang))
        else:
            if ctx.start_time is not None:
                start = ctx.start_time.hour * 60 + ctx.start_time.minute
                finish = start + duration_min
                margin = sunset - finish
                lines.append("- " + tr("light_finish", lang, start=_hhmm(start), finish=_hhmm(finish),
                                       margin=_duration(margin, lang)))
                if margin < 0:
                    warnings.append(PlanWarning("danger", tr(
                        "light_warn_after_sunset", lang, minutes=int(round(-margin)))))
                elif margin < SAFETY_BUFFER_MIN:
                    warnings.append(PlanWarning("caution", tr("light_warn_tight", lang, buffer=SAFETY_BUFFER_MIN)))
            else:
                latest = sunset - SAFETY_BUFFER_MIN - duration_min
                lines.append("- " + tr("light_latest_start", lang, buffer=SAFETY_BUFFER_MIN, latest=_hhmm(latest)))
                if latest < sunrise and duration_min <= length:
                    warnings.append(PlanWarning("caution", tr("light_warn_tight", lang, buffer=SAFETY_BUFFER_MIN)))
            if duration_min > length:
                warnings.append(PlanWarning("danger", tr(
                    "light_warn_not_fit", lang, hours=round(duration_min / 60.0, 1), length=_duration(length, lang))))

        return Section("light", "\n".join(lines), "derived", warnings=warnings,
                       shared={"kind": "normal", "sunrise_local_min": sunrise, "sunset_local_min": sunset})
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_light.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/day_plan/plugins skills/osm-day-route-day-plan/tests/test_light.py
git commit -m "Add daylight plugin: sunrise, sunset, day length, finish margin

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Weather plugin

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py`
- Test: `skills/osm-day-route-day-plan/tests/test_weather.py`

**Interfaces:**
- Consumes: `SectionPlugin`, `Section`, `PlanWarning`, `HttpError`, `tr`, `compass`, `sun_times`; `ctx.http(url) -> dict`, `ctx.cache.get_entry/put`, `ctx.centroid`, `ctx.date`, `ctx.today`, `ctx.lang`.
- Produces: `WeatherPlugin` (`plugin_id="weather"`, `section_id="weather"`); `Section.shared` = `utc_offset_seconds`, `rows` (24 dicts: `hour, temp, feels, precip, prob, cloud, vis_m, code, wind, wdir, gust, snow_m`), `daytime_rows`, `source` (`forecast | archive | climate`), `fetched_at` (epoch), `daily_mean_temp`. Also module functions `choose_source`, `parse_hourly`, `average_rows`, `utc_offset_for`, `daytime_rows`, `render_table`, `warnings_for`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_weather.py`:

```python
import datetime

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.weather import (
    WeatherPlugin, average_rows, choose_source, daytime_rows, parse_hourly, render_table, utc_offset_for,
    warnings_for,
)

TODAY = datetime.date(2026, 6, 20)


def _ctx(make_route, fixed_now, http, date=datetime.date(2026, 6, 21), lang="en"):
    return build_context(make_route(), date, lang=lang, http=http, now=fixed_now)


def test_choose_source_boundaries():
    assert choose_source(TODAY + datetime.timedelta(days=15), TODAY) == "forecast"
    assert choose_source(TODAY + datetime.timedelta(days=16), TODAY) == "climate"
    assert choose_source(TODAY - datetime.timedelta(days=92), TODAY) == "forecast"
    assert choose_source(TODAY - datetime.timedelta(days=93), TODAY) == "archive"


def test_parse_hourly_maps_variables_and_tolerates_missing_ones(weather_response):
    response = weather_response()
    del response["hourly"]["visibility"]
    rows = parse_hourly(response)
    assert len(rows) == 24
    assert rows[5]["hour"] == 5
    assert rows[5]["temp"] == 18.0
    assert rows[5]["vis_m"] is None
    assert rows[5]["wdir"] == 270


def test_forecast_request_uses_forecast_api_with_ms_and_single_date(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        return weather_response()

    section = WeatherPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert len(urls) == 1
    assert urls[0].startswith("https://api.open-meteo.com/v1/forecast?")
    assert "wind_speed_unit=ms" in urls[0]
    assert "start_date=2026-06-21&end_date=2026-06-21" in urls[0]
    assert "timezone=auto" in urls[0]
    assert section.confidence == "derived"
    assert section.shared["source"] == "forecast"
    assert section.shared["utc_offset_seconds"] == 3600


def test_old_date_uses_archive_api(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        return weather_response(date="2026-01-10")

    ctx = _ctx(make_route, fixed_now, http, date=datetime.date(2026, 1, 10))
    # today is 2026-06-20, so 2026-01-10 is 161 days back -> archive
    section = WeatherPlugin().run(ctx, {})
    assert urls[0].startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "precipitation_probability" not in urls[0]
    assert "Historical archive" in section.markdown or "historical archive" in section.markdown


def test_far_future_uses_climatology_of_five_previous_years(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        year = url.split("start_date=")[1][:4]
        return weather_response(date=f"{year}-08-15", temperature_2m=float(int(year) - 2000))

    ctx = _ctx(make_route, fixed_now, http, date=datetime.date(2026, 8, 15))
    section = WeatherPlugin().run(ctx, {})
    assert len(urls) == 5
    assert all("archive-api" in u for u in urls)
    assert sorted(u.split("start_date=")[1][:4] for u in urls) == ["2021", "2022", "2023", "2024", "2025"]
    assert section.shared["source"] == "climate"
    assert "not a forecast" in section.markdown
    assert any("climatology" in w.text for w in section.warnings)
    assert section.shared["rows"][12]["temp"] == pytest.approx(23.0)  # mean of 21..25


def test_climatology_of_feb_29_uses_feb_28_in_non_leap_years(make_route, fixed_now, weather_response):
    urls = []

    def http(url):
        urls.append(url)
        year = url.split("start_date=")[1][:4]
        return weather_response(date=f"{year}-02-28")

    ctx = build_context(make_route(), datetime.date(2028, 2, 29), http=http,
                        now=datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    WeatherPlugin().run(ctx, {})
    assert all("2-28" in u for u in urls if "start_date=2025" in u or "start_date=2022" in u)


def test_forecast_is_cached_for_three_hours(make_route, fixed_now, weather_response):
    calls = []

    def http(url):
        calls.append(url)
        return weather_response()

    ctx = _ctx(make_route, fixed_now, http)
    WeatherPlugin().run(ctx, {})
    WeatherPlugin().run(ctx, {})
    assert len(calls) == 1


def test_http_failure_gives_no_data_section_not_an_exception(make_route, fixed_now):
    def http(url):
        raise HttpError("timeout")

    section = WeatherPlugin().run(_ctx(make_route, fixed_now, http), {})
    assert section.confidence == "no-data"
    assert "timeout" in section.markdown
    assert section.shared == {}


def test_malformed_response_gives_no_data_section(make_route, fixed_now):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda url: {"unexpected": True}), {})
    assert section.confidence == "no-data"


def test_daytime_rows_follow_sunrise_and_sunset(weather_response):
    rows = parse_hourly(weather_response())
    day = daytime_rows(rows, datetime.date(2026, 6, 21), 51.5, -0.13, 3600)
    hours = [r["hour"] for r in day]
    assert hours[0] == 4 and hours[-1] == 21   # sunrise 04:43, sunset 21:21 local


def test_daytime_rows_polar_night_shows_a_midday_window(weather_response):
    rows = parse_hourly(weather_response(date="2026-12-21"))
    day = daytime_rows(rows, datetime.date(2026, 12, 21), 69.65, 18.96, 3600)
    assert [r["hour"] for r in day] == list(range(9, 16))


def test_table_has_wind_direction_from_gusts_and_snow(weather_response):
    rows = parse_hourly(weather_response(wind_direction_10m=270, snow_depth=0.12, wind_speed_10m=4.2))
    table = render_table(rows[10:11], "en")
    assert "4.2 W (270°)" in table
    assert "| 12 |" in table          # snow depth 0.12 m -> 12 cm
    assert table.splitlines()[0].startswith("| Time |")


def test_table_shows_dash_for_missing_values(weather_response):
    response = weather_response()
    response["hourly"]["visibility"] = [None] * 24
    rows = parse_hourly(response)
    assert "–" in render_table(rows[10:11], "en")


def test_precipitation_probability_is_shown_in_parentheses(weather_response):
    rows = parse_hourly(weather_response(precipitation=1.5, precipitation_probability=80))
    assert "1.5 (80)" in render_table(rows[10:11], "en")


def test_thunderstorm_is_danger(weather_response):
    rows = parse_hourly(weather_response(weather_code={14: 95}))
    warnings = warnings_for(rows, "en", "forecast")
    assert ("danger", True) in [(w.severity, "Thunderstorms" in w.text) for w in warnings]


def test_fog_by_code_or_by_visibility(weather_response):
    by_code = warnings_for(parse_hourly(weather_response(weather_code={7: 45})), "en", "forecast")
    by_vis = warnings_for(parse_hourly(weather_response(visibility={7: 400.0})), "en", "forecast")
    assert any("Fog" in w.text for w in by_code)
    assert any("Fog" in w.text for w in by_vis)


def test_gust_severity_levels(weather_response):
    caution = warnings_for(parse_hourly(weather_response(wind_gusts_10m={12: 12.0})), "en", "forecast")
    danger = warnings_for(parse_hourly(weather_response(wind_gusts_10m={12: 20.0})), "en", "forecast")
    assert [w.severity for w in caution if "Gusts" in w.text] == ["caution"]
    assert [w.severity for w in danger if "Gusts" in w.text] == ["danger"]


def test_cold_and_heat(weather_response):
    cold = warnings_for(parse_hourly(weather_response(apparent_temperature=-27.0)), "en", "forecast")
    heat = warnings_for(parse_hourly(weather_response(apparent_temperature={14: 33.0})), "en", "forecast")
    assert any(w.severity == "danger" and "hypothermia" in w.text for w in cold)
    assert any(w.severity == "caution" and "water" in w.text for w in heat)


def test_snow_cover_is_reported_from_snow_depth(weather_response):
    warnings = warnings_for(parse_hourly(weather_response(snow_depth=0.2)), "en", "forecast")
    assert any("Snow cover of about 20 cm" in w.text for w in warnings)


def test_calm_clear_day_has_no_warnings(weather_response):
    assert warnings_for(parse_hourly(weather_response()), "en", "forecast") == []


def test_average_rows_uses_circular_mean_for_wind_direction(weather_response):
    a = parse_hourly(weather_response(wind_direction_10m=350))
    b = parse_hourly(weather_response(wind_direction_10m=10))
    mean = average_rows([a, b])
    assert mean[0]["wdir"] == pytest.approx(0.0, abs=0.5) or mean[0]["wdir"] == pytest.approx(360.0, abs=0.5)


def test_russian_table_headers_and_source_note(make_route, fixed_now, weather_response):
    section = WeatherPlugin().run(_ctx(make_route, fixed_now, lambda url: weather_response(), lang="ru"), {})
    assert section.markdown.splitlines()[0].startswith("| Время |")
    assert "Open-Meteo" in section.markdown


def test_utc_offset_comes_from_the_zone_name_for_the_requested_date(weather_response):
    # Open-Meteo reports the offset of the moment of the request; a January
    # date in London must be UTC+0 even if the response says +3600.
    january = weather_response(date="2024-01-10", utc_offset_seconds=3600, timezone="Europe/London")
    june = weather_response(date="2024-06-21", utc_offset_seconds=0, timezone="Europe/London")
    assert utc_offset_for(january, datetime.date(2024, 1, 10)) == 0
    assert utc_offset_for(june, datetime.date(2024, 6, 21)) == 3600


def test_utc_offset_falls_back_to_the_reported_value(weather_response):
    assert utc_offset_for(weather_response(utc_offset_seconds=7200), datetime.date(2026, 6, 21)) == 7200
    bad_zone = weather_response(utc_offset_seconds=7200, timezone="Not/AZone")
    assert utc_offset_for(bad_zone, datetime.date(2026, 6, 21)) == 7200


def test_wind_speed_without_direction_still_renders(weather_response):
    response = weather_response()
    response["hourly"]["wind_direction_10m"] = [None] * 24
    assert "| 3.0 |" in render_table(parse_hourly(response)[10:11], "en")


def test_dst_day_with_twenty_three_hourly_rows_does_not_crash(make_route, fixed_now, weather_response):
    response = weather_response(date="2026-03-29")
    for series in response["hourly"].values():
        if isinstance(series, list):
            del series[3]   # spring-forward day: the local 03:00 hour does not exist
    section = WeatherPlugin().run(
        _ctx(make_route, fixed_now, lambda url: response, date=datetime.date(2026, 3, 29)), {})
    assert section.confidence == "derived"
    assert len(section.shared["rows"]) == 23
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_weather.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'day_plan.plugins.weather'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py`:

```python
"""Hourly weather from Open-Meteo (free, no key). Source depends on the
date relative to today:

  today-7d .. today+15d   forecast API (the last week is model data)
  older than today-7d     historical archive (recorded weather)
  beyond today+15d        climatology: average of the same date over the
                          last CLIMATE_YEARS years from the archive, labelled
                          as NOT a forecast (spec)

Confidence is always `derived` (model output). Wind direction is reported as
the direction the wind blows FROM. Open-Meteo applies no elevation
correction to wind, so mountain gusts are likely underestimated."""
import datetime
import math
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..base import PlanWarning, Section, SectionPlugin
from ..http import HttpError
from ..i18n import compass, tr
from ..sun import sun_times

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15
FORECAST_PAST_DAYS = 92
CLIMATE_YEARS = 5
FORECAST_TTL_S = 3 * 3600

FORECAST_VARS = (
    "temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
    "cloud_cover", "visibility", "weather_code", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "snow_depth",
)
ARCHIVE_VARS = tuple(v for v in FORECAST_VARS if v not in ("precipitation_probability", "visibility"))

# Row keys <- Open-Meteo hourly variable names
_ROW_KEYS = {
    "temperature_2m": "temp", "apparent_temperature": "feels", "precipitation": "precip",
    "precipitation_probability": "prob", "cloud_cover": "cloud", "visibility": "vis_m",
    "weather_code": "code", "wind_speed_10m": "wind", "wind_direction_10m": "wdir",
    "wind_gusts_10m": "gust", "snow_depth": "snow_m",
}

THRESHOLDS = {
    "gust_caution": 10.0, "gust_danger": 17.0,   # m/s
    "cold_caution": -10.0, "cold_danger": -25.0,  # feels-like, °C
    "heat_caution": 32.0, "heat_danger": 38.0,
    "rain_caution": 2.0,                          # mm/h
    "snow_cm": 5.0,
    "fog_visibility_m": 1000.0,
}
_THUNDER_CODES = (95, 96, 99)
_FOG_CODES = (45, 48)
# Hours shown when there is no normal sunrise/sunset.
_POLAR_DAY_HOURS = (6, 22)
_POLAR_NIGHT_HOURS = (9, 15)


def choose_source(date: datetime.date, today: datetime.date) -> str:
    delta = (date - today).days
    if delta > FORECAST_HORIZON_DAYS:
        return "climate"
    if delta >= -FORECAST_PAST_DAYS:
        return "forecast"
    return "archive"


def _url(base: str, variables, lat: float, lon: float, date: datetime.date) -> str:
    d = date.isoformat()
    return (f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&hourly={','.join(variables)}"
            f"&wind_speed_unit=ms&timezone=auto&start_date={d}&end_date={d}")


def parse_hourly(response: dict) -> list[dict]:
    """Open-Meteo response -> list of 24 row dicts (missing variables are
    None). Row keys: hour (int), temp, feels, precip, prob, cloud, vis_m,
    code, wind, wdir, gust, snow_m."""
    hourly = response["hourly"]
    times = hourly["time"]
    rows = []
    for i, stamp in enumerate(times):
        row = {"hour": int(stamp[11:13])}
        for api_key, row_key in _ROW_KEYS.items():
            series = hourly.get(api_key)
            row[row_key] = series[i] if series is not None and i < len(series) else None
        rows.append(row)
    return rows


def _vector_mean_direction(directions: list[float]) -> float | None:
    if not directions:
        return None
    x = sum(math.sin(math.radians(d)) for d in directions)
    y = sum(math.cos(math.radians(d)) for d in directions)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(x, y)) % 360


def average_rows(per_year_rows: list[list[dict]]) -> list[dict]:
    """Hour-by-hour climatology over several years' rows."""
    out = []
    for hour in range(24):
        samples = [r for rows in per_year_rows for r in rows if r["hour"] == hour]
        row = {"hour": hour}
        for key in ("temp", "feels", "precip", "cloud", "wind", "gust", "snow_m", "vis_m", "prob"):
            values = [s[key] for s in samples if s.get(key) is not None]
            row[key] = sum(values) / len(values) if values else None
        codes = [s["code"] for s in samples if s.get("code") is not None]
        row["code"] = Counter(codes).most_common(1)[0][0] if codes else None
        row["wdir"] = _vector_mean_direction([s["wdir"] for s in samples if s.get("wdir") is not None])
        out.append(row)
    return out


def utc_offset_for(response: dict, date: datetime.date) -> float | None:
    """UTC offset (seconds) valid ON `date`. Open-Meteo's own
    `utc_offset_seconds` reflects the moment of the request, not the requested
    date (checked live: an archive request for a January date returned the
    summer offset), so prefer the IANA zone name it also returns."""
    name = response.get("timezone")
    if name:
        try:
            offset = ZoneInfo(name).utcoffset(datetime.datetime.combine(date, datetime.time(12)))
            if offset is not None:
                return offset.total_seconds()
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return response.get("utc_offset_seconds")


def _same_day_in_year(date: datetime.date, year: int) -> datetime.date:
    try:
        return date.replace(year=year)
    except ValueError:  # 29 February
        return date.replace(year=year, day=28)


def _fetch(ctx, source: str, lat: float, lon: float):
    """Returns (rows, utc_offset_seconds, fetched_at_epoch)."""
    key = f"weather|{source}|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
    max_age = FORECAST_TTL_S if source == "forecast" else None
    cached = ctx.cache.get_entry(key, max_age)
    if cached is not None:
        value, stored_at = cached
        return value["rows"], value["utc_offset_seconds"], stored_at

    if source == "forecast":
        response = ctx.http(_url(FORECAST_URL, FORECAST_VARS, lat, lon, ctx.date))
        rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
    elif source == "archive":
        response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, ctx.date))
        rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
    else:
        per_year, offset = [], None
        for back in range(1, CLIMATE_YEARS + 1):
            past = _same_day_in_year(ctx.date, ctx.today.year - back)
            response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, past))
            per_year.append(parse_hourly(response))
            offset = offset if offset is not None else utc_offset_for(response, ctx.date)
        rows = average_rows(per_year)
    stored_at = ctx.cache.put(key, {"rows": rows, "utc_offset_seconds": offset})
    return rows, offset, stored_at


def daytime_rows(rows: list[dict], date: datetime.date, lat: float, lon: float,
                 utc_offset_seconds: float | None) -> list[dict]:
    sun = sun_times(date, lat, lon)
    if sun.kind == "polar_day":
        lo, hi = _POLAR_DAY_HOURS
        return [r for r in rows if lo <= r["hour"] <= hi]
    if sun.kind == "polar_night":
        lo, hi = _POLAR_NIGHT_HOURS
        return [r for r in rows if lo <= r["hour"] <= hi]
    offset_min = (utc_offset_seconds if utc_offset_seconds is not None else round(lon / 15.0 * 2) / 2 * 3600) / 60.0
    sunrise = sun.sunrise_utc_min + offset_min
    sunset = sun.sunset_utc_min + offset_min
    return [r for r in rows if r["hour"] * 60 + 59 >= sunrise and r["hour"] * 60 <= sunset]


def _sky_key(code) -> str:
    if code is None:
        return "sky_unknown"
    if code in _THUNDER_CODES:
        return "sky_thunder"
    if code in _FOG_CODES:
        return "sky_fog"
    if code in (51, 53, 55, 56, 57):
        return "sky_drizzle"
    if code in (61, 63, 65, 66, 67):
        return "sky_rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "sky_snow"
    if code in (80, 81, 82):
        return "sky_showers"
    if code in (0, 1):
        return "sky_clear"
    if code == 2:
        return "sky_partly"
    if code == 3:
        return "sky_overcast"
    return "sky_unknown"


def _num(value, digits=0) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}"


def _wind_cell(row: dict, lang: str) -> str:
    if row["wind"] is None:
        return "–"
    label = compass(row["wdir"], lang) if row["wdir"] is not None else ""
    return f"{row['wind']:.1f} {label} ({row['wdir']:.0f}°)" if label else f"{row['wind']:.1f}"


def _precip_cell(row: dict) -> str:
    if row["precip"] is None:
        return "–"
    text = f"{row['precip']:.1f}"
    return f"{text} ({row['prob']:.0f})" if row.get("prob") is not None else text


def render_table(rows: list[dict], lang: str) -> str:
    header = [tr(k, lang) for k in ("w_time", "w_temp", "w_feels", "w_precip", "w_cloud", "w_vis",
                                    "w_wind", "w_gust", "w_snow", "w_sky")]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        vis_km = r["vis_m"] / 1000.0 if r.get("vis_m") is not None else None
        snow_cm = r["snow_m"] * 100.0 if r.get("snow_m") is not None else None
        cells = [f"{r['hour']:02d}:00", _num(r["temp"], 0), _num(r["feels"], 0), _precip_cell(r),
                 _num(r["cloud"], 0), _num(vis_km, 1), _wind_cell(r, lang), _num(r["gust"], 1),
                 _num(snow_cm, 0), tr(_sky_key(r["code"]), lang)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _max(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return max(values) if values else None


def _min(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return min(values) if values else None


def warnings_for(rows: list[dict], lang: str, source: str) -> list[PlanWarning]:
    th = THRESHOLDS
    out = []
    if source == "climate":
        out.append(PlanWarning("info", tr("w_warn_climate", lang)))
    if any(r.get("code") in _THUNDER_CODES for r in rows):
        out.append(PlanWarning("danger", tr("w_warn_thunder", lang)))
    if any(r.get("code") in _FOG_CODES or (r.get("vis_m") is not None and r["vis_m"] < th["fog_visibility_m"])
           for r in rows):
        out.append(PlanWarning("caution", tr("w_warn_fog", lang)))
    gust = _max(rows, "gust")
    if gust is not None and gust >= th["gust_caution"]:
        severity = "danger" if gust >= th["gust_danger"] else "caution"
        name = tr("gust_storm" if severity == "danger" else "gust_strong", lang)
        out.append(PlanWarning(severity, tr("w_warn_gust", lang, value=f"{gust:.0f}", label=name)))
    cold = _min(rows, "feels")
    if cold is not None and cold <= th["cold_caution"]:
        severity = "danger" if cold <= th["cold_danger"] else "caution"
        out.append(PlanWarning(severity, tr("w_warn_cold", lang, value=f"{cold:.0f}")))
    heat = _max(rows, "feels")
    if heat is not None and heat >= th["heat_caution"]:
        severity = "danger" if heat >= th["heat_danger"] else "caution"
        out.append(PlanWarning(severity, tr("w_warn_heat", lang, value=f"{heat:.0f}")))
    rain = _max(rows, "precip")
    if rain is not None and rain >= th["rain_caution"]:
        out.append(PlanWarning("caution", tr("w_warn_rain", lang, value=f"{rain:.1f}")))
    snow = _max(rows, "snow_m")
    if snow is not None and snow * 100.0 >= th["snow_cm"]:
        out.append(PlanWarning("info", tr("w_warn_snow", lang, value=f"{snow * 100.0:.0f}")))
    return out


class WeatherPlugin(SectionPlugin):
    plugin_id = "weather"
    section_id = "weather"

    def run(self, ctx, shared: dict) -> Section:
        lat, lon = ctx.centroid
        source = choose_source(ctx.date, ctx.today)
        try:
            rows, offset, fetched_at = _fetch(ctx, source, lat, lon)
        except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
            return Section("weather", tr("w_unavailable", ctx.lang, reason=str(e) or type(e).__name__),
                           "no-data")
        day = daytime_rows(rows, ctx.date, lat, lon, offset) or rows
        note_key = {"forecast": "w_source_forecast", "archive": "w_source_archive",
                    "climate": "w_source_climate"}[source]
        note = tr(note_key, ctx.lang, years=CLIMATE_YEARS) if source == "climate" else tr(note_key, ctx.lang)
        markdown = render_table(day, ctx.lang) + "\n\n*" + note + "*"
        means = [r["temp"] for r in rows if r.get("temp") is not None]
        return Section(
            "weather", markdown, "derived", sources=["https://open-meteo.com/"],
            warnings=warnings_for(day, ctx.lang, source),
            shared={"utc_offset_seconds": offset, "rows": rows, "daytime_rows": day, "source": source,
                    "fetched_at": fetched_at,
                    "daily_mean_temp": sum(means) / len(means) if means else None},
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_weather.py -q`
Expected: PASS (26 passed).

- [ ] **Step 5: Live check of the request parameters (one-off, needs internet)**

The tests use fakes, so confirm the real API accepts the requests once:

```bash
d=$(date -d "+1 day" +%F)
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.13&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,cloud_cover,visibility,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,snow_depth&wind_speed_unit=ms&timezone=auto&start_date=$d&end_date=$d" | head -c 700
curl -s "https://archive-api.open-meteo.com/v1/archive?latitude=51.5&longitude=-0.13&hourly=temperature_2m,apparent_temperature,precipitation,cloud_cover,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,snow_depth&wind_speed_unit=ms&timezone=auto&start_date=2024-01-10&end_date=2024-01-10" | head -c 700
```

Expected: JSON with `hourly` and `hourly_units` (`wind_speed_10m` in `m/s`, `visibility` and `snow_depth` in metres), no `"error": true`. Verified when this plan was written; note that `utc_offset_seconds` there is the offset of the moment of the request (a January archive date still returned the summer offset), which is why `utc_offset_for` reads the zone name instead.

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/day_plan/plugins/weather.py skills/osm-day-route-day-plan/tests/test_weather.py
git commit -m "Add hourly weather plugin (Open-Meteo forecast, archive, climatology)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Summary and service

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/summary.py`, `skills/osm-day-route-day-plan/scripts/day_plan/service.py`
- Test: `skills/osm-day-route-day-plan/tests/test_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: `build_summary_section(sections, lang) -> Section`; `run_plugins(ctx, plugins) -> (sections_in_registration_order, shared, failures)`; `assemble_markdown(ctx, sections, summary, fetched_at) -> str`; `build_plan(ctx, plugins) -> PlanResult(markdown, sections, failures)`. The file starts with `# <route name> — <date>`, then `<!-- day-plan fetched_at: <ISO Z> -->` (machine-readable, read by `osm-day-route-show`), then an italic metadata line.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_service.py`:

```python
import datetime

import pytest

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", depends_on=(), markdown="body", warnings=(),
                 confidence="derived", title=None, raises=False, shared=None):
        self.plugin_id, self.section_id, self.depends_on = plugin_id, section_id, tuple(depends_on)
        self._args = dict(markdown=markdown, warnings=list(warnings), confidence=confidence,
                          title=title, shared=shared or {})
        self._raises = raises
        self.seen_shared = None

    def run(self, ctx, shared):
        self.seen_shared = shared
        if self._raises:
            raise RuntimeError("boom")
        return Section(self.section_id, **self._args)


def _ctx(make_route, fixed_now, lang="en", departure=None, http=None, weather_response=None):
    http = http or (lambda url: weather_response())
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, departure=departure,
                         http=http, now=fixed_now)


def test_dependency_order_and_shared_data_are_passed(make_route, fixed_now):
    a = Stub("a", shared={"x": 1})
    b = Stub("b", depends_on=("a",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    run_plugins(ctx, [b, a])
    assert b.seen_shared == {"a": {"x": 1}}


def test_failing_plugin_becomes_no_data_and_others_still_run(make_route, fixed_now):
    good, bad = Stub("good"), Stub("bad", raises=True)
    dependent = Stub("dep", depends_on=("bad",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections, shared, failures = run_plugins(ctx, [bad, good, dependent])
    assert [s.confidence for s in sections] == ["no-data", "derived", "derived"]
    assert failures == [("bad", "RuntimeError: boom")]
    assert dependent.seen_shared == {}   # failed dependency is simply absent


def test_unregistered_dependency_is_ignored(make_route, fixed_now):
    p = Stub("p", depends_on=("missing",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections, _, failures = run_plugins(ctx, [p])
    assert failures == [] and len(sections) == 1


def test_dependency_cycle_raises(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    with pytest.raises(ValueError):
        run_plugins(ctx, [Stub("a", depends_on=("b",)), Stub("b", depends_on=("a",))])


def test_summary_sorts_by_severity_and_caps_at_five():
    warnings = [PlanWarning("info", f"i{i}") for i in range(4)] + [
        PlanWarning("danger", "D"), PlanWarning("caution", "C")]
    summary = build_summary_section([Section("hazards", "x", "derived", warnings=warnings)], "en")
    lines = summary.markdown.splitlines()
    assert len(lines) == 5
    assert lines[0] == "- **Danger:** D"
    assert lines[1] == "- **Caution:** C"


def test_summary_without_warnings_says_so_and_lists_no_data_sections():
    sections = [Section("light", "x", "derived"), Section("weather", "x", "no-data")]
    summary = build_summary_section(sections, "en")
    assert "No warnings for this date." in summary.markdown
    assert "Sections without data: Weather by hour." in summary.markdown


def test_summary_is_localized():
    summary = build_summary_section([Section("light", "x", "derived",
                                             warnings=[PlanWarning("danger", "т")])], "ru")
    assert summary.markdown == "- **Опасно:** т"


def test_full_plan_has_fixed_section_order_and_metadata(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, departure="Waterloo", weather_response=weather_response)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    lines = result.markdown.splitlines()
    assert lines[0] == "# Test route — 2026-06-21"
    assert lines[1] == "<!-- day-plan fetched_at: 2026-06-20T12:00:00Z -->"
    assert lines[2] == "*Forecast fetched 2026-06-20 12:00 UTC · Mode: walking · From: Waterloo*"
    headings = [l for l in lines if l.startswith("## ")]
    assert headings == ["## Summary", "## Daylight", "## Weather by hour"]
    assert result.failures == []


def test_group_with_several_plugins_gets_subheadings(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections = [Section("hazards", "one", title="Ticks"), Section("hazards", "two", title="Fire")]
    text = assemble_markdown(ctx, sections, Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## Hazards\n\n### Ticks\n\none\n\n### Fire\n\ntwo" in text


def test_metadata_uses_weather_fetch_time_not_run_time(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, weather_response=weather_response)
    stamp = datetime.datetime(2026, 6, 20, 7, 30, tzinfo=datetime.timezone.utc).timestamp()
    stub = Stub("weather", section_id="weather", shared={"fetched_at": stamp})
    result = build_plan(ctx, [stub])
    assert "fetched_at: 2026-06-20T07:30:00Z" in result.markdown


def test_russian_plan_headings(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, lang="ru", weather_response=weather_response)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    assert "## Главное на день" in result.markdown
    assert "## Световой день" in result.markdown
    assert "## Погода по часам" in result.markdown
    assert "Режим: пешком" in result.markdown


def test_weather_outage_does_not_break_the_plan(make_route, fixed_now):
    from day_plan.http import HttpError

    def http(url):
        raise HttpError("offline")

    ctx = _ctx(make_route, fixed_now, http=http)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    assert "estimated from longitude" in result.markdown       # light still works
    assert "Sections without data: Weather by hour." in result.markdown
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'day_plan.service'`.

- [ ] **Step 3: Write the implementation**

`skills/osm-day-route-day-plan/scripts/day_plan/summary.py`:

```python
"""The "Summary" section: the highest-severity warnings from every other
section, plus a list of sections that have no data. Built by the service
after all plugins ran (it needs their warnings), not a SectionPlugin."""
from .base import Section
from .i18n import tr

_SEVERITY_RANK = {"danger": 0, "caution": 1, "info": 2}
MAX_ITEMS = 5


def build_summary_section(sections: list, lang: str) -> Section:
    warnings = [w for s in sections for w in s.warnings]
    warnings.sort(key=lambda w: _SEVERITY_RANK.get(w.severity, 3))  # stable: keeps plugin order
    lines = [f"- **{tr('sev_' + w.severity, lang)}:** {w.text}" for w in warnings[:MAX_ITEMS]]
    if not lines:
        lines.append("- " + tr("summary_none", lang))
    missing = [s.title or tr("h_" + s.section_id, lang) for s in sections if s.confidence == "no-data"]
    if missing:
        lines.append("- " + tr("summary_no_data", lang, names=", ".join(missing)))
    return Section("summary", "\n".join(lines), "derived", warnings=[])
```

`skills/osm-day-route-day-plan/scripts/day_plan/service.py`:

```python
"""Runs the plugins in dependency order with per-plugin fault isolation
(same discipline as place_info.PlaceInfoService and
tile_providers.TileProviderService), then assembles the Markdown file."""
import datetime
from dataclasses import dataclass

from .base import SECTION_ORDER, Section
from .i18n import tr
from .summary import build_summary_section


@dataclass
class PlanResult:
    markdown: str
    sections: list
    failures: list  # [(plugin_id, reason)]


def _ordered(plugins: list) -> list:
    """Topological order; registration order breaks ties. A dependency that
    is not registered is ignored (the dependent handles its absence)."""
    registered = {p.plugin_id for p in plugins}
    done, order, remaining = set(), [], list(plugins)
    while remaining:
        progressed = False
        for plugin in list(remaining):
            deps = [d for d in plugin.depends_on if d in registered]
            if all(d in done for d in deps):
                order.append(plugin)
                done.add(plugin.plugin_id)
                remaining.remove(plugin)
                progressed = True
        if not progressed:
            raise ValueError("dependency cycle among plugins: " + ", ".join(p.plugin_id for p in remaining))
    return order


def run_plugins(ctx, plugins: list):
    """Returns (sections_in_registration_order, shared, failures)."""
    shared, failures, by_id = {}, [], {}
    for plugin in _ordered(plugins):
        deps = {d: shared[d] for d in plugin.depends_on if d in shared}
        try:
            section = plugin.run(ctx, deps)
        except Exception as e:  # noqa: BLE001 — isolate any plugin failure
            reason = f"{type(e).__name__}: {e}"
            failures.append((plugin.plugin_id, reason))
            section = Section(plugin.section_id, tr("plugin_failed", ctx.lang, reason=reason), "no-data")
        else:
            shared[plugin.plugin_id] = section.shared
        by_id[plugin.plugin_id] = section
    return [by_id[p.plugin_id] for p in plugins], shared, failures


def _fetched_at(ctx, shared: dict) -> datetime.datetime:
    stamp = (shared.get("weather") or {}).get("fetched_at")
    if stamp is None:
        return ctx.now
    return datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc)


def assemble_markdown(ctx, sections: list, summary: Section, fetched_at: datetime.datetime) -> str:
    lang = ctx.lang
    stamp = fetched_at.strftime("%Y-%m-%d %H:%M")
    mode = tr("mode_bike" if ctx.mode == "bike" else "mode_walk", lang)
    meta = tr("meta", lang, fetched=stamp, mode=mode)
    if ctx.departure:
        meta += tr("meta_from", lang, departure=ctx.departure)
    header = "\n".join([
        f"# {ctx.route_name} — {ctx.date_iso}",
        f"<!-- day-plan fetched_at: {fetched_at.strftime('%Y-%m-%dT%H:%M:%SZ')} -->",
        f"*{meta}*",
    ])
    parts = [
        header,
        f"## {tr('h_summary', lang)}\n\n{summary.markdown}",
    ]
    for section_id in SECTION_ORDER:
        if section_id == "summary":
            continue
        group = [s for s in sections if s.section_id == section_id]
        if not group:
            continue
        body = []
        for s in group:
            if len(group) > 1 and s.title:
                body.append(f"### {s.title}\n\n{s.markdown}")
            else:
                body.append(s.markdown)
        parts.append(f"## {tr('h_' + section_id, lang)}\n\n" + "\n\n".join(body))
    return "\n\n".join(parts) + "\n"


def build_plan(ctx, plugins: list) -> PlanResult:
    sections, shared, failures = run_plugins(ctx, plugins)
    summary = build_summary_section(sections, ctx.lang)
    markdown = assemble_markdown(ctx, sections, summary, _fetched_at(ctx, shared))
    return PlanResult(markdown=markdown, sections=sections, failures=failures)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (all tests so far, 68 passed).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/day_plan/summary.py skills/osm-day-route-day-plan/scripts/day_plan/service.py skills/osm-day-route-day-plan/tests/test_service.py
git commit -m "Add day-plan summary and service with plugin fault isolation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: CLI and SKILL.md

**Files:**
- Create: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`, `skills/osm-day-route-day-plan/SKILL.md`
- Test: `skills/osm-day-route-day-plan/tests/test_cli.py`

**Interfaces:**
- Consumes: `build_context`, `build_plan`, `WeatherPlugin`, `LightPlugin`, `get_json`.
- Produces: `main(argv, http=get_json, now=None, plugins=None) -> int`; `default_plugins()`; `coarse_departure(text) -> (value_or_None, was_dropped)`. Writes `<route_dir>/day-plan-<date>.md`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-day-plan/tests/test_cli.py`:

```python
import datetime

import build_day_plan


def test_cli_writes_plan_file_and_reports_path(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "en", "--departure", "Waterloo",
                                "--start", "09:00"], http=lambda url: weather_response(), now=fixed_now)
    assert code == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "From: Waterloo" in text
    assert "estimated finish 14:00" in text
    assert "wrote" in capsys.readouterr().out


def test_cli_overwrites_the_same_date_and_keeps_other_dates(make_route, weather_response, fixed_now):
    route_dir = make_route()
    http = lambda url: weather_response()  # noqa: E731
    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-22"], http=lambda url: weather_response(date="2026-06-22"),
                        now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=http, now=fixed_now)
    assert (route_dir / "day-plan-2026-06-22.md").exists()
    assert "Главное на день" in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")


def test_cli_drops_departure_that_looks_like_a_street_address(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21", "--departure", "Baker Street 221B"],
                        http=lambda url: weather_response(), now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "Baker" not in text and "From:" not in text
    assert "street address" in capsys.readouterr().err


def test_coarse_departure_keeps_plain_city_or_station():
    assert build_day_plan.coarse_departure("  Madrid, Atocha ") == ("Madrid, Atocha", False)
    assert build_day_plan.coarse_departure(None) == (None, False)


def test_cli_rejects_bad_date_and_missing_route(make_route, tmp_path, capsys):
    assert build_day_plan.main([str(make_route()), "21-06-2026"]) == 1
    assert build_day_plan.main([str(tmp_path / "nope"), "2026-06-21"]) == 1
    assert "not found" in capsys.readouterr().err


def test_plan_written_by_cli_is_found_by_glob_used_in_show(make_route, weather_response, fixed_now):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: weather_response(), now=fixed_now)
    assert [p.name for p in route_dir.glob("day-plan-????-??-??.md")] == ["day-plan-2026-06-21.md"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_day_plan'`.

- [ ] **Step 3: Write the implementation and the skill document**

`skills/osm-day-route-day-plan/scripts/build_day_plan.py`:

```python
#!/usr/bin/env python3
"""Build day-plan-<YYYY-MM-DD>.md for a saved route.

Standard-library only. Usage:
    python3 build_day_plan.py <route_dir> <YYYY-MM-DD>
        [--lang <ISO 639-1>] [--departure "<city or station>"] [--start HH:MM]

--departure is written into the file, and the file is meant to be forwarded
(it is embedded in map.html), so pass a city, station or stop — never a street
address. A value containing digits is treated as a possible address and is
NOT written.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

from day_plan.context import build_context
from day_plan.http import get_json
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import build_plan


def default_plugins() -> list:
    return [WeatherPlugin(), LightPlugin()]


def coarse_departure(text: str | None) -> tuple[str | None, bool]:
    """(value_to_write, was_dropped). Digits suggest a street address."""
    if not text:
        return None, False
    if re.search(r"\d", text):
        return None, True
    return text.strip(), False


def main(argv=None, http=get_json, now=None, plugins=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route_dir")
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--departure", default=None)
    parser.add_argument("--start", default=None, help="planned start time HH:MM")
    args = parser.parse_args(argv)

    route_dir = Path(args.route_dir)
    if not (route_dir / "route.geojson").exists():
        print(f"error: {route_dir / 'route.geojson'} not found", file=sys.stderr)
        return 1
    try:
        date = datetime.date.fromisoformat(args.date)
        start = datetime.time.fromisoformat(args.start) if args.start else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    departure, dropped = coarse_departure(args.departure)
    if dropped:
        print("warning: --departure looks like a street address (contains digits); it was NOT "
              "written to the plan. Pass a city, station or stop.", file=sys.stderr)

    ctx = build_context(route_dir, date, lang=args.lang, departure=departure, start_time=start,
                        http=http, now=now)
    result = build_plan(ctx, plugins if plugins is not None else default_plugins())
    out = route_dir / f"day-plan-{date.isoformat()}.md"
    out.write_text(result.markdown, encoding="utf-8")
    print(f"wrote {out.resolve()}")
    for plugin_id, reason in result.failures:
        print(f"warning: plugin {plugin_id} failed: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`skills/osm-day-route-day-plan/SKILL.md`:

````markdown
---
name: osm-day-route-day-plan
description: Use when the user wants a briefing for a specific date for a route already saved by osm-day-route-planning (a routes/<slug>-<date>/ folder with route.geojson) — sunrise/sunset and daylight, hourly weather (wind speed and direction, precipitation, temperature, cloud/fog, snow cover) — or asks "what will the weather/daylight be on <date>", "план на день", "когда рассвет и закат", "погода по часам".
---

# OSM Day Route Day Plan

## Overview

Turns a saved route plus a date into `day-plan-<YYYY-MM-DD>.md` in the route
folder. `osm-day-route-show` embeds every such file into `map.html` (sidebar
summary, full-plan panel, `.md` download, print to PDF), so the single map
file can be forwarded with all planned days inside.

Design: `docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md`.
This skill currently implements the **light** (sunrise, sunset, day length,
margin to the route's finish) and **weather** (hourly) sections and the
**summary**. Transit and opening hours, hazards (ticks, biting insects,
mountains, air, radiation, fire) and mobile coverage are separate follow-up
plans; until they exist the plan simply has no such sections — never invent
them by hand.

Every script is **stdlib-only** (`urllib.request`/`json`/`zoneinfo`), no API
keys, same rule as the other two skills.

## When to Use

- A route exists in `routes/` and the user names a date (or asks about
  "tomorrow", "Saturday" — convert to `YYYY-MM-DD` first).
- The user asks for sunrise/sunset, day length, or hourly weather for a route.

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
3. Optional `--start HH:MM` if the person gave a start time; otherwise the
   plan reports the latest start that still ends 60 minutes before sunset.
4. Run (from this skill's `scripts/` directory):
   ```bash
   python3 build_day_plan.py <route_dir> <YYYY-MM-DD> \
       --lang <ISO 639-1 of the person's language> \
       [--departure "<city or station>"] [--start HH:MM]
   ```
   Re-running for the same date overwrites that date's file; other dates are
   kept. Network results are cached in `<route_dir>/day_plan_cache.json`
   (forecasts for 3 hours).
5. Report the file path and read the **Summary** section back to the person.
   If the plan shows the route does not fit the day (finish after sunset,
   thunderstorm), say so and offer to go back to osm-day-route-planning —
   this skill never changes the route.
6. Offer to re-render the map so the new date is inside it:
   `python3 ../../osm-day-route-show/scripts/render_map.py <route_dir> --user-lang <code>`.
   A `map.html` is a snapshot; a plan added later does not appear until it is
   re-rendered. Tell the person which dates the map will contain.

## Confidence and honesty

Sections carry a tier like the rest of the project: light and weather are
`derived` (computed / model output). A forecast is only as good as its
horizon: beyond 15 days the weather table is a **climatology** (average of
the same date over five previous years) and says so in the file. A section
that could not be built says `no data` — report that plainly.

## Limitations

- Body text of the light/weather sections is translated for English and
  Russian; other languages get English body text (headings, metadata and
  severity labels are localized in all seven languages).
- Open-Meteo applies no elevation correction to wind: ridge gusts are likely
  underestimated.
- Pollen, radiation, fire danger, insects, mountain hazards, transit and
  mobile coverage are not in this version.

## Common Mistakes

- Writing a street address as the departure point (it ends up in a forwarded file).
- Editing `day-plan-*.md` by hand and forgetting that re-running the script
  overwrites the file.
- Forgetting to re-render `map.html` after adding a plan.
````

- [ ] **Step 4: Run the whole suite**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests -q`
Expected: PASS (74 passed).

- [ ] **Step 5: Smoke test against the real API (needs internet)**

Use an existing archive folder (or create a minimal `route.geojson` with one LineString feature) and a date within two weeks:

```bash
cd skills/osm-day-route-day-plan/scripts
python3 build_day_plan.py ../../../routes/<some-route> $(date -d "+2 days" +%F) --lang en --departure "Madrid" --start 09:00
```

Expected: `wrote .../day-plan-<date>.md`; the file starts with the `# ... — <date>` heading, has `## Summary`, `## Daylight`, `## Weather by hour` with a table of hourly rows, and a source line. If `routes/` has no archive, use a temporary folder with a minimal route.

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-day-plan/scripts/build_day_plan.py skills/osm-day-route-day-plan/SKILL.md skills/osm-day-route-day-plan/tests/test_cli.py
git commit -m "Add build_day_plan CLI and SKILL.md

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Show skill — day-plan view module

**Files:**
- Create: `skills/osm-day-route-show/scripts/day_plan_view.py`
- Modify: `skills/osm-day-route-show/scripts/render_map.py` (import and string/alias merge only)
- Test: `skills/osm-day-route-show/tests/test_day_plan_view.py`

**Interfaces:**
- Consumes: `t`, `SECTION_ALIASES`, `extract_md_section` from `render_map` (tests only).
- Produces (`day_plan_view`): `load_day_plans(route_dir) -> list[RawPlan(date, markdown, fetched_at)]` (sorted by date, HTML comments stripped, BOM and CRLF tolerated, impossible dates skipped); `default_plan_index(dates, today) -> int`; `DAY_PLAN_UI` (seven languages), `DAY_PLAN_SUMMARY_HEADINGS`; `DAY_PLAN_CSS`; `build_day_plan_parts(plans, labels, file_base, today) -> (sidebar_html, overlay_html, script_js)` where each plan dict has `date, md, html, summary_html, fetched_at`. `render_map` gains `t("day_plan_*")` keys and `SECTION_ALIASES["day_plan_summary"]`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-show/tests/test_day_plan_view.py`:

```python
import json

from day_plan_view import (
    DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI, build_day_plan_parts, default_plan_index, load_day_plans,
)
from render_map import SECTION_ALIASES, extract_md_section, t

PLAN = (
    "# Route — 2026-06-21\n<!-- day-plan fetched_at: 2026-06-20T12:00:00Z -->\n*Meta*\n\n"
    "## Summary\n\n- **Danger:** storm\n\n## Daylight\n\n- Sunrise **04:43**\n"
)


def _write(route_dir, date, text=PLAN):
    (route_dir / f"day-plan-{date}.md").write_text(text, encoding="utf-8")


def _labels(lang="en"):
    return {key: t(key, lang) for key in DAY_PLAN_UI["en"]}


def _plan_dict(date="2026-06-21", md="# T\n"):
    return {"date": date, "md": md, "html": "<h2>T</h2>", "summary_html": "<ul><li>x</li></ul>",
            "fetched_at": "2026-06-20T12:00:00Z"}


def test_load_returns_plans_sorted_by_date_with_comments_stripped(tmp_path):
    _write(tmp_path, "2026-06-23")
    _write(tmp_path, "2026-06-21")
    plans = load_day_plans(tmp_path)
    assert [p.date for p in plans] == ["2026-06-21", "2026-06-23"]
    assert "<!--" not in plans[0].markdown
    assert plans[0].fetched_at == "2026-06-20T12:00:00Z"


def test_load_skips_impossible_dates_other_files_and_unreadable_files(tmp_path):
    _write(tmp_path, "2026-13-45")
    (tmp_path / "day-plan-notes.md").write_text("x", encoding="utf-8")
    (tmp_path / "day-plan-2026-06-21.facts.json").write_text("{}", encoding="utf-8")
    (tmp_path / "day-plan-2026-06-22.md").write_bytes(b"\xff\xfe\x00bad")
    _write(tmp_path, "2026-06-24")
    assert [p.date for p in load_day_plans(tmp_path)] == ["2026-06-24"]


def test_load_with_no_plans_is_empty(tmp_path):
    assert load_day_plans(tmp_path) == []


def test_default_index_is_nearest_upcoming_else_latest():
    dates = ["2026-06-10", "2026-06-21", "2026-06-30"]
    assert default_plan_index(dates, "2026-06-15") == 1
    assert default_plan_index(dates, "2026-06-21") == 1
    assert default_plan_index(dates, "2026-06-01") == 0
    assert default_plan_index(dates, "2026-07-15") == 2
    assert default_plan_index([], "2026-06-15") == 0


def test_summary_aliases_find_the_section_in_every_language():
    for heading in DAY_PLAN_SUMMARY_HEADINGS:
        md = f"# T\n\n## {heading}\n\n- one\n\n## Other\n\n- two\n"
        assert extract_md_section(md, "day_plan_summary") == "- one", heading


def test_aliases_are_registered_and_ui_strings_exist_in_all_languages():
    assert SECTION_ALIASES["day_plan_summary"] == DAY_PLAN_SUMMARY_HEADINGS
    for lang in ("en", "ru", "es", "fr", "de", "pt", "it"):
        assert t("day_plan_open", lang) == DAY_PLAN_UI[lang]["day_plan_open"]
    assert t("day_plan_title", "xx") == "Day plan"   # English fallback


def test_no_plans_gives_placeholder_and_no_overlay():
    sidebar, overlay, script = build_day_plan_parts([], _labels(), "Route", "2026-06-21")
    assert "No day plan yet" in sidebar
    assert overlay == ""
    assert script == "const DAY_PLANS = [];"


def test_single_plan_shows_date_text_not_a_select():
    sidebar, overlay, script = build_day_plan_parts([_plan_dict()], _labels(), "Route", "2026-06-21")
    assert "<select" not in sidebar
    assert "2026-06-21" in sidebar
    assert 'id="dp-open"' in sidebar
    assert 'id="dp-overlay" hidden' in overlay


def test_several_plans_give_a_date_select_and_all_are_embedded():
    plans = [_plan_dict("2026-06-21"), _plan_dict("2026-06-23", md="# Other\n")]
    sidebar, overlay, script = build_day_plan_parts(plans, _labels(), "Route", "2026-06-22")
    assert sidebar.count("<option") == 2
    assert "let current = 1;" in script          # nearest upcoming date
    payload = json.loads(script.split("const DAY_PLANS = ")[1].split(";\n  const DP_LABELS")[0])
    assert [p["date"] for p in payload] == ["2026-06-21", "2026-06-23"]
    assert payload[1]["md"] == "# Other\n"


def test_toolbar_has_download_print_and_close_and_localized_labels():
    _, overlay, _ = build_day_plan_parts([_plan_dict()], _labels("ru"), "Route", "2026-06-21")
    assert 'id="dp-download"' in overlay and "Скачать .md" in overlay
    assert 'id="dp-print"' in overlay and "Печать / сохранить в PDF" in overlay
    assert 'id="dp-close"' in overlay


def test_plan_text_cannot_break_out_of_the_script_tag():
    md = "# T\n</script><script>alert(1)</script>\n"
    _, _, script = build_day_plan_parts([_plan_dict(md=md)], _labels(), "Route", "2026-06-21")
    assert "</script>" not in script


def test_plan_saved_with_a_bom_and_crlf_line_endings_still_loads_cleanly(tmp_path):
    (tmp_path / "day-plan-2026-06-21.md").write_bytes(("\ufeff" + PLAN.replace("\n", "\r\n")).encode("utf-8"))
    plan = load_day_plans(tmp_path)[0]
    assert plan.markdown.startswith("# Route")
    assert "\r" not in plan.markdown
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests/test_day_plan_view.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'day_plan_view'`.

- [ ] **Step 3: Write the module**

`skills/osm-day-route-show/scripts/day_plan_view.py`:

```python
"""Embedding of day-plan-<date>.md files (written by osm-day-route-day-plan)
into map.html: loading, the sidebar block, the full-plan overlay, and its
small script and print CSS. No imports from render_map — the caller passes
already-rendered HTML — so there is no import cycle.

Design: docs/superpowers/specs/2026-09-29-osm-day-route-day-plan-design.md
("Integration into osm-day-route-show")."""
import datetime
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

_FILE_RE = re.compile(r"^day-plan-(\d{4}-\d{2}-\d{2})\.md$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FETCHED_RE = re.compile(r"<!--\s*day-plan fetched_at:\s*(\S+)\s*-->")

# Headings osm-day-route-day-plan writes for its first section (its i18n
# h_summary in each language) — must stay in sync with that skill.
DAY_PLAN_SUMMARY_HEADINGS = [
    "Summary", "Главное на день", "Resumen del día", "L'essentiel du jour",
    "Das Wichtigste", "Resumo do dia", "In breve",
]

DAY_PLAN_UI = {
    "en": {
        "day_plan_title": "Day plan", "day_plan_open": "Open full plan",
        "day_plan_download": "Download .md", "day_plan_print": "Print / save as PDF",
        "day_plan_none": "No day plan yet — ask Claude to plan a specific date",
        "day_plan_fetched": "Forecast fetched", "day_plan_passed": "date has passed",
        "day_plan_close": "Close", "day_plan_date": "Date",
    },
    "ru": {
        "day_plan_title": "План дня", "day_plan_open": "Открыть полный план",
        "day_plan_download": "Скачать .md", "day_plan_print": "Печать / сохранить в PDF",
        "day_plan_none": "Плана дня пока нет — попросите спланировать конкретную дату",
        "day_plan_fetched": "Прогноз получен", "day_plan_passed": "дата прошла",
        "day_plan_close": "Закрыть", "day_plan_date": "Дата",
    },
    "es": {
        "day_plan_title": "Plan del día", "day_plan_open": "Abrir plan completo",
        "day_plan_download": "Descargar .md", "day_plan_print": "Imprimir / guardar como PDF",
        "day_plan_none": "Aún no hay plan del día — pide planificar una fecha concreta",
        "day_plan_fetched": "Previsión obtenida", "day_plan_passed": "la fecha ya pasó",
        "day_plan_close": "Cerrar", "day_plan_date": "Fecha",
    },
    "fr": {
        "day_plan_title": "Plan du jour", "day_plan_open": "Ouvrir le plan complet",
        "day_plan_download": "Télécharger .md", "day_plan_print": "Imprimer / enregistrer en PDF",
        "day_plan_none": "Pas encore de plan du jour — demandez de planifier une date précise",
        "day_plan_fetched": "Prévision récupérée", "day_plan_passed": "date passée",
        "day_plan_close": "Fermer", "day_plan_date": "Date",
    },
    "de": {
        "day_plan_title": "Tagesplan", "day_plan_open": "Vollständigen Plan öffnen",
        "day_plan_download": ".md herunterladen", "day_plan_print": "Drucken / als PDF speichern",
        "day_plan_none": "Noch kein Tagesplan – bitte ein bestimmtes Datum planen lassen",
        "day_plan_fetched": "Vorhersage abgerufen", "day_plan_passed": "Datum liegt in der Vergangenheit",
        "day_plan_close": "Schließen", "day_plan_date": "Datum",
    },
    "pt": {
        "day_plan_title": "Plano do dia", "day_plan_open": "Abrir plano completo",
        "day_plan_download": "Transferir .md", "day_plan_print": "Imprimir / guardar como PDF",
        "day_plan_none": "Ainda não há plano do dia — peça para planear uma data concreta",
        "day_plan_fetched": "Previsão obtida", "day_plan_passed": "a data já passou",
        "day_plan_close": "Fechar", "day_plan_date": "Data",
    },
    "it": {
        "day_plan_title": "Piano del giorno", "day_plan_open": "Apri il piano completo",
        "day_plan_download": "Scarica .md", "day_plan_print": "Stampa / salva come PDF",
        "day_plan_none": "Nessun piano del giorno — chiedi di pianificare una data precisa",
        "day_plan_fetched": "Previsione ottenuta", "day_plan_passed": "data trascorsa",
        "day_plan_close": "Chiudi", "day_plan_date": "Data",
    },
}


@dataclass
class RawPlan:
    date: str  # YYYY-MM-DD
    markdown: str  # HTML comments stripped
    fetched_at: str | None  # ISO timestamp from the file's machine-readable comment


def load_day_plans(route_dir) -> list[RawPlan]:
    """Every day-plan-YYYY-MM-DD.md in the folder, oldest date first.
    Unreadable files and names with an impossible date are skipped."""
    plans = []
    for path in sorted(Path(route_dir).glob("day-plan-*.md")):
        match = _FILE_RE.match(path.name)
        if not match:
            continue
        try:
            datetime.date.fromisoformat(match.group(1))
            text = path.read_text(encoding="utf-8-sig")  # tolerate a BOM from hand-edited files
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        fetched = _FETCHED_RE.search(text)
        plans.append(RawPlan(match.group(1), _COMMENT_RE.sub("", text).strip() + "\n",
                             fetched.group(1) if fetched else None))
    plans.sort(key=lambda p: p.date)
    return plans


def default_plan_index(dates: list[str], today: str) -> int:
    """Index of the nearest upcoming date (today included); the latest date
    when every plan is in the past. `dates` is sorted ascending."""
    for i, d in enumerate(dates):
        if d >= today:
            return i
    return max(len(dates) - 1, 0)


DAY_PLAN_CSS = """
  #sidebar .dp-summary ul { margin: 4px 0; }
  #sidebar .dp-btn, #dp-panel .dp-btn {
    display: inline-block; padding: 4px 10px; margin: 4px 4px 0 0; font: inherit; font-size: 13px;
    color: #1f2937; background: #f3f4f6; border: 1px solid #9ca3af; border-radius: 6px;
    text-decoration: none; cursor: pointer;
  }
  #dp-overlay { position: fixed; inset: 0; z-index: 3000; background: rgba(0,0,0,0.45);
    display: flex; justify-content: center; }
  #dp-overlay[hidden] { display: none; }
  #dp-panel { background: #fff; width: 100%; max-width: 1100px; height: 100%; overflow-y: auto;
    box-sizing: border-box; padding: 12px 18px 24px; font-size: 14px; line-height: 1.45; }
  #dp-toolbar { position: sticky; top: -12px; background: #fff; padding: 8px 0; margin-top: -12px;
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center; border-bottom: 1px solid #e5e7eb; }
  #dp-heading { font-weight: 600; font-size: 16px; margin-right: 8px; }
  #dp-meta { color: #6b7280; font-size: 12px; flex: 1 1 200px; }
  #dp-body h2 { font-size: 18px; margin: 16px 0 6px; }
  #dp-body h3 { font-size: 16px; margin: 14px 0 6px; border-bottom: 1px solid #e5e7eb; }
  #dp-body h4 { font-size: 14px; margin: 10px 0 4px; }
  #dp-body .table-wrap { overflow-x: auto; margin: 4px 0 10px; }
  #dp-body table { border-collapse: collapse; width: 100%; font-size: 12px; }
  #dp-body th, #dp-body td { border: 1px solid #d1d5db; padding: 3px 6px; text-align: left; vertical-align: top; }
  #dp-body th { background: #f3f4f6; white-space: nowrap; }
  #dp-body a { color: #2563eb; }
  @media print {
    body > *:not(#dp-overlay) { display: none !important; }
    #dp-overlay { position: static; display: block; background: none; }
    #dp-panel { max-width: none; height: auto; overflow: visible; padding: 0; }
    #dp-toolbar { display: none; }
    #dp-body tr, #dp-body h2, #dp-body h3 { break-inside: avoid; page-break-inside: avoid; }
    #dp-body .table-wrap { overflow: visible; }
    #dp-body table { font-size: 10px; }
  }
"""

_SCRIPT_TEMPLATE = """
  const DAY_PLANS = __PLANS__;
  const DP_LABELS = __LABELS__;
  const DP_FILE_BASE = __FILE_BASE__;
  (function () {
    if (!DAY_PLANS.length) return;
    const $ = id => document.getElementById(id);
    const select = $('dp-select');
    let current = __DEFAULT__;
    function isPassed(plan) { return new Date(plan.date + 'T23:59:59') < new Date(); }
    function show(i) {
      current = i;
      const plan = DAY_PLANS[i];
      $('dp-summary').innerHTML = plan.summary_html;
      $('dp-heading').textContent = DP_LABELS.title + ' — ' + plan.date;
      const parts = [];
      if (plan.fetched_at) parts.push(DP_LABELS.fetched + ': ' + plan.fetched_at.replace('T', ' ').replace('Z', ' UTC'));
      if (isPassed(plan)) parts.push(DP_LABELS.passed);
      $('dp-meta').textContent = parts.join(' · ');
      $('dp-body').innerHTML = plan.html;
      const link = $('dp-download');
      link.href = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(plan.md);
      link.download = DP_FILE_BASE + '-day-plan-' + plan.date + '.md';
      if (select) select.value = String(i);
    }
    function openPanel() { $('dp-overlay').hidden = false; $('dp-panel').scrollTop = 0; }
    function closePanel() { $('dp-overlay').hidden = true; }
    if (select) select.addEventListener('change', () => show(Number(select.value)));
    $('dp-open').addEventListener('click', openPanel);
    $('dp-close').addEventListener('click', closePanel);
    $('dp-print').addEventListener('click', () => window.print());
    $('dp-overlay').addEventListener('click', e => { if (e.target === $('dp-overlay')) closePanel(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });
    show(current);
  })();
"""


def _json_for_script(value) -> str:
    # "</" would let a plan's text end the inline <script> early; \/ is the
    # same string to a JSON parser.
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def build_day_plan_parts(plans: list[dict], labels: dict, file_base: str, today: str) -> tuple[str, str, str]:
    """(sidebar_html, overlay_html, script_js). Each plan dict has: date,
    md (raw markdown), html (full plan as HTML), summary_html, fetched_at.
    `labels` has the localized UI strings under their day_plan_* names."""
    title = html.escape(labels["day_plan_title"])
    if not plans:
        sidebar = f'<h3>{title}</h3><p><em>{html.escape(labels["day_plan_none"])}</em></p>'
        return sidebar, "", "const DAY_PLANS = [];"

    default = default_plan_index([p["date"] for p in plans], today)
    if len(plans) > 1:
        options = "".join(f'<option value="{i}">{html.escape(p["date"])}</option>' for i, p in enumerate(plans))
        chooser = (f'<label>{html.escape(labels["day_plan_date"])}: '
                   f'<select id="dp-select">{options}</select></label>')
    else:
        chooser = f'<p>{html.escape(plans[0]["date"])}</p>'
    sidebar = (
        f'<h3>{title}</h3><div id="dp-block">{chooser}<div id="dp-summary" class="dp-summary"></div>'
        f'<button id="dp-open" class="dp-btn" type="button">{html.escape(labels["day_plan_open"])}</button></div>'
    )
    overlay = (
        '<div id="dp-overlay" hidden><div id="dp-panel" role="dialog" aria-modal="true" aria-labelledby="dp-heading">'
        '<div id="dp-toolbar"><span id="dp-heading"></span><span id="dp-meta"></span>'
        f'<a id="dp-download" class="dp-btn" href="#">{html.escape(labels["day_plan_download"])}</a>'
        f'<button id="dp-print" class="dp-btn" type="button">{html.escape(labels["day_plan_print"])}</button>'
        f'<button id="dp-close" class="dp-btn" type="button">{html.escape(labels["day_plan_close"])}</button></div>'
        '<div id="dp-body"></div></div></div>'
    )
    payload = [{"date": p["date"], "md": p["md"], "html": p["html"], "summary_html": p["summary_html"],
                "fetched_at": p["fetched_at"]} for p in plans]
    js_labels = {"title": labels["day_plan_title"], "fetched": labels["day_plan_fetched"],
                 "passed": labels["day_plan_passed"]}
    script = (_SCRIPT_TEMPLATE
              .replace("__PLANS__", _json_for_script(payload))
              .replace("__LABELS__", _json_for_script(js_labels))
              .replace("__FILE_BASE__", _json_for_script(file_base))
              .replace("__DEFAULT__", str(default)))
    return sidebar, overlay, script
```

- [ ] **Step 4: Wire the strings and aliases into `render_map.py`**

In `skills/osm-day-route-show/scripts/render_map.py`:

**Replace:**

```python
from tile_providers import TileProviderService
```

**With:**

```python
from day_plan_view import DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI
from tile_providers import TileProviderService
```

**Replace:**

```python
def t(key: str, lang: str) -> str:
    """UI string for `key` in `lang`, falling back to English."""
```

**With:**

```python
for _lang, _strings in DAY_PLAN_UI.items():
    UI_STRINGS[_lang].update(_strings)
SECTION_ALIASES["day_plan_summary"] = list(DAY_PLAN_SUMMARY_HEADINGS)


def t(key: str, lang: str) -> str:
    """UI string for `key` in `lang`, falling back to English."""
```

- [ ] **Step 5: Run the whole show suite**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests -q`
Expected: PASS (existing tests plus 12 new ones).

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-show/scripts/day_plan_view.py skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_day_plan_view.py
git commit -m "Add day-plan view module for map.html

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Show skill — whole-file Markdown converter

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Test: `skills/osm-day-route-show/tests/test_plan_markdown_to_html.py`

**Interfaces:**
- Consumes: existing `_inline_markdown`, `_xml_escape`, `_render_table`, `_TABLE_SEPARATOR_ROW`, `_LIST_MARKER`.
- Produces: `plan_markdown_to_html(md_text) -> str` (`#`/`##`/`###` become `h2`/`h3`/`h4`; paragraphs; lists; tables; inline link, bold, italic, code; everything HTML-escaped first). `markdown_to_html` is left unchanged.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-show/tests/test_plan_markdown_to_html.py`:

```python
from render_map import plan_markdown_to_html


def test_headings_become_h2_h3_h4():
    html = plan_markdown_to_html("# Title\n\n## Section\n\n### Sub")
    assert "<h2>Title</h2>" in html
    assert "<h3>Section</h3>" in html
    assert "<h4>Sub</h4>" in html


def test_plain_lines_are_paragraphs_not_list_items():
    html = plan_markdown_to_html("first line\nsecond line\n\nnext paragraph")
    assert html == "<p>first line second line</p><p>next paragraph</p>"


def test_lists_and_wrapped_list_items():
    html = plan_markdown_to_html("- one\n  continued\n- two\n\n1. a\n2. b")
    assert html == "<ul><li>one continued</li><li>two</li></ul><ul><li>a</li><li>b</li></ul>"


def test_italic_bold_code_and_links():
    html = plan_markdown_to_html("*note* and **bold** and `x` [site](https://e.com)")
    assert "<i>note</i>" in html and "<b>bold</b>" in html and "<code>x</code>" in html
    assert '<a href="https://e.com" target="_blank" rel="noopener">site</a>' in html


def test_bold_is_not_mistaken_for_italic():
    assert plan_markdown_to_html("**Danger:** text") == "<p><b>Danger:</b> text</p>"


def test_tables_render_with_wrapper():
    html = plan_markdown_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
    assert '<div class="table-wrap"><table>' in html
    assert "<th>A</th>" in html and "<td>2</td>" in html


def test_table_directly_after_heading_and_before_paragraph():
    html = plan_markdown_to_html("### T\n| A |\n|---|\n| 1 |\n\n*src*")
    assert html.index("<h4>") < html.index("<table>") < html.index("<i>src</i>")


def test_html_in_plan_text_is_escaped():
    html = plan_markdown_to_html("## <script>alert(1)</script>\n\n- <img src=x onerror=y>")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_empty_input():
    assert plan_markdown_to_html("") == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests/test_plan_markdown_to_html.py -q`
Expected: FAIL with `ImportError: cannot import name 'plan_markdown_to_html' from 'render_map'`.

- [ ] **Step 3: Add the converter**

In `skills/osm-day-route-show/scripts/render_map.py`, insert the functions just before the place-info section banner:

**Replace:**

```python
# ---------------------------------------------------------------------------
# Place-info enrichment (spec §5): queries every configured plugin
```

**With:**

```python
_PLAN_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def _plan_inline(text: str) -> str:
    """_inline_markdown plus *italic* (day plans use it for the metadata and
    source lines). Bold is converted first, so a remaining single * pair is
    italic."""
    text = _inline_markdown(_xml_escape(text))
    return re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<i>\1</i>", text)


def plan_markdown_to_html(md_text: str) -> str:
    """Markdown -> HTML for a whole day-plan file: '#'/'##'/'###' headings
    (rendered as h2/h3/h4), paragraphs, '- '/'1. ' lists, GFM tables, and
    inline links/bold/italic/code. markdown_to_html deliberately stays as it
    is for notes.md sections: it has no headings and turns bare lines into
    list items, which would mangle a plan."""
    lines = md_text.split("\n")
    out, items, paragraph = [], [], []
    current = None
    i = 0

    def flush_paragraph():
        if paragraph:
            out.append("<p>" + _plan_inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_list():
        nonlocal current
        if current is not None:
            items.append(current)
            current = None
        if items:
            out.append("<ul>" + "".join(f"<li>{_plan_inline(item)}</li>" for item in items) + "</ul>")
            items.clear()

    while i < len(lines):
        line = lines[i].strip()

        if "|" in line and i + 1 < len(lines) and _TABLE_SEPARATOR_ROW.match(lines[i + 1].strip()):
            flush_paragraph()
            flush_list()
            table_rows = [line, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                table_rows.append(lines[i].strip())
                i += 1
            out.append(_render_table(table_rows))
            continue

        heading = _PLAN_HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1)) + 1
            out.append(f"<h{level}>{_plan_inline(heading.group(2))}</h{level}>")
        elif _LIST_MARKER.match(line):
            flush_paragraph()
            if current is not None:
                items.append(current)
            current = line[_LIST_MARKER.match(line).end():]
        elif not line:
            flush_paragraph()
            flush_list()
        elif current is not None:
            current = f"{current} {line}"
        else:
            paragraph.append(line)
        i += 1

    flush_paragraph()
    flush_list()
    return "".join(out)


# ---------------------------------------------------------------------------
# Place-info enrichment (spec §5): queries every configured plugin
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests -q`
Expected: PASS (all, including 9 new).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_plan_markdown_to_html.py
git commit -m "Add plan_markdown_to_html for whole day-plan files

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Show skill — embed plans in map.html

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py` (`build_map_html`)
- Test: `skills/osm-day-route-show/tests/test_day_plan_embed.py`

**Interfaces:**
- Consumes: `load_day_plans`, `build_day_plan_parts`, `DAY_PLAN_CSS`, `DAY_PLAN_UI` (Task 7); `plan_markdown_to_html` (Task 8); existing `markdown_to_html`, `extract_md_section`, `t`.
- Produces: `build_map_html` output with, between the Points-of-interest block and the Export block, a "Day plan" sidebar block; a full-plan overlay; a second inline `<script>` holding `DAY_PLANS`; print CSS. No plan files -> placeholder block and `const DAY_PLANS = [];`.

- [ ] **Step 1: Write the failing tests**

`skills/osm-day-route-show/tests/test_day_plan_embed.py`:

```python
import json
import re

from render_map import build_map_html

GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-3.75, 40.42, 600.0], [-3.74, 40.43, 640.0]]},
        "properties": {"name": "Casa de Campo", "mode": "walk", "distance_km": 3.0,
                       "elevation_gain_m": 40, "elevation_loss_m": 0, "duration_estimate_hours": 1.0},
    }],
}


def _route(tmp_path, plans=None):
    (tmp_path / "route.geojson").write_text(json.dumps(GEOJSON), encoding="utf-8")
    (tmp_path / "notes.md").write_text("## Access\n\n- Metro\n\n## Points of interest\n\n- Lake\n", encoding="utf-8")
    for date, text in (plans or {}).items():
        (tmp_path / f"day-plan-{date}.md").write_text(text, encoding="utf-8")
    return tmp_path


def _plan(date, storm="storm"):
    return (f"# Casa de Campo — {date}\n<!-- day-plan fetched_at: {date}T06:00:00Z -->\n*Meta*\n\n"
            f"## Summary\n\n- **Danger:** {storm}\n\n## Weather by hour\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")


def _build(route_dir, lang="en"):
    return build_map_html(route_dir / "route.geojson", route_dir / "notes.md", title="Casa de Campo",
                          user_lang=lang, resolve_wiki=False, tile_timeout=0.1)


def test_map_without_plans_shows_placeholder_block_between_poi_and_export(tmp_path):
    html = _build(_route(tmp_path))
    assert "No day plan yet" in html
    assert "const DAY_PLANS = [];" in html
    assert html.index("<h3>Points of interest</h3>") < html.index("<h3>Day plan</h3>") \
        < html.index("<h3>Export & open elsewhere</h3>")


def test_map_embeds_every_plan_so_the_file_can_be_forwarded(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21", "storm A"),
                              "2026-06-28": _plan("2026-06-28", "storm B")})
    html = _build(route)
    assert html.count('<option value=') == 2
    assert "storm A" in html and "storm B" in html
    # embedded raw markdown for download, and rendered HTML for the panel
    assert "## Weather by hour" in html
    assert "<table>" in html


def test_map_has_download_print_and_print_css(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}))
    assert 'id="dp-download"' in html and 'id="dp-print"' in html
    assert "data:text/markdown" in html
    assert "@media print" in html and "#dp-overlay" in html
    assert "Casa de Campo" in html  # download filename base


def test_download_filename_base_strips_path_characters(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21")})
    html = build_map_html(route / "route.geojson", route / "notes.md", title='A/B: "C"',
                          resolve_wiki=False, tile_timeout=0.1)
    assert 'const DP_FILE_BASE = "A_B_ _C_";' in html


def test_map_is_localized(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}), lang="ru")
    assert "План дня" in html and "Открыть полный план" in html


def test_plan_with_script_tag_does_not_break_the_page(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21", "</script><script>alert(1)</script>")})
    html = _build(route)
    assert "<script>alert(1)</script>" not in html


def test_existing_sections_are_untouched_when_plans_exist(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}))
    assert "Getting there" in html and "Points of interest" in html and "Metro" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests/test_day_plan_embed.py -q`
Expected: FAIL with assertion errors (for example `assert 'No day plan yet' in html`).

- [ ] **Step 3: Wire the block into `build_map_html`**

In `skills/osm-day-route-show/scripts/render_map.py`, apply these six edits in order:

**Replace:**

```python
import argparse
import json

```

**With:**

```python
import argparse
import datetime
import json

```

**Replace:**

```python
from day_plan_view import DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI

```

**With:**

```python
from day_plan_view import (
    DAY_PLAN_CSS, DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI, build_day_plan_parts, load_day_plans,
)

```

**Replace:**

```python
    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] == "Point":
            feature["properties"]["_popupExtra"] = point_popup_html(feature["properties"])

```

**With:**

```python
    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] == "Point":
            feature["properties"]["_popupExtra"] = point_popup_html(feature["properties"])

    # Every day-plan-<date>.md in the route folder is embedded, so the single
    # map.html can be forwarded with all planned days inside.
    day_plans = [
        {"date": p.date, "md": p.markdown, "html": plan_markdown_to_html(p.markdown),
         "summary_html": markdown_to_html(extract_md_section(p.markdown, "day_plan_summary")),
         "fetched_at": p.fetched_at}
        for p in load_day_plans(geojson_path.parent)
    ]
    day_plan_sidebar, day_plan_overlay, day_plan_script = build_day_plan_parts(
        day_plans, {key: t(key, user_lang) for key in DAY_PLAN_UI["en"]},
        file_base=re.sub(r'[\\/:*?"<>|]+', "_", title), today=datetime.date.today().isoformat(),
    )

```

**Replace:**

```python
  .route-arrow div {{
```

**With:**

```python
  {DAY_PLAN_CSS}
  .route-arrow div {{
```

**Replace:**

```python
  {confidence_html}
  {links_html}
</div>
<script src="{LEAFLET_JS}"></script>
```

**With:**

```python
  {confidence_html}
  {day_plan_sidebar}
  {links_html}
</div>
{day_plan_overlay}
<script src="{LEAFLET_JS}"></script>
```

**Replace:**

```python
    addDirectionArrows(lineFeature.geometry.coordinates);
  }}
</script>
```

**With:**

```python
    addDirectionArrows(lineFeature.geometry.coordinates);
  }}
</script>
<script>
{day_plan_script}
</script>
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd skills/osm-day-route-show && python3 -m pytest tests -q`
Expected: PASS (all, including 7 new).

- [ ] **Step 5: Check the page in a real browser (one-off)**

Generate a map for a folder holding two plans and open it in a browser (for example Chromium; a headless run works too). The scratch generator used when this plan was written did:

```bash
python3 - <<'EOF'
import json, pathlib, sys, tempfile
sys.path.insert(0, "skills/osm-day-route-show/scripts")
from render_map import build_map_html
d = pathlib.Path(tempfile.mkdtemp())
g = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "LineString",
     "coordinates": [[-3.75, 40.42, 600], [-3.74, 40.43, 640]]}, "properties": {"name": "X"}}]}
(d / "route.geojson").write_text(json.dumps(g))
for day in ("2026-06-21", "2026-06-28"):
    (d / f"day-plan-{day}.md").write_text(
        f"# X — {day}\n<!-- day-plan fetched_at: {day}T06:00:00Z -->\n\n## Summary\n\n- **Danger:** s {day}\n\n"
        "## Weather by hour\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
(d / "map.html").write_text(build_map_html(d / "route.geojson", None, title="X", resolve_wiki=False))
print(d / "map.html")
EOF
```

Expected in the browser: a "Day plan" block between "Points of interest" and "Export & open elsewhere" with a date selector and the summary; "Open full plan" opens the panel with the table; "Download .md" saves `X-day-plan-<date>.md`; "Print / save as PDF" produces a PDF containing only the plan (no map, no sidebar); Escape closes the panel. This was verified in headless Chromium when the plan was written (selector default, summary text, panel, table, download file name and content, Escape, and a print-to-PDF whose text was only the plan).

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_day_plan_embed.py
git commit -m "Embed all day plans in map.html with download and print

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Documentation and final verification

**Files:**
- Modify: `skills/osm-day-route-show/SKILL.md`, `README.md`

- [ ] **Step 1: Document the day-plan embedding in the show skill**

In `skills/osm-day-route-show/SKILL.md`, insert this section immediately before the `## Configuration` heading:

````markdown
## Day Plans

`render_map.py` embeds every `day-plan-YYYY-MM-DD.md` found in the route
folder (written by `osm-day-route-day-plan`) — so the single `map.html` can
be forwarded with all planned days inside, no other file needed. Code lives
in `scripts/day_plan_view.py` (loading, sidebar block, overlay, script, print
CSS) plus `plan_markdown_to_html` in `render_map.py`.

- **Sidebar block "Day plan"** sits after Points of interest and before
  Export: a date `<select>` when there is more than one plan (default: the
  nearest upcoming date, else the latest), the plan's Summary section (found
  through `SECTION_ALIASES["day_plan_summary"]`, the seven summary headings
  the day-plan skill writes — keep both lists in sync), and an "Open full
  plan" button. With no plan files it shows a "No day plan yet" placeholder,
  like every other block.
- **Full-plan overlay**: the whole plan rendered by `plan_markdown_to_html`
  (headings, paragraphs, lists, tables — `markdown_to_html` deliberately
  stays untouched, it has no headings and would turn plan text into list
  items), with fetched-at time, a "date has passed" marker (decided in the
  browser when the page is opened), **Download .md** (a `data:text/markdown`
  link, file name `<route>-day-plan-<date>.md`) and **Print / save as PDF**
  (`window.print()`; `@media print` hides everything except the plan).
- Plan text is HTML-escaped by the converter, and the JSON embedded in the
  page escapes `</`, so a plan cannot break out of the inline `<script>`.
- The file is a snapshot: a plan added after rendering is not in `map.html`
  until it is re-rendered. Plans saved with a BOM or CRLF line endings load
  normally; files with an impossible date in the name are skipped.
- The map itself still loads Leaflet and tiles from the internet; the
  sidebar and plan panel work offline.
````

- [ ] **Step 2: Update the README**

In `README.md`, apply these edits:

**Replace:**

```python
The project is a Claude Code plugin made of two skills that work as a pair.
```

**With:**

```python
The project is a Claude Code plugin made of three skills: two that work as a pair (plan a route, show it), and a third that briefs you on a specific day for a saved route.
```

**Replace:**

````python
```
 your request ──▶ osm-day-route-planning ──▶ routes/<place>-<date>/ ──▶ osm-day-route-show ──▶ map.html + GPX
                  (builds the route)          route.geojson, notes.md,     (draws it)
                                              weights.json, requests.md
```
````

**With:**

````python
```
 your request ──▶ osm-day-route-planning ──▶ routes/<place>-<date>/ ──▶ osm-day-route-show ──▶ map.html + GPX
                  (builds the route)          route.geojson, notes.md,     (draws it, with
                                              weights.json, requests.md,    every day plan inside)
                                              day-plan-<date>.md  ▲
                                                                  │
                                      a date ──▶ osm-day-route-day-plan
                                                 (daylight, weather by hour)
```
````

**Replace:**

```python
| `osm-day-route-show` | Renders a saved route as an interactive map page. Needs a route from the planning skill. |
```

**With:**

```python
| `osm-day-route-show` | Renders a saved route as an interactive map page. Needs a route from the planning skill. |
| `osm-day-route-day-plan` | For a saved route and a date, writes a day plan: sunrise, sunset, daylight, hourly weather. Needs a route from the planning skill. |
```

**Replace:**

```python
## Skill: osm-day-route-show

```

**With:**

```python
## Skill: osm-day-route-day-plan

**Use it when** you have a saved route and know the day you will go: "what will the weather and daylight be on Saturday?"

What you get, as `day-plan-<YYYY-MM-DD>.md` in the route folder:
- **Summary:** the most important warnings first (thunderstorm, strong gusts, finish after sunset, fog, cold, heavy rain).
- **Daylight:** sunrise, sunset and day length, and how much daylight is left after the route's estimated finish (or the latest start that still finishes an hour before sunset).
- **Weather by hour:** temperature and feels-like, precipitation and its probability, cloud cover, visibility, **wind speed and the direction it blows from**, gusts, snow cover, and a plain-language sky description.

Good to know:
- Forecasts reach about 15 days ahead. For a later date you get the average of that date over the last five years, clearly labelled as *not a forecast*. Dates older than a week use recorded weather; the last week uses model data.
- Ask for a plan for several dates: each gets its own file, and re-running a date overwrites only that date.
- The plan records where you start from only as a city or station, never a street address, because the file is embedded in `map.html`, which is meant to be forwarded.
- This is the first version: daylight, weather and the summary. Transit and opening hours, hazards (ticks, mosquitoes, mountains, air, radiation, fire) and mobile coverage are planned next.

## Skill: osm-day-route-show

```

**Replace:**

```python
- **Export:** a GPX download (with elevation), plus links to open the area in Google Maps and OpenStreetMap.
```

**With:**

```python
- **Day plan:** if the route folder has `day-plan-<date>.md` files, every one is embedded in the page. The side panel shows a date picker and the plan's summary; "Open full plan" shows the whole plan (with the hourly weather table), and you can download it as `.md` or print it / save it as PDF from your browser. Because everything is inside the one HTML file, you can send `map.html` to someone and they get all planned days. Re-render the map after adding a new date.
- **Export:** a GPX download (with elevation), plus links to open the area in Google Maps and OpenStreetMap.
```

**Replace:**

```python
how to get there, points of interest, export. Sections
```

**With:**

```python
how to get there, points of interest, day plan, export. Sections
```

**Replace:**

```python
| `map.html` | The rendered map (after the show step). |
```

**With:**

```python
| `day-plan-<YYYY-MM-DD>.md` | A day plan for one date (daylight, hourly weather). One file per planned date. |
| `map.html` | The rendered map (after the show step); contains every day plan. |
```


- [ ] **Step 3: Run every suite**

```bash
(cd skills/osm-day-route-day-plan && python3 -m pytest tests -q)
(cd skills/osm-day-route-show && python3 -m pytest tests -q)
(cd skills/osm-day-route-planning && python3 -m pytest tests -q)
```

Expected: all pass. The planning suite must be unchanged: `archive_validate.py` checks only its required files, so extra `day-plan-*.md`, `day_plan_cache.json` and `facts.json` files in a route folder do not fail validation (confirm by running `python3 skills/osm-day-route-planning/scripts/archive_validate.py <a route folder that has a day plan>` if one exists).

- [ ] **Step 4: Commit**

```bash
git add skills/osm-day-route-show/SKILL.md README.md
git commit -m "Document day-plan skill and map embedding

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** light (Task 3), weather with wind speed, direction and gusts, fog, snow cover, three data sources and climatology (Task 4), summary and fixed section order (Task 5), plan file, privacy and per-date files (Tasks 5-6), map sidebar, panel, `.md` download, print CSS, all plans embedded, localization (Tasks 7-9), docs (Task 10). Deliberately not in this plan: transit, poi_hours, hazards group (bio, mountain, people, air, radiation, fire), cell coverage — plans 2 and 3. Their headings and `SECTION_ORDER` slots exist already.
- **Known limitation to carry into the follow-up plans:** body text of the light and weather sections is translated for English and Russian only (other languages fall back to English); headings, metadata and severity labels exist in all seven languages.
- **Cross-skill contract:** the summary headings in `i18n.STRINGS[lang]["h_summary"]` must equal `DAY_PLAN_SUMMARY_HEADINGS` in `day_plan_view.py`; the machine-readable comment `<!-- day-plan fetched_at: ... -->` written by `service.assemble_markdown` is what `load_day_plans` reads.
