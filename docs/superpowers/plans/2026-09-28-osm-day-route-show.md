# osm-day-route-show Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `osm-day-route-show` skill — renders a multi-mode `route.geojson` (from `osm-day-route-planning`) into an interactive map, with 3D-coordinate support and a plugin-based module that shows **every** source's findings for a point (interest point or access point), not just one "best" link.

**Architecture:** Port `render_map.py` from `init-raw-source/osm-hike-route-show` into `skills/osm-day-route-show/scripts/`, fix its three `[lon, lat]`-unpacking sites for 3D coordinates, extract its existing verified-Wikipedia-match logic into a `place_info/providers/wikipedia.py` plugin, and add three more plugins (Wikidata, Wikimedia Commons, optional-key OpenTripMap) behind a shared `PlaceInfoService` aggregator that queries all of them and returns every non-empty result, not the single best one. This plan assumes `docs/superpowers/plans/2026-09-28-osm-day-route-planning.md` has been implemented (or at least that its `route.geojson` schema — spec §3.11 — is stable), since this skill's fixtures are hand-written to match that schema.

**Tech Stack:** Python 3.10+, standard library only at runtime (`urllib.request`, `json`, `re`). Tests use `pytest` (dev-only) with `unittest.mock` for HTTP calls; no live network access in the automated suite.

**Spec:** `docs/superpowers/specs/2026-09-28-osm-day-route-planning-show-design.md`

## Global Constraints

- Zero external runtime dependencies — stdlib only, same as `osm-day-route-planning` (spec §3.6, carried over to this skill).
- Never publish an unverified name-only match as a Wikipedia link — a candidate must both fuzzy-match the point's name AND have its own coordinates within ~5km (or come from a curated `wikidata`/`wikipedia` OSM tag, which skips the coordinate check). This existing discipline (spec §5, "Wikipedia Links") is preserved verbatim when the logic moves into the new plugin shape.
- Point/route names are never translated for display, in any language — `search_names`/the plugin `names` dict is search-only and never changes what's shown (existing convention, unchanged).
- `opentripmap.py` works only when an API key is configured; its absence is silently handled (the plugin contributes nothing, every other plugin still runs) — never an exception that stops the render (spec §5).
- `place_info.json` is one shared cache file per route, used by all four plugins and by both interest points and access points (spec §5) — not four separate cache files.
- A `route.geojson` produced before this round (no `mode` property on the `LineString`, 2D coordinates) must still render without errors — see spec §6.3 and Review Focus below.

## Review Focus

- `build_gpx`'s `for lon, lat in line["geometry"]["coordinates"]:` unpacks each coordinate as a 2-tuple — a 3D `[lon, lat, ele]` array (the new schema, spec §3.11) raises `ValueError: too many values to unpack`. Covered in Task 2.
- An archive built before this round has 2D coordinates and no `mode`/`style`/etc. properties on its `LineString` — the renderer must not crash on either the missing properties or the shorter coordinate arrays. Covered in Task 2 (coordinates) and Task 8 (properties).
- `opentripmap.py` with no configured key, or a key that gets an HTTP 401/403 back, must return `None` from `fetch()` without raising — the other three plugins must still run and their results must still reach the page. Covered in Task 5 and Task 6.
- A point with a `wikidata` QID that doesn't actually resolve to any sitelink (a stub/malformed Wikidata item) must not be treated as a Wikipedia match — `wikidata.py`'s own result and `wikipedia.py`'s sitelink lookup must each independently degrade to "no result" rather than propagating a `KeyError`/`IndexError` up through `PlaceInfoService`. Covered in Task 4 (wikidata) and Task 3 (wikipedia, already true of the ported logic — pinned by a new test here).
- `PlaceInfoService` must keep working, and keep returning the other three plugins' results, when exactly one plugin's `fetch()` raises an unexpected exception (a bug in a single plugin must not take down the whole popup). Covered in Task 6.

---

## Task 1: Scaffold the skill directory and port `render_map.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/render_map.py` (ported from `init-raw-source/osm-hike-route-show/scripts/render_map.py`)
- Create: `skills/osm-day-route-show/tests/conftest.py`
- Test: `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Produces: every existing function/name in `render_map.py` unchanged for now (`build_gpx`, `bbox_center_zoom`, `_route_title`, `build_map_html`, `main`, the i18n tables, `resolve_wikipedia` and its helpers — the latter get extracted to `place_info/` in Task 3, not deleted here).

- [ ] **Step 1: Create the directory skeleton**

```bash
mkdir -p /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-show/scripts/place_info/providers
mkdir -p /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-show/tests
```

- [ ] **Step 2: Copy `render_map.py` into the new location unmodified**

```bash
cp /mnt/data/pavel/work/osm-hike-route/init-raw-source/osm-hike-route-show/scripts/render_map.py \
   /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-show/scripts/render_map.py
```

- [ ] **Step 3: Add `conftest.py`**

```python
# skills/osm-day-route-show/tests/conftest.py
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
```

- [ ] **Step 4: Write a failing sanity test for the ported module**

```python
# skills/osm-day-route-show/tests/test_render_map.py
from render_map import lang_priority, t


def test_lang_priority_orders_user_local_english_deduplicated():
    assert lang_priority("ru", "ru") == ["ru", "en"]
    assert lang_priority("ru", "es") == ["ru", "es", "en"]


def test_t_falls_back_to_english_for_unknown_language():
    assert t("wikipedia", "xx") == t("wikipedia", "en")
```

- [ ] **Step 5: Run the test and confirm it passes (the module was only copied)**

Run: `cd /mnt/data/pavel/work/osm-hike-route/skills/osm-day-route-show && python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/conftest.py \
        skills/osm-day-route-show/tests/test_render_map.py
git commit -m "Scaffold osm-day-route-show skill and port render_map.py"
```

---

## Task 2: Fix `build_gpx` for 3D coordinates and emit `<ele>` (Review Focus #1, #2)

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Test: `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Modifies: `render_map.build_gpx(geojson: dict, title: str) -> str` — same signature, now tolerates both 2-tuple and 3-tuple coordinate arrays and writes a nested `<ele>` element on `<trkpt>`/`<wpt>` when a third coordinate is present.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-show/tests/test_render_map.py
from render_map import build_gpx


def _geojson_3d():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0]]},
                "properties": {"name": "Тестовый маршрут"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005, 105.0]},
                "properties": {"name": "Родник", "type": "spring"},
            },
        ],
    }


def _geojson_2d_legacy():
    """Pre-this-round archive: no third coordinate anywhere."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
                "properties": {"name": "Старый маршрут"},
            },
        ],
    }


def test_build_gpx_does_not_raise_on_3d_coordinates():
    gpx = build_gpx(_geojson_3d(), "Тестовый маршрут")
    assert "<gpx" in gpx


def test_build_gpx_emits_ele_for_3d_track_points_and_waypoints():
    gpx = build_gpx(_geojson_3d(), "Тестовый маршрут")

    assert "<ele>100.0</ele>" in gpx
    assert "<ele>110.0</ele>" in gpx
    assert "<ele>105.0</ele>" in gpx


def test_build_gpx_omits_ele_for_2d_legacy_coordinates():
    gpx = build_gpx(_geojson_2d_legacy(), "Старый маршрут")

    assert "<ele>" not in gpx
    assert '<trkpt lat="55.0" lon="37.0"/>' in gpx or "<trkpt" in gpx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: FAIL — `test_build_gpx_does_not_raise_on_3d_coordinates` and the `_emits_ele_` test fail with `ValueError: too many values to unpack (expected 2)` from the existing `for lon, lat in line["geometry"]["coordinates"]:` line.

- [ ] **Step 3: Replace `build_gpx`'s coordinate handling**

```python
def build_gpx(geojson: dict, title: str) -> str:
    """GPX 1.1 — the format both Wikiloc and Garmin devices/BaseCamp/Connect
    import natively. One <trk> from the route LineString, one <wpt> per
    Point feature. Coordinates may be [lon, lat] (older archives) or
    [lon, lat, ele] (spec §3.11) — ele is emitted only when present."""
    features = geojson.get("features", [])
    line = next((f for f in features if f["geometry"]["type"] == "LineString"), None)
    points = [f for f in features if f["geometry"]["type"] == "Point"]

    def _ele_tag(coord) -> str:
        return f"<ele>{coord[2]}</ele>" if len(coord) > 2 else ""

    wpts = []
    for f in points:
        coord = f["geometry"]["coordinates"]
        lon, lat = coord[0], coord[1]
        props = f.get("properties", {})
        name = _xml_escape(props.get("name", "Point"))
        desc = _xml_escape(props.get("type", ""))
        wpts.append(
            f'  <wpt lat="{lat}" lon="{lon}">{_ele_tag(coord)}<name>{name}</name><desc>{desc}</desc></wpt>'
        )

    trkpts = []
    if line:
        for coord in line["geometry"]["coordinates"]:
            lon, lat = coord[0], coord[1]
            trkpts.append(f'      <trkpt lat="{lat}" lon="{lon}">{_ele_tag(coord)}</trkpt>')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="osm-day-route-show" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <metadata><name>{_xml_escape(title)}</name></metadata>\n"
        + "\n".join(wpts) + ("\n" if wpts else "")
        + "  <trk>\n"
        f"    <name>{_xml_escape(title)}</name>\n"
        "    <trkseg>\n"
        + "\n".join(trkpts) + ("\n" if trkpts else "")
        + "    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )
```

Note the `creator` attribute changes from `osm-hike-route-show` to `osm-day-route-show` — consistent with the skill rename.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_render_map.py
git commit -m "Fix build_gpx for 3D coordinates and emit <ele> (Review Focus #1)"
```

---

## Task 3: Extract the Wikipedia logic into `place_info/providers/wikipedia.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/place_info/__init__.py` (empty for now, filled in Task 6)
- Create: `skills/osm-day-route-show/scripts/place_info/providers/__init__.py` (empty)
- Create: `skills/osm-day-route-show/scripts/place_info/providers/base.py`
- Create: `skills/osm-day-route-show/scripts/place_info/providers/wikipedia.py`
- Modify: `skills/osm-day-route-show/scripts/render_map.py` (remove the functions moved out)
- Test: `skills/osm-day-route-show/tests/test_place_info_wikipedia.py`

**Interfaces:**
- Produces: `place_info.providers.base.PlaceInfoProvider` (ABC: `provider_id: str`, `fetch(self, names: dict[str, str], lat: float, lon: float, wikidata_qid: str | None) -> PlaceInfoResult | None`), `place_info.providers.base.PlaceInfoResult` (a small dataclass: `provider_id: str`, `summary: str | None`, `url: str | None`, `image_url: str | None`), `place_info.providers.wikipedia.WikipediaProvider(user_lang: str, local_lang: str | None = None, timeout: float = 5.0)`.

- [ ] **Step 1: Write `base.py`**

```python
# skills/osm-day-route-show/scripts/place_info/providers/base.py
"""Common interface every place-info plugin implements — one source, one
file, see spec §5. PlaceInfoService only talks to this interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PlaceInfoResult:
    provider_id: str
    summary: str | None = None
    url: str | None = None
    image_url: str | None = None


class PlaceInfoProvider(ABC):
    provider_id: str

    @abstractmethod
    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        """`names` is {lang: name} — local language, user language, English
        (spec §5, reuses the point's own `search_names`/`name`). Returns
        None when this provider found nothing usable — never raises for an
        ordinary 'no data' outcome; only a genuine transport/programming
        error should propagate."""
        raise NotImplementedError
```

- [ ] **Step 2: Write the failing tests for the wrapper's plugin-shaped behavior**

These tests exercise `WikipediaProvider.fetch` end-to-end with the HTTP layer mocked, pinning the two paths that matter for Review Focus #4 (a QID that resolves to nothing) without re-deriving every fuzzy-match edge case the underlying algorithm already handles (that logic is copied verbatim from a production-verified implementation, see Step 3).

```python
# skills/osm-day-route-show/tests/test_place_info_wikipedia.py
import json
from unittest.mock import patch, MagicMock

from place_info.providers.wikipedia import WikipediaProvider
from place_info.providers.base import PlaceInfoResult


def _mock_response(payload):
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode("utf-8")
    return mock


def test_provider_id_is_wikipedia():
    assert WikipediaProvider(user_lang="ru").provider_id == "wikipedia"


def test_fetch_returns_result_with_url_when_qid_resolves():
    sitelinks_payload = {
        "entities": {"Q123": {"sitelinks": {"ruwiki": {"title": "Бажуково"}}}}
    }
    provider = WikipediaProvider(user_lang="ru")

    with patch("place_info.providers.wikipedia._http_get_with_retry",
               return_value=json.dumps(sitelinks_payload).encode("utf-8")):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid="Q123")

    assert isinstance(result, PlaceInfoResult)
    assert result.provider_id == "wikipedia"
    assert result.url == "https://ru.wikipedia.org/wiki/%D0%91%D0%B0%D0%B6%D1%83%D0%BA%D0%BE%D0%B2%D0%BE"


def test_fetch_returns_none_when_qid_has_no_matching_sitelink():
    """Review Focus #4: a QID that resolves to something, but not to any
    usable sitelink, must degrade to None, not raise."""
    sitelinks_payload = {"entities": {"Q999": {"sitelinks": {}}}}
    provider = WikipediaProvider(user_lang="ru")

    with patch("place_info.providers.wikipedia._http_get_with_retry",
               return_value=json.dumps(sitelinks_payload).encode("utf-8")):
        result = provider.fetch({"ru": "Пустая точка"}, 56.85, 59.5, wikidata_qid="Q999")

    assert result is None


def test_fetch_returns_none_without_qid_and_without_verified_search_match():
    search_payload = {"query": {"search": []}}
    geosearch_payload = {"query": {"geosearch": []}}
    provider = WikipediaProvider(user_lang="ru")

    def fake_get(url, timeout):
        payload = search_payload if "list=search" in url else geosearch_payload
        return json.dumps(payload).encode("utf-8")

    with patch("place_info.providers.wikipedia._http_get_with_retry", side_effect=fake_get):
        result = provider.fetch({"ru": "Неизвестное место"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
```

- [ ] **Step 3: Move the Wikipedia resolution code from `render_map.py` into `wikipedia.py`, then wrap it**

From `render_map.py`, **cut** (not copy) these names — they move entirely into the new file and are deleted from `render_map.py`: `WikiLookupError`, `_last_request_time`, `MIN_REQUEST_INTERVAL`, `_throttle`, `_http_get_with_retry`, `_wiki_api_get`, `_wikidata_sitelinks`, `_langlinks`, `_search_near`, `_geosearch`, `_haversine_km`, `_verified_by_coords`, `_best_verified_candidate`, `_merged_candidates`, `_normalize_name`, `_name_matches`, `resolve_wikipedia`, `USER_AGENT` (the module-level constant near the top of the file — rename it `_USER_AGENT = "osm-day-route-show/1.0 (place_info wikipedia plugin)"` in its new home).

Paste them into `place_info/providers/wikipedia.py`, unchanged except:
1. The module-level `import` lines it actually needs: `difflib`, `json`, `math`, `re`, `unicodedata`, `urllib.error`, `urllib.parse`, `urllib.request`.
2. `lang_priority` is still needed by `resolve_wikipedia` — it stays in `render_map.py` (other code needs it too, see Task 8), so import it: `from render_map import lang_priority` would create a circular import (`render_map` will later import `place_info`), so instead **copy** `lang_priority` itself into `wikipedia.py` as a small private helper named `_lang_priority` (it's an 8-line pure function — duplicating it here is cheaper than restructuring both modules' import graph for one helper). Inside the pasted `resolve_wikipedia` body, change its one call site from `lang_priority(user_lang, local_lang)` to `_lang_priority(user_lang, local_lang)` to match.
3. Append the wrapper class:

```python
from .base import PlaceInfoProvider, PlaceInfoResult


class WikipediaProvider(PlaceInfoProvider):
    provider_id = "wikipedia"

    def __init__(self, user_lang: str, local_lang: str | None = None, timeout: float = 5.0):
        self.user_lang = user_lang
        self.local_lang = local_lang
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        search_lang = self.local_lang or self.user_lang
        name = names.get(search_lang) or names.get(self.user_lang) or next(iter(names.values()), "")
        feature = {
            "geometry": {"coordinates": [lon, lat]},
            "properties": {
                "name": name,
                "wikidata": wikidata_qid,
                "search_names": names,
            },
        }
        try:
            url, lang = resolve_wikipedia(feature, self.user_lang, self.local_lang, self.timeout)
        except WikiLookupError:
            return None
        if url is None:
            return None
        return PlaceInfoResult(provider_id=self.provider_id, url=url, summary=f"Wikipedia ({lang})")
```

`resolve_wikipedia`'s own signature and body are unchanged from the ported version — it still reads `feature["properties"]["wikidata"]`/`["search_names"]` and `feature["geometry"]["coordinates"]`, all of which the wrapper above constructs from the plugin-shaped arguments.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_place_info_wikipedia.py -v`
Expected: PASS (4 tests)

Also re-run the render_map tests to confirm the extraction didn't break anything still living there:

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (5 tests) — `resolve_wikipedia` and friends are gone from `render_map.py`, but nothing already tested there depended on them directly (they were only ever called from `annotate_wikipedia_links`, which moves out in Task 6).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/scripts/place_info \
        skills/osm-day-route-show/tests/test_place_info_wikipedia.py
git commit -m "Extract Wikipedia resolution into place_info/providers/wikipedia.py plugin"
```

---

## Task 4: `place_info/providers/wikidata.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/place_info/providers/wikidata.py`
- Test: `skills/osm-day-route-show/tests/test_place_info_wikidata.py`

**Interfaces:**
- Produces: `place_info.providers.wikidata.WikidataProvider(user_lang: str, timeout: float = 5.0)` implementing `PlaceInfoProvider`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_place_info_wikidata.py
import json
from unittest.mock import patch

from place_info.providers.wikidata import WikidataProvider


def test_provider_id_is_wikidata():
    assert WikidataProvider(user_lang="ru").provider_id == "wikidata"


def test_fetch_by_qid_returns_description_and_url():
    payload = {"entities": {"Q123": {
        "labels": {"ru": {"value": "Бажуково"}},
        "descriptions": {"ru": {"value": "деревня в Свердловской области"}},
        "sitelinks": {"ruwiki": {"title": "Бажуково"}},
    }}}
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value=payload):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid="Q123")

    assert result.provider_id == "wikidata"
    assert result.summary == "деревня в Свердловской области"
    assert result.url == "https://www.wikidata.org/wiki/Q123"


def test_fetch_by_qid_returns_none_when_entity_missing_from_response():
    """Review Focus #4: a QID whose entity data doesn't come back at all."""
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value={"entities": {}}):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid="Q999")

    assert result is None


def test_fetch_without_qid_uses_nearby_sparql_search():
    sparql_payload = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q456"},
         "itemLabel": {"value": "Родник"}},
    ]}}
    entity_payload = {"entities": {"Q456": {
        "labels": {"ru": {"value": "Родник"}},
        "descriptions": {"ru": {"value": "источник питьевой воды"}},
        "sitelinks": {},
    }}}
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", side_effect=[sparql_payload, entity_payload]):
        result = provider.fetch({"ru": "Родник"}, 56.85, 59.5, wikidata_qid=None)

    assert result.summary == "источник питьевой воды"
    assert result.url == "https://www.wikidata.org/wiki/Q456"


def test_fetch_without_qid_returns_none_when_nothing_nearby():
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value={"results": {"bindings": []}}):
        result = provider.fetch({"ru": "Точка в поле"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_place_info_wikidata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'place_info.providers.wikidata'`

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/osm-day-route-show/scripts/place_info/providers/wikidata.py
"""Wikidata plugin (spec §5): a known QID (copied from the OSM `wikidata`
tag) is a fast, curated lookup; without one, a SPARQL 'nearby' search
finds a candidate entity by coordinates. Either way, only a description
in a language this run cares about is returned — never a raw fallback
in an unrelated language."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info wikidata plugin)"
_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
_SPARQL_URL = "https://query.wikidata.org/sparql"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _describe_entity(qid: str, user_lang: str, timeout: float) -> PlaceInfoResult | None:
    try:
        data = _http_get_json(_ENTITY_URL.format(qid=qid), timeout)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    entity = data.get("entities", {}).get(qid)
    if not entity:
        return None
    description = entity.get("descriptions", {}).get(user_lang, {}).get("value") \
        or entity.get("descriptions", {}).get("en", {}).get("value")
    if not description:
        return None
    return PlaceInfoResult(
        provider_id="wikidata", summary=description,
        url=f"https://www.wikidata.org/wiki/{qid}",
    )


class WikidataProvider(PlaceInfoProvider):
    provider_id = "wikidata"

    def __init__(self, user_lang: str, timeout: float = 5.0):
        self.user_lang = user_lang
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        if wikidata_qid:
            return _describe_entity(wikidata_qid, self.user_lang, self.timeout)

        query = (
            "SELECT ?item ?itemLabel WHERE { "
            f"SERVICE wikibase:around {{ ?item wdt:P625 ?location . "
            f'bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral . '
            'bd:serviceParam wikibase:radius "0.3" . } '
            f'SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{self.user_lang},en" . }} '
            "} LIMIT 1"
        )
        url = _SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
        try:
            data = _http_get_json(url, self.timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None
        item_uri = bindings[0]["item"]["value"]
        qid = item_uri.rsplit("/", 1)[-1]
        return _describe_entity(qid, self.user_lang, self.timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_place_info_wikidata.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/place_info/providers/wikidata.py skills/osm-day-route-show/tests/test_place_info_wikidata.py
git commit -m "Add Wikidata place_info plugin (Review Focus #4)"
```

---

## Task 5: `place_info/providers/wikimedia_commons.py` and `opentripmap.py`

**Files:**
- Create: `skills/osm-day-route-show/scripts/place_info/providers/wikimedia_commons.py`
- Create: `skills/osm-day-route-show/scripts/place_info/providers/opentripmap.py`
- Test: `skills/osm-day-route-show/tests/test_place_info_commons_and_opentripmap.py`

**Interfaces:**
- Produces: `WikimediaCommonsProvider()` (no constructor args needed — geosearch is language-agnostic), `OpenTripMapProvider(api_key: str | None)`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_place_info_commons_and_opentripmap.py
import json
from unittest.mock import patch

from place_info.providers.wikimedia_commons import WikimediaCommonsProvider
from place_info.providers.opentripmap import OpenTripMapProvider


def test_commons_provider_id():
    assert WikimediaCommonsProvider().provider_id == "wikimedia_commons"


def test_commons_fetch_returns_image_url_for_nearest_file():
    payload = {"query": {"geosearch": [{"title": "File:Bazhukovo view.jpg"}]}}
    provider = WikimediaCommonsProvider()

    with patch("place_info.providers.wikimedia_commons._http_get_json", return_value=payload):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid=None)

    assert result.provider_id == "wikimedia_commons"
    assert result.image_url == "https://commons.wikimedia.org/wiki/File:Bazhukovo_view.jpg"


def test_commons_fetch_returns_none_when_nothing_nearby():
    provider = WikimediaCommonsProvider()

    with patch("place_info.providers.wikimedia_commons._http_get_json", return_value={"query": {"geosearch": []}}):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None


def test_opentripmap_provider_id():
    assert OpenTripMapProvider(api_key="fake-key").provider_id == "opentripmap"


def test_opentripmap_fetch_returns_none_without_configured_key():
    """Review Focus #3: no key configured -> silent skip, no network call."""
    provider = OpenTripMapProvider(api_key=None)

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
    mock_urlopen.assert_not_called()


def test_opentripmap_fetch_returns_summary_and_url_with_valid_key():
    radius_payload = {"features": [{"properties": {"xid": "N123"}}]}
    detail_payload = {
        "name": "Родник", "wikipedia_extracts": {"text": "Источник питьевой воды."},
        "url": "https://example.org/rodnik",
    }
    provider = OpenTripMapProvider(api_key="fake-key")

    with patch("place_info.providers.opentripmap._http_get_json", side_effect=[radius_payload, detail_payload]):
        result = provider.fetch({"ru": "Родник"}, 56.85, 59.5, wikidata_qid=None)

    assert result.summary == "Источник питьевой воды."
    assert result.url == "https://example.org/rodnik"


def test_opentripmap_fetch_returns_none_on_unauthorized_key():
    """Review Focus #3: a key that the API rejects must degrade quietly."""
    import urllib.error
    provider = OpenTripMapProvider(api_key="bad-key")

    with patch("place_info.providers.opentripmap._http_get_json",
               side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_place_info_commons_and_opentripmap.py -v`
Expected: FAIL with `ModuleNotFoundError` for both new modules.

- [ ] **Step 3: Write the minimal implementations**

```python
# skills/osm-day-route-show/scripts/place_info/providers/wikimedia_commons.py
"""Wikimedia Commons plugin (spec §5): nearby-file geosearch for a photo
of the point — no description, images only. No auth needed."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info commons plugin)"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WikimediaCommonsProvider(PlaceInfoProvider):
    provider_id = "wikimedia_commons"

    def __init__(self, radius_m: int = 500, timeout: float = 5.0):
        self.radius_m = radius_m
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        params = {
            "action": "query", "format": "json", "list": "geosearch",
            "gscoord": f"{lat}|{lon}", "gsradius": self.radius_m,
            "gsnamespace": 6, "gslimit": 1,
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            data = _http_get_json(url, self.timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        results = data.get("query", {}).get("geosearch", [])
        if not results:
            return None
        title = results[0]["title"]
        image_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        return PlaceInfoResult(provider_id=self.provider_id, image_url=image_url)
```

```python
# skills/osm-day-route-show/scripts/place_info/providers/opentripmap.py
"""OpenTripMap plugin (spec §5): the richest single-call payload of the
four (aggregates OSM+Wikidata+Wikipedia), but needs a free API key —
missing/rejected key degrades to no result, never an exception."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info opentripmap plugin)"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OpenTripMapProvider(PlaceInfoProvider):
    provider_id = "opentripmap"

    def __init__(self, api_key: str | None, radius_m: int = 300, timeout: float = 5.0):
        self.api_key = api_key
        self.radius_m = radius_m
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        if not self.api_key:
            return None
        radius_params = {
            "radius": self.radius_m, "lon": lon, "lat": lat, "limit": 1, "apikey": self.api_key,
        }
        radius_url = "https://api.opentripmap.com/0.1/en/places/radius?" + urllib.parse.urlencode(radius_params)
        try:
            radius_data = _http_get_json(radius_url, self.timeout)
            features = radius_data.get("features", [])
            if not features:
                return None
            xid = features[0]["properties"]["xid"]
            detail_url = (
                f"https://api.opentripmap.com/0.1/en/places/xid/{xid}?"
                + urllib.parse.urlencode({"apikey": self.api_key})
            )
            detail = _http_get_json(detail_url, self.timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError, KeyError):
            return None
        summary = detail.get("wikipedia_extracts", {}).get("text")
        url = detail.get("url")
        if not summary and not url:
            return None
        return PlaceInfoResult(provider_id=self.provider_id, summary=summary, url=url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_place_info_commons_and_opentripmap.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/place_info/providers/wikimedia_commons.py \
        skills/osm-day-route-show/scripts/place_info/providers/opentripmap.py \
        skills/osm-day-route-show/tests/test_place_info_commons_and_opentripmap.py
git commit -m "Add Wikimedia Commons and optional-key OpenTripMap plugins (Review Focus #3)"
```

---

## Task 6: `place_info/cache.py` and `PlaceInfoService` aggregator (Review Focus #5)

**Files:**
- Create: `skills/osm-day-route-show/scripts/place_info/cache.py`
- Modify: `skills/osm-day-route-show/scripts/place_info/__init__.py`
- Test: `skills/osm-day-route-show/tests/test_place_info_service.py`

**Interfaces:**
- Produces: `place_info.cache.cache_key(provider_id: str, identity: str, lat: float, lon: float) -> str`, `place_info.cache.load_cache(path) -> dict`, `place_info.cache.save_entry(path, cache, key, result_dict) -> None`; `place_info.PlaceInfoService(providers: list[PlaceInfoProvider], cache_path: Path)` with `.fetch_all(names: dict[str, str], lat: float, lon: float, wikidata_qid: str | None, identity: str) -> list[PlaceInfoResult]`.

- [ ] **Step 1: Write the failing tests**

```python
# skills/osm-day-route-show/tests/test_place_info_service.py
from place_info import PlaceInfoService
from place_info.providers.base import PlaceInfoProvider, PlaceInfoResult


class _FakeProvider(PlaceInfoProvider):
    def __init__(self, provider_id, result=None, raises=False):
        self.provider_id = provider_id
        self._result = result
        self._raises = raises
        self.call_count = 0

    def fetch(self, names, lat, lon, wikidata_qid):
        self.call_count += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._result


def test_fetch_all_returns_results_from_every_provider_that_found_something(tmp_path):
    p1 = _FakeProvider("p1", result=PlaceInfoResult(provider_id="p1", summary="A"))
    p2 = _FakeProvider("p2", result=None)
    p3 = _FakeProvider("p3", result=PlaceInfoResult(provider_id="p3", url="https://example.org"))
    service = PlaceInfoService([p1, p2, p3], cache_path=tmp_path / "place_info.json")

    results = service.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/1")

    assert [r.provider_id for r in results] == ["p1", "p3"]


def test_fetch_all_survives_a_single_provider_raising(tmp_path):
    """Review Focus #5: one plugin's bug must not take down the others."""
    ok_provider = _FakeProvider("ok", result=PlaceInfoResult(provider_id="ok", summary="fine"))
    broken_provider = _FakeProvider("broken", raises=True)
    service = PlaceInfoService([broken_provider, ok_provider], cache_path=tmp_path / "place_info.json")

    results = service.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/2")

    assert [r.provider_id for r in results] == ["ok"]


def test_fetch_all_uses_cache_on_second_call(tmp_path):
    provider = _FakeProvider("p1", result=PlaceInfoResult(provider_id="p1", summary="cached"))
    cache_path = tmp_path / "place_info.json"

    PlaceInfoService([provider], cache_path=cache_path).fetch_all(
        {"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/3")
    provider.call_count = 0
    second = PlaceInfoService([provider], cache_path=cache_path)
    results = second.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/3")

    assert results[0].summary == "cached"
    assert provider.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_place_info_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'PlaceInfoService'`

- [ ] **Step 3: Write `cache.py` and `__init__.py`**

```python
# skills/osm-day-route-show/scripts/place_info/cache.py
"""One shared place_info.json per route (spec §5) — used by every plugin,
for both interest points and access points. Written immediately on each
new result, same incremental-write reasoning as wiki_links.json before it."""
import json
from dataclasses import asdict
from pathlib import Path


def cache_key(provider_id: str, identity: str, lat: float, lon: float) -> str:
    return f"{provider_id}|{identity}|{round(lat, 5)}|{round(lon, 5)}"


def load_cache(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_entry(path: Path, cache: dict, key: str, result_dict: dict) -> None:
    cache[key] = result_dict
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
```

```python
# skills/osm-day-route-show/scripts/place_info/__init__.py
"""Public entry point for point enrichment (spec §5) — queries every
configured plugin and returns EVERY non-empty result, not just the best
one. Used identically for interest points and access points."""
from dataclasses import asdict
from pathlib import Path

from .cache import cache_key, load_cache, save_entry
from .providers.base import PlaceInfoResult


class PlaceInfoService:
    def __init__(self, providers: list, cache_path: Path):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._cache = load_cache(self._cache_path)

    def fetch_all(self, names: dict[str, str], lat: float, lon: float,
                  wikidata_qid: str | None, identity: str) -> list[PlaceInfoResult]:
        results = []
        for provider in self._providers:
            key = cache_key(provider.provider_id, identity, lat, lon)
            if key in self._cache:
                cached = self._cache[key]
                if cached is not None:
                    results.append(PlaceInfoResult(**cached))
                continue
            try:
                result = provider.fetch(names, lat, lon, wikidata_qid)
            except Exception:
                # A single broken plugin must not take down the others or
                # the render — see spec §5 "each plugin works independently".
                result = None
            save_entry(self._cache_path, self._cache, key,
                       asdict(result) if result is not None else None)
            if result is not None:
                results.append(result)
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_place_info_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/place_info/cache.py skills/osm-day-route-show/scripts/place_info/__init__.py \
        skills/osm-day-route-show/tests/test_place_info_service.py
git commit -m "Add place_info cache and PlaceInfoService aggregator (Review Focus #5)"
```

---

## Task 7: Wire `PlaceInfoService` into `render_map.py`'s point-annotation step

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Test: `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Consumes: `place_info.PlaceInfoService.fetch_all` (Task 6).
- Produces: `render_map.annotate_place_info(geojson: dict, user_lang: str, local_lang: str | None, cache_path: Path | None, opentripmap_api_key: str | None = None) -> None` — replaces the old `annotate_wikipedia_links`; mutates every `Point` feature's `properties["_placeInfo"]` to a list of `{"provider_id", "summary", "url", "image_url"}` dicts (only non-null fields included per entry, matching how `_point_feature` already omits `None`s in the planning skill's output — see spec §5 "показывает все, что нашли плагины").

- [ ] **Step 1: Write the failing test**

```python
# append to skills/osm-day-route-show/tests/test_render_map.py
from unittest.mock import patch
from render_map import annotate_place_info
from place_info.providers.base import PlaceInfoResult


def test_annotate_place_info_adds_placeinfo_list_to_point_features(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
            "properties": {"name": "Родник", "type": "spring", "osm_id": "node/1"},
        }],
    }

    fake_results = [PlaceInfoResult(provider_id="wikidata", summary="источник")]
    with patch("render_map.PlaceInfoService") as MockService:
        MockService.return_value.fetch_all.return_value = fake_results
        annotate_place_info(geojson, user_lang="ru", local_lang=None,
                             cache_path=tmp_path / "place_info.json")

    point = geojson["features"][0]
    assert point["properties"]["_placeInfo"] == [{"provider_id": "wikidata", "summary": "источник"}]


def test_annotate_place_info_skips_linestring_features(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.1, 55.1]]},
            "properties": {"name": "Маршрут"},
        }],
    }

    annotate_place_info(geojson, user_lang="ru", local_lang=None, cache_path=tmp_path / "place_info.json")

    assert "_placeInfo" not in geojson["features"][0]["properties"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'annotate_place_info'`

- [ ] **Step 3: Add the import and the new function to `render_map.py`, and update `build_map_html`'s call site**

Add near the top of `render_map.py` (with the other imports):

```python
from place_info import PlaceInfoService
from place_info.providers.wikipedia import WikipediaProvider
from place_info.providers.wikidata import WikidataProvider
from place_info.providers.wikimedia_commons import WikimediaCommonsProvider
from place_info.providers.opentripmap import OpenTripMapProvider
```

Add the new function (near where `annotate_wikipedia_links` used to be — that function and its own now-orphaned `_wiki_cache_load`/`_wiki_cache_key` helpers are deleted, since `place_info`'s own cache module replaces them):

```python
def annotate_place_info(geojson: dict, user_lang: str, local_lang: str | None,
                         cache_path: Path | None, opentripmap_api_key: str | None = None,
                         timeout: float = 5.0) -> None:
    """Mutates every Point feature in place, adding `_placeInfo`: a list of
    every plugin's non-empty result (spec §5 — show ALL sources, not the
    single best one, unlike the old resolve_wikipedia-only behavior)."""
    import os
    api_key = opentripmap_api_key or os.environ.get("OSM_DAY_ROUTE_OPENTRIPMAP_KEY")
    providers = [
        WikipediaProvider(user_lang, local_lang, timeout),
        WikidataProvider(user_lang, timeout),
        WikimediaCommonsProvider(timeout=timeout),
        OpenTripMapProvider(api_key, timeout=timeout),
    ]
    service = PlaceInfoService(providers, cache_path) if cache_path else PlaceInfoService(providers, Path("/dev/null"))

    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] != "Point":
            continue
        props = feature.get("properties", {})
        coord = feature["geometry"]["coordinates"]
        lon, lat = coord[0], coord[1]
        names = props.get("search_names", {}) or {}
        if props.get("name"):
            names = {**names, (local_lang or user_lang): props["name"]}
        identity = props.get("osm_id") or props.get("wikidata") or props.get("name", "")

        results = service.fetch_all(names, lat, lon, props.get("wikidata"), identity)
        if results:
            props["_placeInfo"] = [
                {k: v for k, v in asdict(r).items() if v is not None} for r in results
            ]
```

Add `from dataclasses import asdict` and `from pathlib import Path` to the top-level imports if not already present (`Path` already is).

Update `build_map_html` to call the new function instead of the old one:

```python
    if resolve_wiki:
        cache_path = geojson_path.parent / "place_info.json"
        annotate_place_info(geojson, user_lang, local_lang, cache_path)
```

(replacing the old `cache_path = geojson_path.parent / "wiki_links.json"` / `annotate_wikipedia_links(...)` pair — the `resolve_wiki`/`--no-wikipedia` flag name stays as-is for CLI backward compatibility, it just now gates all four plugins instead of one).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_render_map.py
git commit -m "Wire PlaceInfoService into render_map's point-annotation step"
```

---

## Task 8: Route-stats sidebar block with backward compatibility (Review Focus #2)

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Test: `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Produces: `render_map.route_stats_html(line_properties: dict, user_lang: str) -> str` — an HTML snippet built from the `LineString`'s properties (spec §3.11/§6.2); every field is read with `.get(...)`, and a missing `mode` renders as `"walk"` rather than raising or leaving a blank label.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-show/tests/test_render_map.py
from render_map import route_stats_html


def test_route_stats_html_includes_all_present_fields():
    props = {
        "mode": "bike", "style": "leisure", "distance_km": 12.3,
        "elevation_gain_m": 150.0, "elevation_loss_m": 140.0,
        "duration_estimate_hours": 2.5, "duration_warning": None,
        "curated_routes_count": 4, "is_loop": True,
        "skipped_interest_points": ["Дальняя точка"],
    }

    html = route_stats_html(props, user_lang="ru")

    assert "12.3" in html
    assert "150" in html
    assert "Дальняя точка" in html


def test_route_stats_html_defaults_missing_mode_to_walk():
    """Review Focus #2: an archive from before this round has no `mode`."""
    html = route_stats_html({}, user_lang="ru")
    assert "walk" in html or "пешком" in html


def test_route_stats_html_omits_warning_line_when_none():
    props = {"mode": "walk", "duration_warning": None}
    html = route_stats_html(props, user_lang="ru")
    assert "duration-warning" not in html.lower() or "None" not in html


def test_route_stats_html_shows_warning_text_when_present():
    props = {"mode": "walk", "duration_warning": "маршрут может не влезть в световой день"}
    html = route_stats_html(props, user_lang="ru")
    assert "маршрут может не влезть в световой день" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'route_stats_html'`

- [ ] **Step 3: Write the minimal implementation and wire it into `build_map_html`**

```python
_MODE_LABELS = {
    "en": {"walk": "walking", "bike": "cycling"},
    "ru": {"walk": "пешком", "bike": "на велосипеде"},
}


def route_stats_html(line_properties: dict, user_lang: str) -> str:
    """Built from computed LineString properties (spec §3.11), never from
    weights.json — this function never sees weights.json at all. A
    pre-this-round archive with none of these properties still renders a
    walk-labeled, mostly-empty block instead of raising."""
    mode = line_properties.get("mode", "walk")
    mode_label = _MODE_LABELS.get(user_lang, _MODE_LABELS["en"]).get(mode, mode)
    parts = [f"<p>{mode_label}"]
    if line_properties.get("style"):
        parts[-1] += f" ({line_properties['style']})"
    parts[-1] += "</p>"

    if line_properties.get("distance_km") is not None:
        parts.append(f"<p>{line_properties['distance_km']:.1f} km</p>")
    if line_properties.get("elevation_gain_m") is not None:
        parts.append(
            f"<p>+{line_properties['elevation_gain_m']:.0f}m / "
            f"-{line_properties.get('elevation_loss_m', 0.0):.0f}m</p>"
        )
    if line_properties.get("duration_estimate_hours") is not None:
        parts.append(f"<p>~{line_properties['duration_estimate_hours']:.1f} h</p>")
    if line_properties.get("curated_routes_count"):
        parts.append(f"<p>{line_properties['curated_routes_count']} curated routes nearby</p>")
    if line_properties.get("duration_warning"):
        parts.append(f'<p class="duration-warning">{_xml_escape(line_properties["duration_warning"])}</p>')
    skipped = line_properties.get("skipped_interest_points") or []
    if skipped:
        skipped_list = ", ".join(_xml_escape(name) for name in skipped)
        parts.append(f"<p>Not included (over budget): {skipped_list}</p>")

    return "".join(parts)
```

Wire it into `build_map_html`, right after `access_html`/`confidence_html` are built:

```python
    line_feature = next((f for f in geojson.get("features", []) if f["geometry"]["type"] == "LineString"), None)
    stats_html = f"<h3>Route</h3>{route_stats_html(line_feature['properties'], user_lang)}" if line_feature else ""
```

and include `{stats_html}` in the sidebar `<div>` template string, right after the `<h3 style="margin-top:0">{title_escaped}</h3>` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_render_map.py
git commit -m "Add route-stats sidebar block with walk-mode fallback (Review Focus #2)"
```

---

## Task 9: Access-point popup shows `opening_hours`/`access_notes`, and every point shows its `_placeInfo`

**Files:**
- Modify: `skills/osm-day-route-show/scripts/render_map.py`
- Test: `skills/osm-day-route-show/tests/test_render_map.py`

**Interfaces:**
- Produces: `render_map.point_popup_html(properties: dict) -> str` — the popup body for one `Point` feature, replacing the ad hoc string-building previously inlined in the page's JS `pointToLayer` callback for the parts that are now server-side-computable (name/type/note/source were already there; `opening_hours`/`access_notes`/`_placeInfo` are new).

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/osm-day-route-show/tests/test_render_map.py
from render_map import point_popup_html


def test_point_popup_includes_opening_hours_and_access_notes_for_access_point():
    props = {
        "name": "Станция Бажуково", "type": "access", "role": "start",
        "opening_hours": "Mo-Su 06:00-23:00", "access_notes": "Билеты у кондуктора.",
    }

    html = point_popup_html(props)

    assert "Mo-Su 06:00-23:00" in html
    assert "Билеты у кондуктора." in html


def test_point_popup_includes_all_place_info_entries():
    props = {
        "name": "Родник", "type": "spring",
        "_placeInfo": [
            {"provider_id": "wikidata", "summary": "источник питьевой воды"},
            {"provider_id": "wikimedia_commons", "image_url": "https://commons.wikimedia.org/wiki/File:X.jpg"},
        ],
    }

    html = point_popup_html(props)

    assert "источник питьевой воды" in html
    assert "https://commons.wikimedia.org/wiki/File:X.jpg" in html
    assert "wikidata" in html
    assert "wikimedia_commons" in html


def test_point_popup_omits_placeinfo_block_when_nothing_found():
    html = point_popup_html({"name": "Точка", "type": "waypoint"})
    assert "_placeInfo" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'point_popup_html'`

- [ ] **Step 3: Write the minimal implementation**

```python
def point_popup_html(properties: dict) -> str:
    """Server-side-rendered popup body — the parts of it that depend only
    on route.geojson properties (not on the client-side tier/type label
    lookup tables, which stay in the page's own JS since they're
    language-dependent, see build_map_html)."""
    parts = []
    if properties.get("opening_hours"):
        parts.append(f"<p>{_xml_escape(properties['opening_hours'])}</p>")
    if properties.get("access_notes"):
        parts.append(f"<p>{_xml_escape(properties['access_notes'])}</p>")
    for entry in properties.get("_placeInfo", []):
        provider_id = entry.get("provider_id", "")
        bits = [f"<b>{_xml_escape(provider_id)}</b>"]
        if entry.get("summary"):
            bits.append(_xml_escape(entry["summary"]))
        if entry.get("url"):
            bits.append(f'<a href="{entry["url"]}" target="_blank" rel="noopener">{entry["url"]}</a>')
        if entry.get("image_url"):
            bits.append(f'<a href="{entry["image_url"]}" target="_blank" rel="noopener">{entry["image_url"]}</a>')
        parts.append(f"<p>{' — '.join(bits)}</p>")
    return "".join(parts)
```

Wire this into the geojson passed to the client: since the existing popup is built in client-side JS (inside the big f-string template in `build_map_html`), the simplest integration is to precompute `properties["_popupExtra"] = point_popup_html(properties)` for every Point feature right before `geojson_json = json.dumps(geojson)` in `build_map_html`, then have the JS `popup +=` chain append `props._popupExtra || ''` right before `marker.bindPopup(popup);`. Add this one-line loop in `build_map_html`:

```python
    for feature in geojson.get("features", []):
        if feature["geometry"]["type"] == "Point":
            feature["properties"]["_popupExtra"] = point_popup_html(feature["properties"])
```

And in the JS template, change:

```js
      if (props._wikiUrl) { ... }
      marker.bindPopup(popup);
```

to:

```js
      if (props._popupExtra) popup += props._popupExtra;
      marker.bindPopup(popup);
```

removing the now-dead `props._wikiUrl`/`WIKIPEDIA_LABEL` block (that data no longer exists on any feature — `_placeInfo` replaced it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render_map.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-show/scripts/render_map.py skills/osm-day-route-show/tests/test_render_map.py
git commit -m "Render opening_hours/access_notes and all place_info entries in point popups"
```

---

## Task 10: `SKILL.md` for `osm-day-route-show`

**Files:**
- Create: `skills/osm-day-route-show/SKILL.md` (adapted from `init-raw-source/osm-hike-route-show/SKILL.md`)

No automated test — documentation, checked by hand against this plan's Global Constraints and Review Focus.

- [ ] **Step 1: Write `SKILL.md`, adapting the existing file**

Base it on `init-raw-source/osm-hike-route-show/SKILL.md`, keeping its structure (Overview, When to Use, How to Use, Direction-of-Travel Arrows, Export & External Links, Languages & Localization, Wikipedia Links, Expected GeoJSON Property Schema, Mobile, Common Mistakes) and updating it:

- Frontmatter `name: osm-day-route-show`; rename every `osm-hike-route-planning`/`osm-hike-route-show` reference to the `osm-day-route-*` names throughout.
- Replace the **Wikipedia Links** section with a **Place Info** section describing the four plugins (Wikipedia/Wikidata/Wikimedia Commons/OpenTripMap), that all four run independently and every result is shown (not just the best), and that `place_info.json` is the one shared cache file for both interest points and access points.
- Add a **Configuration** section: how to set `OSM_DAY_ROUTE_OPENTRIPMAP_KEY` (or pass `opentripmap_api_key` directly) for the optional richer plugin, and that its absence is not an error.
- **Expected GeoJSON Property Schema** table: add `opening_hours`, `access_notes` for access points, and the `LineString`-level fields (`mode`, `style`, `distance_km`, `elevation_gain_m`/`elevation_loss_m`, `duration_estimate_hours`, `duration_warning`, `curated_routes_count`, `is_loop`, `skipped_interest_points`) with a note that a missing `mode` renders as `walk`.
- **Common Mistakes**: add the five Review Focus items from this plan's header, phrased as mistakes to avoid, alongside the existing ones (tile provider caveats, GPX caveats, etc. all stay — they're unaffected by this round's changes).

- [ ] **Step 2: Read the finished `SKILL.md` back and check it against this plan's Global Constraints and Review Focus lists**

Confirm each Global Constraint and each Review Focus item has at least one corresponding sentence — add anything missing before moving on.

- [ ] **Step 3: Commit**

```bash
git add skills/osm-day-route-show/SKILL.md
git commit -m "Write SKILL.md for osm-day-route-show"
```

---

## Post-plan manual verification (not part of the automated suite)

1. Run `osm-day-route-planning`'s output (from a real Task-set run of the sibling plan, or a hand-written `route.geojson` matching spec §3.11's schema) through `render_map.py` and open the resulting HTML in a real browser — confirm the sidebar stats, GPX download (with elevation), and point popups (including a point with multiple `_placeInfo` entries) all render correctly.
2. Confirm at least one of the four `place_info` providers returns real data from this environment for a well-known point (e.g. a capital city's central square) — a fully offline sandbox would make every plugin legitimately return nothing, which Task 6/9 already handle gracefully but is worth knowing about ahead of time.
3. Render an old, pre-this-round archive (2D coordinates, no `mode`/`style`/`_placeInfo`-eligible properties) from `init-raw-source`'s own example output, if one exists, or a hand-crafted minimal fixture — confirm it still renders without exceptions (Review Focus #2).

---

**Plan complete and saved to `docs/superpowers/plans/2026-09-28-osm-day-route-show.md`.**
