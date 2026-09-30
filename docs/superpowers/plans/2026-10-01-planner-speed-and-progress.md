# Planner Speed, Console Progress and Elevation Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the planner's graph stage fast (measured: `tag_edges` 37–59 s down to under 1 s on real data), show the user what a long planning run is doing in the user's own language, cache Overpass answers, and store elevations in `route.geojson` to 0.1 m.

**Architecture:** Pure speed-ups with oracle tests (the old computation is kept in the tests and compared on random inputs and on real data); a stdlib `progress.py` with a seven-language message catalogue and an optional `progress=None` parameter on the slow functions; an on-disk Overpass cache keyed by the query text; rounding in `build_geojson`.

**Tech Stack:** Python 3 stdlib only, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-planner-speed-and-progress-design.md`.

**Deviations from the spec (decided while building, all small):** thousands are separated by a no-break space (U+00A0) rather than a thin space (terminals render it reliably); without a terminal a sub-progress line is printed at most every 5 s and only while a step is running (a step that finishes fast prints no ticks, the done line is its end); a retry or endpoint switch is noted, the first attempt is silent; the plugin names in the day-plan progress lines are a new string family `pl_<plugin_id>` in all seven languages (the existing `hz_*` titles exist in en/ru only); a step can be named with a caller-localized `text=` and can be marked failed with `step.fail(reason)` without raising.

## Global Constraints

- Every script stays stdlib-only; no network in the automated tests.
- A speed-up must give exactly the old result: the oracle tests compare on random inputs, and Task 8 compares `tag_edges` on real data.
- Everything the user reads in the progress output comes from the message catalogue in the user's language (`en ru es fr de pt it`, English for any other language or any missing key); an unknown key prints the key and never raises; a missing placeholder never raises.
- Without a terminal only plain lines are written (no carriage returns, no colour); with `NO_COLOR` set no colour at all.
- `progress=None` is the default everywhere and changes nothing for existing callers; progress goes to stderr.
- The Overpass cache is at most 24 h old by default; `refresh=True` bypasses it; a cache failure never fails a query.
- Elevations in `route.geojson` are rounded to 0.1 m; the elevation cache keeps full precision.
- The two `progress.py` files are byte-identical.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- The old and the new `tag_edges` and `select_optional_points` must agree on unreachable candidates, a one-node path, a loop path (the start repeats), nodes without coordinates and edges exactly on a polygon's bounding box.
- A cache entry that is expired, truncated, corrupted or unreadable, or a read-only cache folder: the query is made and the plan goes on.
- Progress must never change a result or raise into the planning run (missing placeholders, unknown keys and languages, a stream without `isatty` or with a narrow encoding).
- A Russian run prints no English words in the progress lines (except exception texts and host names).
- Day-plan tests and library callers get no progress output; the existing stdout lines and stderr warnings stay as they were.

---

### Task 1: Elevations are stored to 0.1 m in route.geojson

`build_geojson` rounds every elevation it writes (LineString vertices and Point features) and `elevation_gain_m` / `elevation_loss_m` to 0.1 m. Coordinates and `distance_km` keep their precision; an unknown vertex elevation is still `0.0` and an unknown point elevation is still left out.

**Files:**
- Modify: `skills/osm-day-route-planning/tests/test_route_output.py`
- Modify: `skills/osm-day-route-planning/scripts/route_output.py`

- [ ] **Step 1: Add the tests** (9 tests in the file(s) below)

Modify `skills/osm-day-route-planning/tests/test_route_output.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/tests/test_route_output.py
+++ b/skills/osm-day-route-planning/tests/test_route_output.py
@@ -90,3 +90,25 @@
     import inspect
     assert inspect.signature(build_geojson).parameters["way_segments"].default is inspect.Parameter.empty
 
+
+
+def test_elevations_are_stored_to_a_tenth_of_a_metre():
+    result = _sample_call(
+        path_coords=[(37.0, 55.0, 682.020635343171), (37.001, 55.001, 542.0), (37.002, 55.002, 100.04)],
+        elevation_gain_m=840.3456, elevation_loss_m=839.96,
+        point_features=[{"lon": 37.0005, "lat": 55.0005, "ele": 615.9931371309518, "name": "P", "type": "viewpoint"}])
+    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
+    assert [c[2] for c in line["geometry"]["coordinates"]] == [682.0, 542.0, 100.0]
+    assert line["properties"]["elevation_gain_m"] == 840.3 and line["properties"]["elevation_loss_m"] == 840.0
+    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")
+    assert point["geometry"]["coordinates"] == [37.0005, 55.0005, 616.0]
+
+
+def test_rounding_keeps_coordinates_and_the_unknown_elevation_rules():
+    result = _sample_call(
+        path_coords=[(37.123456789, 55.987654321, None), (37.1, 55.9, 10.0)],
+        point_features=[{"lon": 37.0, "lat": 55.0, "ele": None, "name": "P", "type": "viewpoint"}])
+    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
+    assert line["geometry"]["coordinates"][0] == [37.123456789, 55.987654321, 0.0]     # unknown stays 0.0
+    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")
+    assert point["geometry"]["coordinates"] == [37.0, 55.0]                              # and no elevation for a point
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-planning && python3 -m pytest tests/test_route_output.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-planning/scripts/route_output.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/scripts/route_output.py
+++ b/skills/osm-day-route-planning/scripts/route_output.py
@@ -2,6 +2,13 @@
 coordinates, and LineString properties that hold computed OUTPUTS only
 (never duplicating weights.json's inputs)."""
 
+ELEVATION_DECIMALS = 1                      # elevations are stored to 0.1 m: the source data is ~30 m resolution
+
+
+def _round_elevation(value):
+    return round(value, ELEVATION_DECIMALS)
+
+
 _OPTIONAL_POINT_KEYS = (
     "note", "source", "osm_id", "wikidata", "wikipedia", "search_names",
     "opening_hours", "access_notes",
@@ -11,7 +18,7 @@
 def _point_feature(pf: dict) -> dict:
     coords = [pf["lon"], pf["lat"]]
     if pf.get("ele") is not None:
-        coords.append(pf["ele"])
+        coords.append(_round_elevation(pf["ele"]))
     properties = {"name": pf["name"], "type": pf["type"]}
     if pf.get("tier") is not None:
         properties["tier"] = pf["tier"]
@@ -30,15 +37,16 @@
         "type": "Feature",
         "geometry": {
             "type": "LineString",
-            "coordinates": [[lon, lat, ele if ele is not None else 0.0] for lon, lat, ele in path_coords],
+            "coordinates": [[lon, lat, _round_elevation(ele) if ele is not None else 0.0]
+                            for lon, lat, ele in path_coords],
         },
         "properties": {
             "name": route_name,
             "mode": mode,
             "style": style,
             "distance_km": distance_km,
-            "elevation_gain_m": elevation_gain_m,
-            "elevation_loss_m": elevation_loss_m,
+            "elevation_gain_m": _round_elevation(elevation_gain_m),
+            "elevation_loss_m": _round_elevation(elevation_loss_m),
             "duration_estimate_hours": duration_estimate_hours,
             "duration_warning": duration_warning,
             "curated_routes_count": curated_routes_count,
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "route_output: elevations to 0.1 m

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 2: progress.py: console progress in the user's language

A stdlib-only module with a message catalogue in seven languages (`MESSAGES[key][lang]`; callers pass a key and parameters, never free text), a `Progress` class (steps with a `[i/N]` counter, rate-limited sub-progress, plain lines without a terminal, in-place line and colour on a terminal, `NO_COLOR`, ASCII marks for a stream that cannot print them) and a do-nothing `NullProgress`. The same file is kept in the day-plan skill (`day_plan/progress.py`); a planning test compares them. Nothing uses it yet.

**Files:**
- Create: `skills/osm-day-route-planning/tests/test_progress.py`
- Create: `skills/osm-day-route-planning/scripts/progress.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/progress.py`

- [ ] **Step 1: Add the tests** (16 tests in the file(s) below)

Create `skills/osm-day-route-planning/tests/test_progress.py`:

```python
import io
import re
from pathlib import Path

import pytest

import progress as pr
from progress import LANGS, MESSAGES, NullProgress, Progress, format_number


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Stream(io.StringIO):
    def __init__(self, tty=False, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    @property
    def encoding(self):
        return self._encoding

    def isatty(self):
        return self._tty


def make(lang="en", tty=False, total=3, **kwargs):
    stream, clock = Stream(tty), Clock()
    return Progress(total_steps=total, lang=lang, stream=stream, clock=clock, **kwargs), stream, clock


def test_a_plain_step_prints_a_start_line_and_a_done_line():
    progress, stream, clock = make()
    with progress.step("graph"):
        clock.advance(0.14)
        progress.detail("graph_done", nodes=35398, edges=72658)
    assert stream.getvalue().splitlines() == [
        "[1/3] Road graph …", "      ✓ 0.1 s · 35 398 nodes, 72 658 edges"]


def test_the_counter_advances_and_works_without_a_known_total():
    progress, stream, _ = make(total=None)
    with progress.step("graph"):
        pass
    with progress.step("elevation"):
        pass
    assert [l for l in stream.getvalue().splitlines() if l.startswith("[")] == ["[1] Road graph …", "[2] Elevations …"]


def test_russian_output_uses_a_decimal_comma_and_russian_words():
    progress, stream, clock = make("ru")
    with progress.step("graph"):
        clock.advance(2.4)
        progress.detail("graph_done", nodes=1234, edges=5)
    assert stream.getvalue().splitlines() == ["[1/3] Граф дорог …", "      ✓ 2,4 с · 1\u00a0234 вершин, 5 рёбер"]


def test_a_russian_run_prints_no_english_words():
    progress, stream, clock = make("ru", total=None)
    for key in ("overpass", "graph", "tag_edges", "elevation", "routing", "optional"):
        with progress.step(key):
            clock.advance(0.5)
    progress.note("overpass_cache_hit", age=3)
    progress.warn("overpass_failed", endpoint="overpass-api.de", reason="HTTP 504")
    with progress.step("overpass"):
        progress.detail("overpass_done", walkable=3, restricted=1)
    text = stream.getvalue()
    assert not re.search(r"\b(ways|nodes|edges|attempt|Road|Overpass query|cached|answer|did not)\b", text)


def test_an_unknown_language_falls_back_to_english_and_an_unknown_key_prints_the_key():
    progress, stream, _ = make("xx")
    with progress.step("graph"):
        pass
    progress.note("no_such_key")
    assert "Road graph" in stream.getvalue() and "no_such_key" in stream.getvalue()


def test_a_bad_placeholder_never_raises():
    progress, stream, _ = make()
    progress.note("overpass_attempt", endpoint="x")          # n and m missing
    assert "attempt" in stream.getvalue()


def test_ticks_without_a_terminal_are_rate_limited_and_never_shown_for_a_quick_step():
    progress, stream, clock = make()
    with progress.step("elevation"):
        for i in range(1, 11):
            clock.advance(0.2)
            progress.tick(i, 10, "elevation_batch")
    assert len(stream.getvalue().splitlines()) == 2                     # the start and the done line only

    progress, stream, clock = make()
    with progress.step("elevation"):
        for i in range(1, 92):
            clock.advance(0.3)                                          # 27 s in total
            progress.tick(i, 91, "elevation_batch")
    ticks = [l for l in stream.getvalue().splitlines() if l.startswith("      …")]
    assert 4 <= len(ticks) <= 6 and "elevation request" in ticks[0] and "%" in ticks[0]
    assert "\r" not in stream.getvalue() and "\x1b" not in stream.getvalue()


def test_a_terminal_rewrites_the_tick_line_and_colours_the_marks(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    progress, stream, clock = make(tty=True)
    with progress.step("elevation"):
        progress.tick(1, 4, "elevation_batch")
        progress.tick(2, 4, "elevation_batch")
    out = stream.getvalue()
    assert out.count("\r\x1b[K      …") == 2 and "\x1b[32m✓\x1b[0m" in out
    assert out.endswith("\n") and out.count("\n") == 2                  # the ticks stay on one screen line


def test_no_color_is_respected_on_a_terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    progress, stream, _ = make(tty=True)
    with progress.step("graph"):
        pass
    progress.warn("overpass_failed", endpoint="e", reason="r")
    assert "\x1b[3" not in stream.getvalue()


def test_an_exception_is_reported_in_one_line_and_reraised():
    progress, stream, clock = make()
    with pytest.raises(RuntimeError):
        with progress.step("graph"):
            clock.advance(1.0)
            raise RuntimeError("boom\nsecond line")
    assert stream.getvalue().splitlines()[-1] == "      ✗ 1.0 s · RuntimeError: boom second line"


def test_fail_marks_a_step_without_raising_and_text_replaces_the_title():
    progress, stream, _ = make()
    with progress.step("graph", text="Weather") as step:
        step.fail("HTTP 503")
    assert stream.getvalue().splitlines() == ["[1/3] Weather …", "      ✗ 0.0 s · HTTP 503"]


def test_a_stream_that_cannot_print_the_marks_gets_ascii():
    stream, clock = Stream(encoding="ascii"), Clock()
    progress = Progress(total_steps=1, stream=stream, clock=clock)
    with progress.step("graph"):
        pass
    assert "ok" in stream.getvalue() and "✓" not in stream.getvalue() and "..." in stream.getvalue()


def test_null_progress_accepts_every_call():
    progress = NullProgress()
    with progress.step("graph") as step:
        step.tick(1, 2)
        step.detail("graph_done", nodes=1, edges=2)
        step.fail("x")
    progress.tick(1, 2)
    progress.detail("graph_done")
    progress.note("x")
    progress.warn("x")


def test_format_number():
    assert format_number(1234567.5, "en", 1) == "1 234 567.5"
    assert format_number(1234567.5, "de", 1) == "1 234 567,5"
    assert format_number(0.04, "ru", 1) == "0,0"


def test_every_message_exists_in_every_language_with_the_same_placeholders():
    for key, entry in MESSAGES.items():
        assert set(entry) == set(LANGS), key
        placeholders = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in entry.items()}
        assert len({frozenset(p) for p in placeholders.values()}) == 1, (key, placeholders)


def test_the_day_plan_copy_is_identical():
    copy = Path(__file__).resolve().parents[2] / "osm-day-route-day-plan" / "scripts" / "day_plan" / "progress.py"
    if not copy.exists():
        pytest.skip("osm-day-route-day-plan is not next to this skill")
    assert copy.read_text(encoding="utf-8") == Path(pr.__file__).read_text(encoding="utf-8")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-planning && python3 -m pytest tests/test_progress.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `skills/osm-day-route-planning/scripts/progress.py`:

```python
"""Console progress for long planning runs, in the user's language.

Everything the user reads comes from MESSAGES (every key in all seven languages of osm-day-route-show); callers
pass a message key and parameters, never free text. Without a terminal (Claude Code's tool output, a log file)
only plain lines are written, each flushed at once; on a terminal the sub-progress line is rewritten in place and
coloured (NO_COLOR is respected). `NullProgress` is what every function uses when the caller passes nothing.

    progress = Progress(total_steps=3, lang="ru")
    with progress.step("graph") as step:          # [1/3] Граф дорог …
        ...
        progress.tick(done, total, "tag_progress")    #       … рёбра 5 000 из 36 320 (14 %)
        progress.detail("graph_done", nodes=35398, edges=72658)
                                                   #       ✓ 0,1 с · 35 398 вершин, 72 658 рёбер

The same file is kept in osm-day-route-day-plan/scripts/day_plan/progress.py (a planning test compares them).
"""
import os
import sys
import time

LANGS = ("en", "ru", "es", "fr", "de", "pt", "it")
TICK_INTERVAL_S = 5.0
_NBSP = " "


def _m(en, ru, es, fr, de, pt, it):
    return dict(zip(LANGS, (en, ru, es, fr, de, pt, it)))


MESSAGES = {
    "unit_s": _m("s", "с", "s", "s", "s", "s", "s"),
    # planner steps
    "overpass": _m("Overpass query", "Запрос к Overpass", "Consulta a Overpass", "Requête Overpass",
                   "Overpass-Abfrage", "Consulta ao Overpass", "Interrogazione Overpass"),
    "overpass_done": _m("{walkable} ways, {restricted} restricted areas", "{walkable} путей, {restricted} закрытых зон",
                        "{walkable} vías, {restricted} zonas restringidas", "{walkable} voies, {restricted} zones interdites",
                        "{walkable} Wege, {restricted} Sperrgebiete", "{walkable} vias, {restricted} zonas restritas",
                        "{walkable} vie, {restricted} zone vietate"),
    "overpass_cache_hit": _m("using the cached answer ({age} h old)", "использован сохранённый ответ (возраст {age} ч)",
                             "usando la respuesta guardada ({age} h)", "réponse en cache utilisée ({age} h)",
                             "gespeicherte Antwort verwendet ({age} h alt)", "a usar a resposta guardada ({age} h)",
                             "uso la risposta in cache ({age} h)"),
    "overpass_attempt": _m("{endpoint}: attempt {n} of {m}", "{endpoint}: попытка {n} из {m}",
                           "{endpoint}: intento {n} de {m}", "{endpoint} : tentative {n} sur {m}",
                           "{endpoint}: Versuch {n} von {m}", "{endpoint}: tentativa {n} de {m}",
                           "{endpoint}: tentativo {n} di {m}"),
    "overpass_failed": _m("{endpoint} did not answer ({reason})", "{endpoint} не ответил ({reason})",
                          "{endpoint} no respondió ({reason})", "{endpoint} n'a pas répondu ({reason})",
                          "{endpoint} hat nicht geantwortet ({reason})", "{endpoint} não respondeu ({reason})",
                          "{endpoint} non ha risposto ({reason})"),
    "graph": _m("Road graph", "Граф дорог", "Grafo de caminos", "Graphe des chemins", "Wegegraph", "Grafo de caminhos",
                "Grafo dei percorsi"),
    "graph_done": _m("{nodes} nodes, {edges} edges", "{nodes} вершин, {edges} рёбер", "{nodes} nodos, {edges} aristas",
                     "{nodes} nœuds, {edges} arêtes", "{nodes} Knoten, {edges} Kanten", "{nodes} nós, {edges} arestas",
                     "{nodes} nodi, {edges} archi"),
    "tag_edges": _m("Tagging edges: highways, water, forest", "Разметка рёбер: шоссе, вода, лес",
                    "Etiquetado de aristas: carreteras, agua, bosque", "Étiquetage des arêtes : routes, eau, forêt",
                    "Kanten markieren: Straßen, Wasser, Wald", "Marcação de arestas: estradas, água, floresta",
                    "Etichettatura degli archi: strade, acqua, bosco"),
    "tag_progress": _m("edges {done} of {total}", "рёбра {done} из {total}", "aristas {done} de {total}",
                       "arêtes {done} sur {total}", "Kanten {done} von {total}", "arestas {done} de {total}",
                       "archi {done} di {total}"),
    "elevation": _m("Elevations", "Высоты", "Altitudes", "Altitudes", "Höhen", "Altitudes", "Quote"),
    "elevation_batch": _m("elevation request {done} of {total}", "запрос высот {done} из {total}",
                          "consulta de altitudes {done} de {total}", "requête d'altitudes {done} sur {total}",
                          "Höhenabfrage {done} von {total}", "pedido de altitudes {done} de {total}",
                          "richiesta di quote {done} di {total}"),
    "elevation_done": _m("{points} points, {cached} from the cache", "{points} точек, из кэша: {cached}",
                         "{points} puntos, {cached} de la caché", "{points} points, {cached} depuis le cache",
                         "{points} Punkte, {cached} aus dem Cache", "{points} pontos, {cached} da cache",
                         "{points} punti, {cached} dalla cache"),
    "routing": _m("Routing", "Прокладка маршрута", "Trazado de la ruta", "Calcul de l'itinéraire", "Routenberechnung",
                  "Traçado do percurso", "Calcolo del percorso"),
    "route_leg": _m("leg {done} of {total}", "участок {done} из {total}", "tramo {done} de {total}",
                    "tronçon {done} sur {total}", "Abschnitt {done} von {total}", "troço {done} de {total}",
                    "tratto {done} di {total}"),
    "optional": _m("Optional points", "Необязательные точки", "Puntos opcionales", "Points facultatifs",
                   "Optionale Punkte", "Pontos opcionais", "Punti facoltativi"),
    "optional_run": _m("route searches {done} of {total}", "поисков пути {done} из {total}",
                       "búsquedas de ruta {done} de {total}", "recherches d'itinéraire {done} sur {total}",
                       "Routensuchen {done} von {total}", "pesquisas de percurso {done} de {total}",
                       "ricerche di percorso {done} di {total}"),
}


def _translate(key: str, lang: str, **params) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key                                              # an unknown key is shown as it is, never an error
    text = entry.get(lang) or entry["en"]
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def format_number(value, lang: str, decimals: int = 0) -> str:
    """1234567.5 -> '1 234 567,5' (no-break space between thousands; decimal comma except in English)."""
    text = f"{value:,.{decimals}f}".replace(",", _NBSP)
    return text if lang == "en" else text.replace(".", ",")


class _NullStep:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def fail(self, *args, **kwargs):
        pass


class NullProgress:
    """The default: every call does nothing."""

    def step(self, *args, **kwargs):
        return _NullStep()

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def note(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        pass


class Progress:
    def __init__(self, total_steps=None, lang="en", stream=None, clock=time.monotonic, tty=None, color=None,
                 tick_interval=TICK_INTERVAL_S):
        self.total_steps = total_steps
        self.lang = lang if lang in LANGS else "en"
        self.stream = stream if stream is not None else sys.stderr
        self._clock = clock
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)()) if tty is None else tty
        self._color = (self._tty and not os.environ.get("NO_COLOR")) if color is None else color
        self._interval = tick_interval
        encoding = (getattr(self.stream, "encoding", None) or "utf-8")
        try:
            "✓✗·…".encode(encoding)
            self._ok, self._bad, self._dot, self._dots = "✓", "✗", "·", "…"
        except (UnicodeEncodeError, LookupError):
            self._ok, self._bad, self._dot, self._dots = "ok", "x", "-", "..."
        self._count = 0
        self._current = None
        self._last_tick = None
        self._live = False                                      # a tick line is on screen (terminal only)

    # ---- output helpers -------------------------------------------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self._color else text

    def _write(self, line: str) -> None:
        if self._live:
            self.stream.write("\r\x1b[K")
            self._live = False
        self.stream.write(line + "\n")
        self.stream.flush()

    def _seconds(self, seconds: float) -> str:
        return f"{format_number(seconds, self.lang, 1)} {_translate('unit_s', self.lang)}"

    def _text(self, key, params) -> str:
        shown = {k: format_number(v, self.lang) if isinstance(v, int) and not isinstance(v, bool) else v
                 for k, v in params.items()}
        return _translate(key, self.lang, **shown)

    # ---- steps ----------------------------------------------------------------------------------------------------
    def step(self, key: str, text: str | None = None, **params):
        """Context manager for one pipeline step. `text` replaces the catalogue title (a caller-localized name,
        e.g. a section heading); otherwise the title is MESSAGES[key]."""
        return _Step(self, key, text, params)

    def tick(self, done, total, key: str = "tag_progress", **params) -> None:
        """Sub-progress of the current step: MESSAGES[key] gets done/total. Without a terminal at most one line
        every `tick_interval` seconds (and never for a step that finishes quickly)."""
        now = self._clock()
        percent = int(100 * done / total) if total else 100
        message = f"{self._dots} {self._text(key, dict(params, done=done, total=total))} ({percent} %)"
        if self._tty:
            self.stream.write("\r\x1b[K      " + message)
            self.stream.flush()
            self._live = True
            return
        if self._last_tick is None:
            self._last_tick = now if self._current is None else self._current.started
        if now - self._last_tick >= self._interval:
            self._last_tick = now
            self._write("      " + message)

    def detail(self, key: str, **params) -> None:
        if self._current is not None:
            self._current.detail_text = self._text(key, params)

    def note(self, key: str, **params) -> None:
        self._write(f"      {self._dot} {self._text(key, params)}")

    def warn(self, key: str, **params) -> None:
        self._write("  " + self._paint("!", "33") + f" {self._text(key, params)}")


class _Step:
    def __init__(self, progress, key, text, params):
        self.p = progress
        self.key, self.text, self.params = key, text, params
        self.detail_text = None
        self.failure = None
        self.started = 0.0

    def __enter__(self):
        p = self.p
        p._count += 1
        p._current = self
        p._last_tick = None
        title = self.text if self.text is not None else p._text(self.key, self.params)
        counter = f"[{p._count}/{p.total_steps}]" if p.total_steps else f"[{p._count}]"
        p._write(f"{counter} {title} {p._dots}")
        self.started = p._clock()
        return self

    def tick(self, done, total, key="tag_progress", **params):
        self.p.tick(done, total, key, **params)

    def detail(self, key, **params):
        self.detail_text = self.p._text(key, params)

    def fail(self, reason: str):
        self.failure = " ".join(str(reason).split())

    def __exit__(self, exc_type, exc, tb):
        p = self.p
        seconds = p._seconds(p._clock() - self.started)
        if exc_type is not None:
            reason = " ".join(f"{exc_type.__name__}: {exc}".split())
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {reason}")
        elif self.failure is not None:
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {self.failure}")
        else:
            extra = f" {p._dot} {self.detail_text}" if self.detail_text else ""
            p._write("      " + p._paint(p._ok, "32") + f" {seconds}{extra}")
        p._current = None
        return False
```

Create `skills/osm-day-route-day-plan/scripts/day_plan/progress.py`:

```python
"""Console progress for long planning runs, in the user's language.

Everything the user reads comes from MESSAGES (every key in all seven languages of osm-day-route-show); callers
pass a message key and parameters, never free text. Without a terminal (Claude Code's tool output, a log file)
only plain lines are written, each flushed at once; on a terminal the sub-progress line is rewritten in place and
coloured (NO_COLOR is respected). `NullProgress` is what every function uses when the caller passes nothing.

    progress = Progress(total_steps=3, lang="ru")
    with progress.step("graph") as step:          # [1/3] Граф дорог …
        ...
        progress.tick(done, total, "tag_progress")    #       … рёбра 5 000 из 36 320 (14 %)
        progress.detail("graph_done", nodes=35398, edges=72658)
                                                   #       ✓ 0,1 с · 35 398 вершин, 72 658 рёбер

The same file is kept in osm-day-route-day-plan/scripts/day_plan/progress.py (a planning test compares them).
"""
import os
import sys
import time

LANGS = ("en", "ru", "es", "fr", "de", "pt", "it")
TICK_INTERVAL_S = 5.0
_NBSP = " "


def _m(en, ru, es, fr, de, pt, it):
    return dict(zip(LANGS, (en, ru, es, fr, de, pt, it)))


MESSAGES = {
    "unit_s": _m("s", "с", "s", "s", "s", "s", "s"),
    # planner steps
    "overpass": _m("Overpass query", "Запрос к Overpass", "Consulta a Overpass", "Requête Overpass",
                   "Overpass-Abfrage", "Consulta ao Overpass", "Interrogazione Overpass"),
    "overpass_done": _m("{walkable} ways, {restricted} restricted areas", "{walkable} путей, {restricted} закрытых зон",
                        "{walkable} vías, {restricted} zonas restringidas", "{walkable} voies, {restricted} zones interdites",
                        "{walkable} Wege, {restricted} Sperrgebiete", "{walkable} vias, {restricted} zonas restritas",
                        "{walkable} vie, {restricted} zone vietate"),
    "overpass_cache_hit": _m("using the cached answer ({age} h old)", "использован сохранённый ответ (возраст {age} ч)",
                             "usando la respuesta guardada ({age} h)", "réponse en cache utilisée ({age} h)",
                             "gespeicherte Antwort verwendet ({age} h alt)", "a usar a resposta guardada ({age} h)",
                             "uso la risposta in cache ({age} h)"),
    "overpass_attempt": _m("{endpoint}: attempt {n} of {m}", "{endpoint}: попытка {n} из {m}",
                           "{endpoint}: intento {n} de {m}", "{endpoint} : tentative {n} sur {m}",
                           "{endpoint}: Versuch {n} von {m}", "{endpoint}: tentativa {n} de {m}",
                           "{endpoint}: tentativo {n} di {m}"),
    "overpass_failed": _m("{endpoint} did not answer ({reason})", "{endpoint} не ответил ({reason})",
                          "{endpoint} no respondió ({reason})", "{endpoint} n'a pas répondu ({reason})",
                          "{endpoint} hat nicht geantwortet ({reason})", "{endpoint} não respondeu ({reason})",
                          "{endpoint} non ha risposto ({reason})"),
    "graph": _m("Road graph", "Граф дорог", "Grafo de caminos", "Graphe des chemins", "Wegegraph", "Grafo de caminhos",
                "Grafo dei percorsi"),
    "graph_done": _m("{nodes} nodes, {edges} edges", "{nodes} вершин, {edges} рёбер", "{nodes} nodos, {edges} aristas",
                     "{nodes} nœuds, {edges} arêtes", "{nodes} Knoten, {edges} Kanten", "{nodes} nós, {edges} arestas",
                     "{nodes} nodi, {edges} archi"),
    "tag_edges": _m("Tagging edges: highways, water, forest", "Разметка рёбер: шоссе, вода, лес",
                    "Etiquetado de aristas: carreteras, agua, bosque", "Étiquetage des arêtes : routes, eau, forêt",
                    "Kanten markieren: Straßen, Wasser, Wald", "Marcação de arestas: estradas, água, floresta",
                    "Etichettatura degli archi: strade, acqua, bosco"),
    "tag_progress": _m("edges {done} of {total}", "рёбра {done} из {total}", "aristas {done} de {total}",
                       "arêtes {done} sur {total}", "Kanten {done} von {total}", "arestas {done} de {total}",
                       "archi {done} di {total}"),
    "elevation": _m("Elevations", "Высоты", "Altitudes", "Altitudes", "Höhen", "Altitudes", "Quote"),
    "elevation_batch": _m("elevation request {done} of {total}", "запрос высот {done} из {total}",
                          "consulta de altitudes {done} de {total}", "requête d'altitudes {done} sur {total}",
                          "Höhenabfrage {done} von {total}", "pedido de altitudes {done} de {total}",
                          "richiesta di quote {done} di {total}"),
    "elevation_done": _m("{points} points, {cached} from the cache", "{points} точек, из кэша: {cached}",
                         "{points} puntos, {cached} de la caché", "{points} points, {cached} depuis le cache",
                         "{points} Punkte, {cached} aus dem Cache", "{points} pontos, {cached} da cache",
                         "{points} punti, {cached} dalla cache"),
    "routing": _m("Routing", "Прокладка маршрута", "Trazado de la ruta", "Calcul de l'itinéraire", "Routenberechnung",
                  "Traçado do percurso", "Calcolo del percorso"),
    "route_leg": _m("leg {done} of {total}", "участок {done} из {total}", "tramo {done} de {total}",
                    "tronçon {done} sur {total}", "Abschnitt {done} von {total}", "troço {done} de {total}",
                    "tratto {done} di {total}"),
    "optional": _m("Optional points", "Необязательные точки", "Puntos opcionales", "Points facultatifs",
                   "Optionale Punkte", "Pontos opcionais", "Punti facoltativi"),
    "optional_run": _m("route searches {done} of {total}", "поисков пути {done} из {total}",
                       "búsquedas de ruta {done} de {total}", "recherches d'itinéraire {done} sur {total}",
                       "Routensuchen {done} von {total}", "pesquisas de percurso {done} de {total}",
                       "ricerche di percorso {done} di {total}"),
}


def _translate(key: str, lang: str, **params) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key                                              # an unknown key is shown as it is, never an error
    text = entry.get(lang) or entry["en"]
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def format_number(value, lang: str, decimals: int = 0) -> str:
    """1234567.5 -> '1 234 567,5' (no-break space between thousands; decimal comma except in English)."""
    text = f"{value:,.{decimals}f}".replace(",", _NBSP)
    return text if lang == "en" else text.replace(".", ",")


class _NullStep:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def fail(self, *args, **kwargs):
        pass


class NullProgress:
    """The default: every call does nothing."""

    def step(self, *args, **kwargs):
        return _NullStep()

    def tick(self, *args, **kwargs):
        pass

    def detail(self, *args, **kwargs):
        pass

    def note(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        pass


class Progress:
    def __init__(self, total_steps=None, lang="en", stream=None, clock=time.monotonic, tty=None, color=None,
                 tick_interval=TICK_INTERVAL_S):
        self.total_steps = total_steps
        self.lang = lang if lang in LANGS else "en"
        self.stream = stream if stream is not None else sys.stderr
        self._clock = clock
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)()) if tty is None else tty
        self._color = (self._tty and not os.environ.get("NO_COLOR")) if color is None else color
        self._interval = tick_interval
        encoding = (getattr(self.stream, "encoding", None) or "utf-8")
        try:
            "✓✗·…".encode(encoding)
            self._ok, self._bad, self._dot, self._dots = "✓", "✗", "·", "…"
        except (UnicodeEncodeError, LookupError):
            self._ok, self._bad, self._dot, self._dots = "ok", "x", "-", "..."
        self._count = 0
        self._current = None
        self._last_tick = None
        self._live = False                                      # a tick line is on screen (terminal only)

    # ---- output helpers -------------------------------------------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self._color else text

    def _write(self, line: str) -> None:
        if self._live:
            self.stream.write("\r\x1b[K")
            self._live = False
        self.stream.write(line + "\n")
        self.stream.flush()

    def _seconds(self, seconds: float) -> str:
        return f"{format_number(seconds, self.lang, 1)} {_translate('unit_s', self.lang)}"

    def _text(self, key, params) -> str:
        shown = {k: format_number(v, self.lang) if isinstance(v, int) and not isinstance(v, bool) else v
                 for k, v in params.items()}
        return _translate(key, self.lang, **shown)

    # ---- steps ----------------------------------------------------------------------------------------------------
    def step(self, key: str, text: str | None = None, **params):
        """Context manager for one pipeline step. `text` replaces the catalogue title (a caller-localized name,
        e.g. a section heading); otherwise the title is MESSAGES[key]."""
        return _Step(self, key, text, params)

    def tick(self, done, total, key: str = "tag_progress", **params) -> None:
        """Sub-progress of the current step: MESSAGES[key] gets done/total. Without a terminal at most one line
        every `tick_interval` seconds (and never for a step that finishes quickly)."""
        now = self._clock()
        percent = int(100 * done / total) if total else 100
        message = f"{self._dots} {self._text(key, dict(params, done=done, total=total))} ({percent} %)"
        if self._tty:
            self.stream.write("\r\x1b[K      " + message)
            self.stream.flush()
            self._live = True
            return
        if self._last_tick is None:
            self._last_tick = now if self._current is None else self._current.started
        if now - self._last_tick >= self._interval:
            self._last_tick = now
            self._write("      " + message)

    def detail(self, key: str, **params) -> None:
        if self._current is not None:
            self._current.detail_text = self._text(key, params)

    def note(self, key: str, **params) -> None:
        self._write(f"      {self._dot} {self._text(key, params)}")

    def warn(self, key: str, **params) -> None:
        self._write("  " + self._paint("!", "33") + f" {self._text(key, params)}")


class _Step:
    def __init__(self, progress, key, text, params):
        self.p = progress
        self.key, self.text, self.params = key, text, params
        self.detail_text = None
        self.failure = None
        self.started = 0.0

    def __enter__(self):
        p = self.p
        p._count += 1
        p._current = self
        p._last_tick = None
        title = self.text if self.text is not None else p._text(self.key, self.params)
        counter = f"[{p._count}/{p.total_steps}]" if p.total_steps else f"[{p._count}]"
        p._write(f"{counter} {title} {p._dots}")
        self.started = p._clock()
        return self

    def tick(self, done, total, key="tag_progress", **params):
        self.p.tick(done, total, key, **params)

    def detail(self, key, **params):
        self.detail_text = self.p._text(key, params)

    def fail(self, reason: str):
        self.failure = " ".join(str(reason).split())

    def __exit__(self, exc_type, exc, tb):
        p = self.p
        seconds = p._seconds(p._clock() - self.started)
        if exc_type is not None:
            reason = " ".join(f"{exc_type.__name__}: {exc}".split())
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {reason}")
        elif self.failure is not None:
            p._write("      " + p._paint(p._bad, "31") + f" {seconds} {p._dot} {self.failure}")
        else:
            extra = f" {p._dot} {self.detail_text}" if self.detail_text else ""
            p._write("      " + p._paint(p._ok, "32") + f" {seconds}{extra}")
        p._current = None
        return False
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "progress.py: console progress in the user's language

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 3: Graph speed: landcover once per segment, one search per source; progress hooks

`tag_edges` computes the tags of the two directed edges of one physical segment once and tests only the polygons whose bounding box contains the midpoint (measured on the Pelayos data, 72 658 edges: 37 s to 0.8 s, identical tags; the tests keep the brute-force definition as an oracle). `shortest_costs` returns the costs from one node to many targets, and `select_optional_points` uses it: one search per distinct path node and one per candidate instead of three per consecutive pair per candidate, with identical results (oracle test). `fetch_area_data` passes `cache_dir`, `refresh` and `progress` to `query_overpass` only when given; `tag_edges`, `select_optional_points` and `route_through_waypoints` take an optional `progress` and tick it.

**Files:**
- Modify: `skills/osm-day-route-planning/tests/test_route_graph.py`
- Modify: `skills/osm-day-route-planning/tests/test_waypoints.py`
- Modify: `skills/osm-day-route-planning/scripts/route_graph.py`
- Modify: `skills/osm-day-route-planning/scripts/waypoints.py`

- [ ] **Step 1: Add the tests** (81 tests in the file(s) below)

Modify `skills/osm-day-route-planning/tests/test_route_graph.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/tests/test_route_graph.py
+++ b/skills/osm-day-route-planning/tests/test_route_graph.py
@@ -646,3 +646,121 @@
     grid = route_graph._VertexGrid([[vertex]], distance + 0.01)
     assert grid.near(56.0, 37.0 + east) and not route_graph._VertexGrid([[vertex]], distance - 0.01).near(56.0, 37.0 + east)
     assert route_graph._VertexGrid([], 50).near(56.0, 37.0) is False
+
+
+# ---- tag_edges: same tags as the brute-force computation, computed once per physical segment ---------------------------
+
+def _reference_tags(mid_lat, mid_lon, highways, water, forests, fields, highway_buffer_m, water_buffer_m):
+    """The original definition: distance to line vertices, point-in-ring against every ring."""
+    from overpass_query import haversine
+
+    def near(geoms, buffer_m):
+        return any(haversine(mid_lat, mid_lon, p["lat"], p["lon"]) < buffer_m for g in geoms for p in g)
+
+    def inside(rings):
+        return any(route_graph.point_in_ring(mid_lat, mid_lon, ring) for ring in rings)
+
+    landcover = "forest" if inside(forests) else "field" if inside(fields) else None
+    return {"near_highway": near(highways, highway_buffer_m), "near_water": near(water, water_buffer_m),
+            "landcover": landcover}
+
+
+def _random_world(seed):
+    import math
+    import random
+    rng = random.Random(seed)
+    lat0, lon0 = 40.36, -4.33
+
+    def pt():
+        return {"lat": lat0 + rng.uniform(-0.03, 0.03), "lon": lon0 + rng.uniform(-0.04, 0.04)}
+
+    def polygon():
+        cx, cy = pt()["lat"], pt()["lon"]
+        n = rng.randint(3, 9)
+        return [{"lat": cx + rng.uniform(0.002, 0.012) * (1 if i % 2 else 0.6) * math.cos(6.283 * i / n),
+                 "lon": cy + rng.uniform(0.003, 0.016) * (1 if i % 2 else 0.6) * math.sin(6.283 * i / n)}
+                for i in range(n)]
+
+    highways = [[pt() for _ in range(rng.randint(2, 8))] for _ in range(25)]
+    water = [[pt() for _ in range(rng.randint(2, 8))] for _ in range(25)]
+    forests = [polygon() for _ in range(12)]
+    fields = [polygon() for _ in range(6)]
+    coords = {i: (lat0 + rng.uniform(-0.03, 0.03), lon0 + rng.uniform(-0.04, 0.04)) for i in range(1, 301)}
+    graph = {i: [] for i in coords}
+    for _ in range(700):
+        a, b = rng.sample(sorted(coords), 2)
+        graph[a].append([b, 10.0, {}])
+        graph[b].append([a, 10.0, {}])
+    graph[1].append([999, 5.0, {}])                        # a neighbour without coordinates
+    return graph, coords, highways, water, forests, fields
+
+
+@pytest.mark.parametrize("seed", [1, 2, 3])
+def test_tag_edges_gives_the_brute_force_tags(seed):
+    graph, coords, highways, water, forests, fields = _random_world(seed)
+    route_graph.tag_edges(graph, coords, [{"geometry": g} for g in highways], [{"geometry": g} for g in water],
+                          [{"geometry": g} for g in forests], [{"geometry": g} for g in fields],
+                          highway_buffer_m=400, water_buffer_m=250)
+    forest_rings = [[(p["lat"], p["lon"]) for p in g] for g in forests]
+    field_rings = [[(p["lat"], p["lon"]) for p in g] for g in fields]
+    checked = {"forest": 0, "field": 0, "near_highway": 0, "near_water": 0}
+    for node, edges in graph.items():
+        for neighbor, _length, tags in edges:
+            lat1, lon1 = coords[node]
+            lat2, lon2 = coords.get(neighbor, (lat1, lon1))
+            expected = _reference_tags((lat1 + lat2) / 2, (lon1 + lon2) / 2, highways, water, forest_rings,
+                                       field_rings, 400, 250)
+            assert {k: tags[k] for k in expected} == expected
+            checked["forest"] += expected["landcover"] == "forest"
+            checked["field"] += expected["landcover"] == "field"
+            checked["near_highway"] += expected["near_highway"]
+            checked["near_water"] += expected["near_water"]
+    assert all(count > 0 for count in checked.values()), checked            # the world really exercises every branch
+
+
+def test_tag_edges_reports_progress_every_five_thousand_directed_edges(monkeypatch):
+    monkeypatch.setattr(route_graph, "TAG_PROGRESS_EVERY", 100)
+    graph, coords, highways, water, forests, fields = _random_world(4)
+
+    class Recorder:
+        def __init__(self):
+            self.ticks = []
+
+        def tick(self, done, total, key="tag_progress", **params):
+            self.ticks.append((done, total, key))
+
+    recorder = Recorder()
+    route_graph.tag_edges(graph, coords, [], [], [], [], progress=recorder)
+    total = sum(len(e) for e in graph.values())
+    assert [d for d, _, _ in recorder.ticks] == list(range(100, total + 1, 100))
+    assert all(t == total and k == "tag_progress" for _, t, k in recorder.ticks)
+
+
+def test_fetch_area_data_passes_cache_options_only_when_given():
+    captured = []
+
+    def fake(ql, **options):
+        captured.append(options)
+        return {"elements": []}
+
+    with patch.object(route_graph, "query_overpass", side_effect=fake):
+        fetch_area_data(55.0, 37.0)
+        fetch_area_data(55.0, 37.0, cache_dir="cache", refresh=True, progress="P")
+    assert captured == [{}, {"cache_dir": "cache", "refresh": True, "progress": "P"}]
+
+
+def test_route_through_waypoints_ticks_once_per_leg():
+    graph = {1: [[2, 100.0, {}]], 2: [[3, 100.0, {}]], 3: []}
+
+    class Recorder:
+        def __init__(self):
+            self.ticks = []
+
+        def tick(self, done, total, key="tag_progress", **params):
+            self.ticks.append((done, total, key))
+
+    recorder = Recorder()
+    path, cost, error = route_graph.route_through_waypoints(graph, [1, 2, 3], {}, progress=recorder)
+    assert path == [1, 2, 3] and error is None
+    assert recorder.ticks == [(1, 2, "route_leg"), (2, 2, "route_leg")]
+    assert route_graph.route_through_waypoints(graph, [3, 1], {})[2] == "no path between 3 and 1"
```

Modify `skills/osm-day-route-planning/tests/test_waypoints.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/tests/test_waypoints.py
+++ b/skills/osm-day-route-planning/tests/test_waypoints.py
@@ -148,3 +148,113 @@
 
     assert [c["name"] for c in included] == ["Рядом"]
     assert skipped == []
+
+
+# ---- the one-search-per-source selection gives the answers of the original three-searches-per-pair one -----------------
+
+import random
+
+import route_graph
+from waypoints import _TIER_RANK
+
+
+def _random_directed_graph(seed, nodes=40, edges=110):
+    rng = random.Random(seed)
+    graph = {i: [] for i in range(nodes + 3)}                     # the last three nodes stay isolated
+    for _ in range(edges):
+        a, b = rng.sample(range(nodes), 2)
+        length = rng.uniform(20, 400)
+        graph[a].append([b, length, {"grade_pct": rng.uniform(-15, 15), "landcover": rng.choice([None, "forest", "field"])}])
+        if rng.random() < 0.7:                                    # mostly two-way, sometimes one-way
+            graph[b].append([a, length, {"grade_pct": rng.uniform(-15, 15), "near_highway": rng.random() < 0.2}])
+    return graph, rng
+
+
+PREFS = {"prefer_forest": 2.0, "avoid_open_field": 1.5, "avoid_near_highway": 2.0, "gradient_threshold_pct": 8,
+         "avoid_steep_gradient": 2.0}
+
+
+def _original_cheapest_insertion_cost_km(graph, path, candidate_node, preferences):
+    from route_graph import weighted_shortest_path
+    if len(path) == 1:
+        _, there = weighted_shortest_path(graph, path[0], candidate_node, preferences)
+        return None if there is None else 2 * there / 1000.0
+    best = None
+    for a, b in zip(path, path[1:]):
+        _, cost_to = weighted_shortest_path(graph, a, candidate_node, preferences)
+        _, cost_from = weighted_shortest_path(graph, candidate_node, b, preferences)
+        _, direct = weighted_shortest_path(graph, a, b, preferences)
+        if cost_to is None or cost_from is None:
+            continue
+        direct = direct or 0.0
+        detour = (cost_to + cost_from - direct) / 1000.0
+        if best is None or detour < best:
+            best = detour
+    return best
+
+
+def _original_select(graph, path, mandatory_cost_km, candidates, preferences, max_distance_km):
+    remaining = float("inf") if max_distance_km is None else max_distance_km - mandatory_cost_km
+    scored, skipped = [], []
+    for candidate in candidates:
+        cost = _original_cheapest_insertion_cost_km(graph, path, candidate["node_id"], preferences)
+        if cost is None:
+            skipped.append(candidate["name"])
+        else:
+            scored.append((cost, _TIER_RANK.get(candidate.get("tier"), 99), candidate))
+    scored.sort(key=lambda item: (item[0], item[1]))
+    included = []
+    for cost, _rank, candidate in scored:
+        if cost <= remaining:
+            included.append(candidate)
+            remaining -= cost
+        else:
+            skipped.append(candidate["name"])
+    return included, skipped
+
+
+@pytest.mark.parametrize("seed", range(6))
+def test_select_optional_points_agrees_with_the_original_search_per_pair(seed):
+    graph, rng = _random_directed_graph(seed)
+    path_length = [1, 2, 3, 6, 6, 4][seed]
+    path = [rng.randrange(40) for _ in range(path_length)]
+    if seed == 5:
+        path = path + [path[0]]                                   # a loop: the start repeats
+    candidates = [{"name": f"c{i}", "node_id": rng.choice(list(range(40)) + [40, 41, 42]),
+                   "tier": rng.choice(["tag-backed", "web-sourced", None])} for i in range(12)]
+    candidates[0]["node_id"] = 41                                 # an isolated node: always unreachable
+    for budget in (None, 3.0, 8.0):
+        expected = _original_select(graph, path, 1.0, candidates, PREFS, budget)
+        assert "c0" in expected[1]
+        assert select_optional_points(graph, path, 1.0, candidates, PREFS, budget) == expected
+
+
+def test_shortest_costs_equals_weighted_shortest_path_for_every_target():
+    graph, rng = _random_directed_graph(11)
+    start = 3
+    everything = route_graph.shortest_costs(graph, start, PREFS)
+    assert everything[start] == 0.0
+    subset = set(rng.sample(range(43), 15)) | {start, 41}
+    costs = route_graph.shortest_costs(graph, start, PREFS, subset)
+    assert set(costs) == subset and costs[start] == 0.0 and costs[41] is None        # 41 is isolated
+    for target in subset:
+        _, expected = route_graph.weighted_shortest_path(graph, start, target, PREFS)
+        assert costs[target] == expected
+        assert everything.get(target) == expected
+
+
+def test_select_optional_points_ticks_once_per_search():
+    graph, rng = _random_directed_graph(2)
+
+    class Recorder:
+        def __init__(self):
+            self.ticks = []
+
+        def tick(self, done, total, key="tag_progress", **params):
+            self.ticks.append((done, total, key))
+
+    recorder = Recorder()
+    candidates = [{"name": f"c{i}", "node_id": n} for i, n in enumerate([5, 6, 7])]
+    select_optional_points(graph, [1, 2, 1], 1.0, candidates, PREFS, None, progress=recorder)
+    assert recorder.ticks == [(1, 5, "optional_run"), (2, 5, "optional_run"), (3, 5, "optional_run"),
+                              (4, 5, "optional_run"), (5, 5, "optional_run")]       # 2 distinct path nodes + 3 candidates
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-planning && python3 -m pytest tests/test_route_graph.py tests/test_waypoints.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-planning/scripts/route_graph.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/scripts/route_graph.py
+++ b/skills/osm-day-route-planning/scripts/route_graph.py
@@ -32,6 +32,7 @@
 import math
 
 from overpass_query import query_overpass, haversine
+from progress import NullProgress
 
 
 RESTRICTED_ACCESS = ("private", "no", "military")
@@ -42,7 +43,8 @@
 
 def fetch_area_data(lat: float, lon: float, radius_m: int = 2000,
                      routable_highway=None, hard_exclude_highway=None,
-                     exclude_highway_without_infra=None, mode: str | None = None) -> dict:
+                     exclude_highway_without_infra=None, mode: str | None = None,
+                     cache_dir=None, refresh: bool = False, progress=None) -> dict:
     """One combined Overpass query for everything build_graph/tag_edges/
     exclusion need: walkable ways, highways (for avoidance), water,
     forest, fields, plus access-restricted ways, military land, barrier
@@ -68,7 +70,11 @@
     bicycle=yes|designated (bike) or foot=yes|designated (walk) is not
     bucketed as restricted for THAT mode only — a bicycle-designated path
     through an access=no area is still closed to walkers. mode=None (an
-    old caller) gets no override at all: the strict default."""
+    old caller) gets no override at all: the strict default.
+
+    cache_dir (e.g. Path("routes/.cache")) keeps the Overpass answer for a day so that a re-plan or a revision of the
+    same area does not wait for the server again; refresh=True bypasses it. progress (optional) is told about a
+    cache hit and about retries (see overpass_query.query_overpass)."""
     routable_highway = tuple(routable_highway) if routable_highway else DEFAULT_ROUTABLE_HIGHWAY
     hard_exclude_highway = tuple(hard_exclude_highway or ())
     exclude_highway_without_infra = tuple(exclude_highway_without_infra or ())
@@ -125,7 +131,14 @@
     .barrierways out geom;
     .barriernodes out;
     """
-    result = query_overpass(ql)
+    options = {}
+    if cache_dir is not None:
+        options["cache_dir"] = cache_dir
+    if refresh:
+        options["refresh"] = True
+    if progress is not None:
+        options["progress"] = progress
+    result = query_overpass(ql, **options)
     elements = result.get("elements", [])
     walkable_set = set(walkable_highway_values)
     # Overpass doesn't tag which named set an element came from in this
@@ -453,36 +466,68 @@
         return False
 
 
+class _RingSet:
+    """Polygon rings with their bounding boxes: a point is tested with `point_in_ring` only against the rings whose
+    box contains it (a point outside a polygon's box is outside the polygon), which is what makes landcover
+    tagging of tens of thousands of edges against dozens of large forest polygons cheap."""
+
+    def __init__(self, rings):
+        self._items = [(ring, (min(p[0] for p in ring), max(p[0] for p in ring),
+                               min(p[1] for p in ring), max(p[1] for p in ring))) for ring in rings]
+
+    def contains(self, lat, lon):
+        for ring, (south, north, west, east) in self._items:
+            if south <= lat <= north and west <= lon <= east and point_in_ring(lat, lon, ring):
+                return True
+        return False
+
+
+TAG_PROGRESS_EVERY = 5000                    # directed edges between two progress ticks
+
+
 def tag_edges(graph, node_coords, highway_ways, water_ways, forest_ways, field_ways,
-              highway_buffer_m=50, water_buffer_m=30):
+              highway_buffer_m=50, water_buffer_m=30, progress=None):
     """Mutates graph in place: each edge [neighbor, length, tags] gets
-    tags = {'near_highway': bool, 'near_water': bool, 'landcover': 'forest'|'field'|None}."""
+    tags = {'near_highway': bool, 'near_water': bool, 'landcover': 'forest'|'field'|None}.
+    The tags depend only on the midpoint of the edge, so the two directed edges of one physical segment are tagged
+    from one computation. `progress` (optional) gets a tick every TAG_PROGRESS_EVERY directed edges."""
     highway_geoms = [w["geometry"] for w in highway_ways if w.get("geometry")]
     water_geoms = [w["geometry"] for w in water_ways if w.get("geometry")]
-    forest_rings = [[(p["lat"], p["lon"]) for p in w["geometry"]]
-                    for w in forest_ways if w.get("geometry") and len(w["geometry"]) >= 3]
-    field_rings = [[(p["lat"], p["lon"]) for p in w["geometry"]]
-                   for w in field_ways if w.get("geometry") and len(w["geometry"]) >= 3]
+    forests = _RingSet([[(p["lat"], p["lon"]) for p in w["geometry"]]
+                        for w in forest_ways if w.get("geometry") and len(w["geometry"]) >= 3])
+    fields = _RingSet([[(p["lat"], p["lon"]) for p in w["geometry"]]
+                       for w in field_ways if w.get("geometry") and len(w["geometry"]) >= 3])
 
     highway_grid = _VertexGrid(highway_geoms, highway_buffer_m) if highway_geoms else None
     water_grid = _VertexGrid(water_geoms, water_buffer_m) if water_geoms else None
 
+    def tags_at(mid_lat, mid_lon):
+        landcover = "forest" if forests.contains(mid_lat, mid_lon) else \
+            "field" if fields.contains(mid_lat, mid_lon) else None
+        return {"near_highway": highway_grid is not None and highway_grid.near(mid_lat, mid_lon),
+                "near_water": water_grid is not None and water_grid.near(mid_lat, mid_lon),
+                "landcover": landcover}
+
+    progress = progress or NullProgress()
+    total = sum(len(edges) for edges in graph.values())
+    done = 0
+    computed = {}
     for node_id, edges in graph.items():
         for edge in edges:
             neighbor_id = edge[0]
             lat1, lon1 = node_coords[node_id]
-            lat2, lon2 = node_coords.get(neighbor_id, (lat1, lon1))
-            mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2
-
-            near_highway = highway_grid is not None and highway_grid.near(mid_lat, mid_lon)
-            near_water = water_grid is not None and water_grid.near(mid_lat, mid_lon)
-            landcover = None
-            if any(point_in_ring(mid_lat, mid_lon, ring) for ring in forest_rings):
-                landcover = "forest"
-            elif any(point_in_ring(mid_lat, mid_lon, ring) for ring in field_rings):
-                landcover = "field"
-
-            edge[2].update({"near_highway": near_highway, "near_water": near_water, "landcover": landcover})
+            if neighbor_id in node_coords:
+                lat2, lon2 = node_coords[neighbor_id]
+                key = (node_id, neighbor_id) if node_id <= neighbor_id else (neighbor_id, node_id)
+                if key not in computed:
+                    computed[key] = tags_at((lat1 + lat2) / 2, (lon1 + lon2) / 2)
+                tags = computed[key]
+            else:                                                   # a neighbour without coordinates: the node itself
+                tags = tags_at(lat1, lon1)
+            edge[2].update(tags)
+            done += 1
+            if done % TAG_PROGRESS_EVERY == 0:
+                progress.tick(done, total, "tag_progress")
 
 
 def tag_grades(graph, node_coords, elevations):
@@ -576,16 +621,48 @@
     return list(reversed(path)), dist[end]
 
 
-def route_through_waypoints(graph, waypoint_ids, preferences):
+def shortest_costs(graph, start, preferences, targets=None):
+    """Preference-weighted cost (the same numbers weighted_shortest_path returns) from `start` to each of
+    `targets`: {target: cost, or None when unreachable}. The search stops as soon as every target is settled.
+    With targets=None the costs to every reachable node are returned. One call replaces one
+    weighted_shortest_path per target."""
+    wanted = None if targets is None else set(targets)
+    dist = {start: 0.0}
+    pq = [(0.0, start)]
+    visited = set()
+    remaining = None if wanted is None else set(wanted)
+    while pq:
+        d, node = heapq.heappop(pq)
+        if node in visited:
+            continue
+        visited.add(node)
+        if remaining is not None:
+            remaining.discard(node)
+            if not remaining:
+                break
+        for neighbor, length_m, tags in graph.get(node, []):
+            nd = d + _edge_cost(length_m, tags, preferences)
+            if nd < dist.get(neighbor, float("inf")):
+                dist[neighbor] = nd
+                heapq.heappush(pq, (nd, neighbor))
+    if wanted is None:
+        return dist
+    return {t: (dist[t] if t in visited else None) for t in wanted}
+
+
+def route_through_waypoints(graph, waypoint_ids, preferences, progress=None):
     """Concatenates weighted_shortest_path between consecutive waypoints
     in the given order. Caller decides waypoint order (nearest-neighbor +
-    2-opt for a handful of points; brute force below that)."""
+    2-opt for a handful of points; brute force below that). `progress` (optional) gets a route_leg tick per leg."""
     full_path = [waypoint_ids[0]]
     total_cost = 0.0
-    for a, b in zip(waypoint_ids, waypoint_ids[1:]):
+    legs = list(zip(waypoint_ids, waypoint_ids[1:]))
+    for done, (a, b) in enumerate(legs, start=1):
         segment, cost = weighted_shortest_path(graph, a, b, preferences)
         if segment is None:
             return None, None, f"no path between {a} and {b}"
         full_path.extend(segment[1:])
         total_cost += cost
+        if progress is not None:
+            progress.tick(done, len(legs), "route_leg")
     return full_path, total_cost, None
```

Modify `skills/osm-day-route-planning/scripts/waypoints.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/scripts/waypoints.py
+++ b/skills/osm-day-route-planning/scripts/waypoints.py
@@ -1,7 +1,8 @@
 """Waypoint-level checks that run BEFORE the graph is built (spec §3.4):
 a restricted-zone hit here must become an explicit message, never a
 silent 'no path found' surfaced later from the router."""
-from route_graph import point_in_ring, weighted_shortest_path
+from progress import NullProgress
+from route_graph import point_in_ring, shortest_costs
 
 
 class RestrictedWaypointError(Exception):
@@ -41,20 +42,20 @@
         )
 
 
-def _cheapest_insertion_cost_km(graph, path: list[int], candidate_node: int, preferences: dict) -> float:
-    """Cost (km) of visiting candidate_node via the cheapest detour between
-    any two consecutive nodes already in `path`. When `path` has a single
-    node (a bare loop with no other mandatory point yet), the only
-    'insertion' possible is a there-and-back detour off that one node."""
+def _cheapest_insertion_cost_km(path: list[int], candidate_node: int, costs_from: dict, costs_from_candidate: dict):
+    """Cost (km) of visiting candidate_node via the cheapest detour between any two consecutive nodes already in
+    `path`, or None when it cannot be reached. `costs_from[a][x]` is the cost a -> x (a on the path, x on the path
+    or the candidate) and `costs_from_candidate[b]` the cost candidate -> b. When `path` has a single node (a bare
+    loop with no other mandatory point yet) the only 'insertion' possible is a there-and-back detour."""
     if len(path) == 1:
-        _, there = weighted_shortest_path(graph, path[0], candidate_node, preferences)
+        there = costs_from[path[0]][candidate_node]
         return None if there is None else 2 * there / 1000.0
 
     best = None
     for a, b in zip(path, path[1:]):
-        _, cost_to = weighted_shortest_path(graph, a, candidate_node, preferences)
-        _, cost_from = weighted_shortest_path(graph, candidate_node, b, preferences)
-        _, direct = weighted_shortest_path(graph, a, b, preferences)
+        cost_to = costs_from[a][candidate_node]
+        cost_from = costs_from_candidate[b]
+        direct = costs_from[a][b]
         if cost_to is None or cost_from is None:
             continue
         direct = direct or 0.0
@@ -66,19 +67,39 @@
 
 def select_optional_points(graph, mandatory_path: list[int], mandatory_cost_km: float,
                             candidates: list[dict], preferences: dict,
-                            max_distance_km: float | None):
+                            max_distance_km: float | None, progress=None):
     """Greedy cheapest-insertion selection under a distance budget (spec
     §3.5 step 3). Candidates unreachable from the mandatory path are
-    treated as skipped, same as ones that don't fit the budget."""
+    treated as skipped, same as ones that don't fit the budget.
+    One route search runs from every distinct node of the path and one from every candidate (the graph is directed,
+    so candidate -> path costs need their own search): P + C searches, not three per pair per candidate.
+    `progress` (optional) gets a tick per search."""
     if max_distance_km is None:
         remaining_budget = float("inf")
     else:
         remaining_budget = max_distance_km - mandatory_cost_km
 
+    progress = progress or NullProgress()
+    sources = list(dict.fromkeys(mandatory_path))
+    candidate_nodes = {c["node_id"] for c in candidates}
+    total_runs = len(sources) + len(candidate_nodes)
+    done = 0
+    costs_from = {}
+    for node in sources:
+        costs_from[node] = shortest_costs(graph, node, preferences, set(mandatory_path) | candidate_nodes)
+        done += 1
+        progress.tick(done, total_runs, "optional_run")
+    costs_from_candidate = {}
+    for node in candidate_nodes:
+        costs_from_candidate[node] = shortest_costs(graph, node, preferences, set(mandatory_path))
+        done += 1
+        progress.tick(done, total_runs, "optional_run")
+
     scored = []
     skipped = []
     for candidate in candidates:
-        cost_km = _cheapest_insertion_cost_km(graph, mandatory_path, candidate["node_id"], preferences)
+        cost_km = _cheapest_insertion_cost_km(mandatory_path, candidate["node_id"], costs_from,
+                                              costs_from_candidate[candidate["node_id"]])
         if cost_km is None:
             skipped.append(candidate["name"])
         else:
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Graph: landcover once per segment, one route search per source, progress hooks

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 4: Overpass answer cache and progress notes

`query_overpass(ql, ..., cache_dir=None, max_age_s=86400, refresh=False, progress=None)`: with `cache_dir` the answer is kept in `<cache_dir>/overpass/<sha256 of the query>.json` and a fresh one is returned without a request (the note says its age in hours); `refresh=True` skips the read; writes are atomic, a malformed or unwritable cache is ignored, entries older than 7 days are pruned on write. Retries, endpoint switches and failed attempts are reported through `progress`. No network in the tests.

**Files:**
- Modify: `skills/osm-day-route-planning/tests/test_overpass_query.py`
- Modify: `skills/osm-day-route-planning/scripts/overpass_query.py`

- [ ] **Step 1: Add the tests** (16 tests in the file(s) below)

Modify `skills/osm-day-route-planning/tests/test_overpass_query.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/tests/test_overpass_query.py
+++ b/skills/osm-day-route-planning/tests/test_overpass_query.py
@@ -33,3 +33,150 @@
 
 def test_count_curated_routes_zero_when_count_element_missing():
     assert count_curated_routes({"elements": [{"type": "way", "id": 1}]}) == 0
+
+
+# ---- the on-disk answer cache and the progress notes ---------------------------------------------------------------------
+
+import json
+import os
+import time
+
+import pytest
+
+import overpass_query
+from overpass_query import query_overpass
+
+
+class _Response:
+    status = 200
+
+    def __init__(self, payload):
+        self._raw = json.dumps(payload).encode()
+
+    def read(self):
+        return self._raw
+
+    def __enter__(self):
+        return self
+
+    def __exit__(self, *exc):
+        return False
+
+
+class _Server:
+    """Stands in for urllib.request.urlopen: answers come from a list of payloads or exceptions."""
+
+    def __init__(self, *outcomes):
+        self.outcomes = list(outcomes)
+        self.calls = 0
+
+    def __call__(self, request, timeout=None):
+        self.calls += 1
+        outcome = self.outcomes.pop(0)
+        if isinstance(outcome, Exception):
+            raise outcome
+        return _Response(outcome)
+
+
+class _Recorder:
+    def __init__(self):
+        self.events = []
+
+    def note(self, key, **params):
+        self.events.append(("note", key, params))
+
+    def warn(self, key, **params):
+        self.events.append(("warn", key, params))
+
+
+@pytest.fixture
+def server(monkeypatch):
+    monkeypatch.setattr(overpass_query.time, "sleep", lambda s: None)
+
+    def install(*outcomes):
+        fake = _Server(*outcomes)
+        monkeypatch.setattr(overpass_query.urllib.request, "urlopen", fake)
+        return fake
+    return install
+
+
+def test_without_cache_dir_every_call_asks_the_server(server):
+    fake = server({"elements": [1]}, {"elements": [2]})
+    assert query_overpass("q") == {"elements": [1]} and query_overpass("q") == {"elements": [2]}
+    assert fake.calls == 2
+
+
+def test_a_fresh_cached_answer_is_returned_without_a_request_and_reported(server, tmp_path):
+    fake = server({"elements": [1]})
+    recorder = _Recorder()
+    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [1]}
+    assert query_overpass("q", cache_dir=tmp_path, progress=recorder) == {"elements": [1]}
+    assert fake.calls == 1 and recorder.events == [("note", "overpass_cache_hit", {"age": 0})]
+
+
+def test_the_key_is_the_query_text(server, tmp_path):
+    fake = server({"elements": [1]}, {"elements": [2]})
+    assert query_overpass("around:1500,55.0,37.0", cache_dir=tmp_path) == {"elements": [1]}
+    assert query_overpass("around:2000,55.0,37.0", cache_dir=tmp_path) == {"elements": [2]}
+    assert fake.calls == 2 and len(list((tmp_path / "overpass").glob("*.json"))) == 2
+
+
+def test_an_expired_entry_is_fetched_again_and_the_age_is_reported_in_hours(server, tmp_path):
+    fake = server({"elements": [1]}, {"elements": [2]})
+    query_overpass("q", cache_dir=tmp_path)
+    entry = next((tmp_path / "overpass").glob("*.json"))
+    three_hours_ago = time.time() - 3 * 3600 - 60
+    os.utime(entry, (three_hours_ago, three_hours_ago))
+    recorder = _Recorder()
+    assert query_overpass("q", cache_dir=tmp_path, progress=recorder) == {"elements": [1]}         # 3 h old: still fresh
+    assert recorder.events == [("note", "overpass_cache_hit", {"age": 3})]
+    two_days_ago = time.time() - 48 * 3600
+    os.utime(entry, (two_days_ago, two_days_ago))
+    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2
+
+
+def test_refresh_skips_the_read_but_updates_the_entry(server, tmp_path):
+    fake = server({"elements": [1]}, {"elements": [2]})
+    query_overpass("q", cache_dir=tmp_path)
+    assert query_overpass("q", cache_dir=tmp_path, refresh=True) == {"elements": [2]}
+    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2
+
+
+def test_a_malformed_entry_is_ignored_not_an_error(server, tmp_path):
+    fake = server({"elements": [1]}, {"elements": [2]})
+    query_overpass("q", cache_dir=tmp_path)
+    next((tmp_path / "overpass").glob("*.json")).write_text("{broken", encoding="utf-8")
+    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2
+
+
+def test_old_entries_are_pruned_when_a_new_one_is_written(server, tmp_path):
+    server({"elements": [1]}, {"elements": [2]})
+    query_overpass("old", cache_dir=tmp_path)
+    old = next((tmp_path / "overpass").glob("*.json"))
+    ten_days_ago = time.time() - 10 * 24 * 3600
+    os.utime(old, (ten_days_ago, ten_days_ago))
+    query_overpass("new", cache_dir=tmp_path)
+    assert not old.exists() and len(list((tmp_path / "overpass").glob("*.json"))) == 1
+    assert not list((tmp_path / "overpass").glob("*.tmp"))
+
+
+def test_an_unwritable_cache_never_fails_the_query(server, tmp_path):
+    server({"elements": [1]})
+    blocker = tmp_path / "blocker"
+    blocker.write_text("a file, not a directory", encoding="utf-8")
+    assert query_overpass("q", cache_dir=blocker) == {"elements": [1]}
+
+
+def test_failures_and_retries_are_reported(server):
+    server(OSError("HTTP Error 504: Gateway Timeout"), {"elements": [3]})
+    recorder = _Recorder()
+    assert query_overpass("q", progress=recorder) == {"elements": [3]}
+    assert recorder.events == [
+        ("warn", "overpass_failed", {"endpoint": "overpass-api.de", "reason": "HTTP Error 504: Gateway Timeout"}),
+        ("note", "overpass_attempt", {"endpoint": "overpass-api.de", "n": 2, "m": 2})]
+
+
+def test_all_endpoints_failing_still_raises(server):
+    server(*[OSError("down")] * 4)
+    with pytest.raises(RuntimeError, match="failed on all endpoints"):
+        query_overpass("q")
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-planning && python3 -m pytest tests/test_overpass_query.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-planning/scripts/overpass_query.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/scripts/overpass_query.py
+++ b/skills/osm-day-route-planning/scripts/overpass_query.py
@@ -9,12 +9,15 @@
 Or import:
     from overpass_query import query_overpass, route_length_m
 """
+import hashlib
 import json
 import math
+import os
 import sys
 import time
 import urllib.request
 import urllib.parse
+from pathlib import Path
 
 ENDPOINTS = [
     "https://overpass-api.de/api/interpreter",
@@ -30,13 +33,66 @@
 }
 
 
-def query_overpass(ql: str, timeout: int = 90, retries: int = 2) -> dict:
+CACHE_MAX_AGE_S = 24 * 3600          # OSM changes slowly, but a closure matters: a cached answer is at most a day old
+CACHE_PRUNE_AGE_S = 7 * 24 * 3600   # older entries are deleted whenever a new one is written
+
+
+def _cache_file(cache_dir, ql: str) -> Path:
+    """The query text holds the centre, the radius and the tag patterns, so its hash is the whole key."""
+    return Path(cache_dir) / "overpass" / (hashlib.sha256(ql.encode("utf-8")).hexdigest() + ".json")
+
+
+def _read_cache(path: Path, max_age_s: float):
+    """(answer, age_seconds) of a fresh, readable entry; None for a missing, expired or malformed one."""
+    try:
+        age = time.time() - path.stat().st_mtime
+        if age > max_age_s:
+            return None
+        return json.loads(path.read_text(encoding="utf-8")), age
+    except (OSError, ValueError):
+        return None
+
+
+def _write_cache(path: Path, result: dict) -> None:
+    """Atomic (temporary file, then rename); a failure to cache never fails the query."""
+    try:
+        path.parent.mkdir(parents=True, exist_ok=True)
+        temporary = path.with_suffix(".tmp")
+        temporary.write_text(json.dumps(result), encoding="utf-8")
+        os.replace(temporary, path)
+        cutoff = time.time() - CACHE_PRUNE_AGE_S
+        for old in path.parent.glob("*.json"):
+            if old != path and old.stat().st_mtime < cutoff:
+                old.unlink()
+    except OSError:
+        pass
+
+
+def _host(endpoint: str) -> str:
+    return urllib.parse.urlparse(endpoint).netloc or endpoint
+
+
+def query_overpass(ql: str, timeout: int = 90, retries: int = 2, cache_dir=None,
+                   max_age_s: float = CACHE_MAX_AGE_S, refresh: bool = False, progress=None) -> dict:
     """Run an Overpass QL query, trying each endpoint, retrying on
-    5xx/timeout-body responses. Raises RuntimeError if all attempts fail."""
+    5xx/timeout-body responses. Raises RuntimeError if all attempts fail.
+
+    With `cache_dir` the answer is kept in <cache_dir>/overpass/ and a fresh one (younger than `max_age_s`) is
+    returned without a request; `refresh=True` skips the read. `progress` (optional: see progress.py) is told about
+    a cache hit, every retry or endpoint switch and every failed attempt."""
+    cache_path = _cache_file(cache_dir, ql) if cache_dir is not None else None
+    if cache_path is not None and not refresh:
+        cached = _read_cache(cache_path, max_age_s)
+        if cached is not None:
+            if progress is not None:
+                progress.note("overpass_cache_hit", age=int(cached[1] // 3600))
+            return cached[0]
     body = urllib.parse.urlencode({"data": ql}).encode()
     last_error = None
-    for endpoint in ENDPOINTS:
+    for endpoint_index, endpoint in enumerate(ENDPOINTS):
         for attempt in range(retries):
+            if progress is not None and (endpoint_index, attempt) != (0, 0):
+                progress.note("overpass_attempt", endpoint=_host(endpoint), n=attempt + 1, m=retries)
             try:
                 req = urllib.request.Request(endpoint, data=body, headers=HEADERS)
                 with urllib.request.urlopen(req, timeout=timeout) as resp:
@@ -49,9 +105,14 @@
                         last_error = f"{endpoint}: server-side timeout/error body"
                         time.sleep(2)
                         continue
-                    return json.loads(text)
+                    result = json.loads(text)
+                    if cache_path is not None:
+                        _write_cache(cache_path, result)
+                    return result
             except Exception as e:
                 last_error = f"{endpoint}: {e}"
+                if progress is not None:
+                    progress.warn("overpass_failed", endpoint=_host(endpoint), reason=" ".join(str(e).split())[:80])
                 time.sleep(2)
     raise RuntimeError(f"Overpass query failed on all endpoints/attempts: {last_error}")
 
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Overpass: on-disk answer cache, progress notes

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 5: Elevation service progress

`ElevationService.get_elevations(locations, progress=None)` ticks once per provider request (the total is the first provider's batch count and grows when a failover needs more) and remembers `last_request` (`points` and `cached` counts) for a summary line. The cache and the sampling are unchanged.

**Files:**
- Modify: `skills/osm-day-route-planning/tests/test_elevation_service.py`
- Modify: `skills/osm-day-route-planning/scripts/elevation/__init__.py`

- [ ] **Step 1: Add the tests** (13 tests in the file(s) below)

Modify `skills/osm-day-route-planning/tests/test_elevation_service.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/tests/test_elevation_service.py
+++ b/skills/osm-day-route-planning/tests/test_elevation_service.py
@@ -176,3 +176,37 @@
     assert result == [None] * 5
     mock_write.assert_not_called()
     assert not (tmp_path / "elevation.json").exists()
+
+
+class _Recorder:
+    def __init__(self):
+        self.ticks = []
+
+    def tick(self, done, total, key="tag_progress", **params):
+        self.ticks.append((done, total, key))
+
+
+def test_get_elevations_ticks_once_per_batch_and_remembers_the_cache_share(tmp_path):
+    points = [(55.0 + i * 0.001, 37.0) for i in range(5)]
+    provider = _FakeProvider("p1", max_batch=2, responses={p: 100.0 + i for i, p in enumerate(points)})
+    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")
+    recorder = _Recorder()
+
+    service.get_elevations(points[:1], progress=recorder)                      # one point goes to the cache
+    recorder = _Recorder()
+    service.get_elevations(points, progress=recorder)
+
+    assert recorder.ticks == [(1, 2, "elevation_batch"), (2, 2, "elevation_batch")]     # 4 pending points, 2 per batch
+    assert service.last_request == {"points": 5, "cached": 1}
+
+
+def test_the_tick_total_grows_when_a_failover_needs_more_requests(tmp_path):
+    points = [(55.0 + i * 0.001, 37.0) for i in range(4)]
+    failing = _FakeProvider("p1", max_batch=4, fail=True)
+    working = _FakeProvider("p2", max_batch=2, responses={p: 1.0 for p in points})
+    service = ElevationService([failing, working], cache_path=tmp_path / "elevation.json")
+    recorder = _Recorder()
+
+    service.get_elevations(points, progress=recorder)
+
+    assert recorder.ticks == [(1, 1, "elevation_batch"), (2, 2, "elevation_batch"), (3, 3, "elevation_batch")]
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-planning && python3 -m pytest tests/test_elevation_service.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-planning/scripts/elevation/__init__.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-planning/scripts/elevation/__init__.py
+++ b/skills/osm-day-route-planning/scripts/elevation/__init__.py
@@ -16,8 +16,12 @@
         self._dataset = dataset
         self._cache = load_cache(self._cache_path)
         self._last_call_time: dict[str, float] = {}
+        self.last_request = {"points": 0, "cached": 0}       # of the latest get_elevations call, for a summary line
 
-    def get_elevations(self, locations: list[tuple[float, float]]) -> list[float | None]:
+    def get_elevations(self, locations: list[tuple[float, float]], progress=None) -> list[float | None]:
+        """Elevation per location (None where no provider knew it). `progress` (optional, see progress.py) gets a
+        tick per provider request: elevation_batch done/total (total counts the first provider's batches and grows
+        if a failover needs more)."""
         results: list[float | None] = [None] * len(locations)
         pending_indices = []
         for i, (lat, lon) in enumerate(locations):
@@ -26,6 +30,9 @@
                 results[i] = self._cache[key]["elevation"]
             else:
                 pending_indices.append(i)
+        self.last_request = {"points": len(locations), "cached": len(locations) - len(pending_indices)}
+        batches_done = 0
+        batches_total = -(-len(pending_indices) // self._providers[0].max_batch) if self._providers else 0
 
         for provider in self._providers:
             if not pending_indices:
@@ -34,6 +41,10 @@
             for batch_indices in self._chunk(pending_indices, provider.max_batch):
                 batch_locations = [locations[i] for i in batch_indices]
                 self._respect_rate_limit(provider)
+                batches_done += 1
+                batches_total = max(batches_total, batches_done)
+                if progress is not None:
+                    progress.tick(batches_done, batches_total, "elevation_batch")
                 try:
                     batch_results = provider.fetch(batch_locations)
                 except Exception:
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Elevation service: progress ticks and last_request

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 6: Planner documentation

The planner `SKILL.md`: the pipeline example creates a `Progress` in the user's language, wraps the steps, passes `cache_dir` and `progress`, uses `service.last_request`; a paragraph on the progress output and on running long scripts in the background with a followed log; the `elevation_gain_m` / `elevation_loss_m` row states the 0.1 m precision.

**Files:**
- Modify: `skills/osm-day-route-planning/SKILL.md`

- [ ] **Step 1: Write the implementation**

Modify `skills/osm-day-route-planning/SKILL.md` — apply this patch (`patch -p1`):

````diff
--- a/skills/osm-day-route-planning/SKILL.md
+++ b/skills/osm-day-route-planning/SKILL.md
@@ -383,30 +383,43 @@
 from elevation.providers.open_elevation import OpenElevationProvider
 from duration import estimate_duration_hours, duration_warning
 from route_output import build_geojson
+from progress import Progress
+
+# Console progress, in the USER'S language (en ru es fr de pt it; English for any other): one line per step, plain
+# lines without a terminal, sub-progress only for slow steps. Pass `progress` to the functions below that accept it.
+progress = Progress(total_steps=5, lang=user_lang)        # user_lang: the language of the conversation / notes.md
 
 preset = load_preset(mode, style)                 # e.g. load_preset("bike", "leisure")
 weights = build_weights(preset, preference_overrides, max_distance_km, max_duration_hours)
 
-data = fetch_area_data(
-    lat, lon, radius_m=1500,
-    routable_highway=weights["routable_highway"],
-    hard_exclude_highway=weights["hard_exclude_tags"].get("highway", []),
-    exclude_highway_without_infra=weights["exclude_highway_without_infra"],
-    mode=weights["mode"],  # scopes the designated-path override to this mode
-)
+with progress.step("overpass"):
+    data = fetch_area_data(
+        lat, lon, radius_m=1500,
+        routable_highway=weights["routable_highway"],
+        hard_exclude_highway=weights["hard_exclude_tags"].get("highway", []),
+        exclude_highway_without_infra=weights["exclude_highway_without_infra"],
+        mode=weights["mode"],  # scopes the designated-path override to this mode
+        cache_dir=Path("routes/.cache"),  # the answer is kept for 24 h: a revision does not wait for Overpass again;
+        progress=progress,                # refresh=True forces a new query (say so if the user doubts the data)
+    )
+    progress.detail("overpass_done", walkable=len(data["walkable"]), restricted=len(data["restricted"]))
 restricted = build_restricted_polygons(data["restricted"], data["barrier_ways"])
 walkable = filter_excluded_ways(
     data["walkable"], restricted,
     hard_exclude_tags=weights["hard_exclude_tags"],
     exclude_highway_without_infra=weights["exclude_highway_without_infra"],
 )
-graph, node_coords = build_graph(
-    walkable, data["barrier_nodes"],
-    blocking_barrier_tags=weights["blocking_barrier_tags"],
-    respect_oneway=(mode == "bike"),
-)
-tag_edges(graph, node_coords, data["highways"], data["water"], data["forest"], data["fields"],
-          highway_buffer_m=weights["buffers_m"]["highway"], water_buffer_m=weights["buffers_m"]["water"])
+with progress.step("graph"):
+    graph, node_coords = build_graph(
+        walkable, data["barrier_nodes"],
+        blocking_barrier_tags=weights["blocking_barrier_tags"],
+        respect_oneway=(mode == "bike"),
+    )
+    progress.detail("graph_done", nodes=len(graph), edges=sum(len(e) for e in graph.values()))
+with progress.step("tag_edges"):
+    tag_edges(graph, node_coords, data["highways"], data["water"], data["forest"], data["fields"],
+              highway_buffer_m=weights["buffers_m"]["highway"], water_buffer_m=weights["buffers_m"]["water"],
+              progress=progress)
 
 # --- elevation wiring: batch ONCE across every way, never once per way ---
 
@@ -429,7 +442,7 @@
         way_samples.append((way, coords, samples))
         all_points.extend((lat, lon) for lat, lon, _ in samples)
 
-    all_elevations = service.get_elevations(all_points)
+    all_elevations = service.get_elevations(all_points, progress=progress)
 
     node_elevations: dict[int, float] = {}
     unresolved = 0
@@ -463,13 +476,25 @@
               f"gradient penalty", file=sys.stderr)
     return node_elevations
 
-elevations = compute_node_elevations(walkable, service)
+with progress.step("elevation"):
+    elevations = compute_node_elevations(walkable, service)        # ticks once per provider request
+    progress.detail("elevation_done", **service.last_request)
 tag_grades(graph, node_coords, elevations)          # mutates graph in place: grade_pct per directed edge
 
 preferences = {**weights["preferences"], "gradient_threshold_pct": weights["gradient_threshold_pct"]}
-path, cost = weighted_shortest_path(graph, start_node_id, end_node_id, preferences)
+with progress.step("routing"):
+    path, cost = weighted_shortest_path(graph, start_node_id, end_node_id, preferences)
 ```
 
+**Progress output.** Every long step reports to the user, in the user's language (`Progress(lang=...)`: the
+language of the conversation; the wording lives in `progress.py`'s catalogue, never pass free text). Functions that
+accept `progress=` are `fetch_area_data`, `query_overpass`, `tag_edges`, `ElevationService.get_elevations`,
+`select_optional_points` (key `optional`) and `route_through_waypoints` (key `routing`). Run the planning script so that its
+output reaches the user while it works: a script whose step may take more than 30 s (Overpass, the first elevation
+fetch of an area) is started in the background with its output written to a log that is then followed. When
+Overpass answered from `routes/.cache` (its line says how old the answer is), a user who suspects stale data gets
+`refresh=True`.
+
 **Do not paste an elevation-wiring version that calls `get_elevations` once
 per way** — with a real fetch (radius 1500m+) that's easily 1000+ separate
 rate-limited HTTP calls (Open-Topo-Data allows 1 req/s and 1000/day on its
@@ -620,7 +645,7 @@
 | `mode` | `"walk"` or `"bike"` |
 | `style` | `"leisure"`/`"sport"` for bike, `null`/omitted for walk |
 | `distance_km` | Physical distance — see **Budget & Duration Wiring**, not the router's weighted cost |
-| `elevation_gain_m`, `elevation_loss_m` | Summed positive/negative deltas along the solved path |
+| `elevation_gain_m`, `elevation_loss_m` | Summed positive/negative deltas along the solved path, to 0.1 m (`build_geojson` also rounds every vertex and point elevation to 0.1 m — the data is ~30 m resolution, more decimals are noise; an unknown vertex elevation is still `0.0`) |
 | `duration_estimate_hours` | From `duration.estimate_duration_hours` |
 | `duration_warning` | String from `duration.duration_warning`, or `null` |
 | `curated_routes_count` | From `overpass_query.count_curated_routes` |
````

- [ ] **Step 2: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 3: Commit**

```bash
git add skills README.md
git commit -m "Planner docs: progress output, Overpass cache, elevation precision

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 7: Day plan: one progress line per plugin

`run_plugins(ctx, plugins, progress=None)` wraps each plugin in a step named in the user's language (`pl_<plugin_id>` strings, all seven languages); a raising plugin becomes a failed line and the plan is still built. `build_day_plan.main(..., progress=None)`; the command line passes `AUTO_PROGRESS` (a `Progress` in the `--lang` language on stderr) unless `--quiet`. Library callers and tests get no output. Docs: the day-plan `SKILL.md` and the README.

**Files:**
- Modify: `skills/osm-day-route-day-plan/tests/test_cli.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py`
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/service.py`
- Modify: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`
- Modify: `skills/osm-day-route-day-plan/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: Add the tests** (35 tests in the file(s) below)

Modify `skills/osm-day-route-day-plan/tests/test_cli.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/tests/test_cli.py
+++ b/skills/osm-day-route-day-plan/tests/test_cli.py
@@ -428,3 +428,53 @@
     with pytest.raises(ValueError, match="does not use --last-departure"):
         record_fact.record(route_dir, "all", "trail_conditions", "x", ["https://example.org/x"], last_departure="21:00")
 
+
+
+# ---- progress lines ------------------------------------------------------------------------------------------------------
+
+def test_the_cli_prints_one_progress_line_per_plugin_in_the_users_language(make_route, weather_response, fixed_now, capsys):
+    route_dir = make_route()
+    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=lambda url: weather_response(),
+                        http_text=_text, now=fixed_now, progress=build_day_plan.AUTO_PROGRESS)
+    lines = capsys.readouterr().err.splitlines()
+    starts = [l for l in lines if l.startswith("[")]
+    total = len(build_day_plan.default_plugins())
+    assert len(starts) == total and starts[0] == f"[1/{total}] Погода …"
+    assert any(l.startswith("[") and "Световой день" in l for l in lines)
+    assert sum(1 for l in lines if l.lstrip().startswith("✓")) >= total - 2
+    assert not any(word in "\n".join(lines) for word in ("Weather", "Daylight", "Mobile coverage"))
+
+
+def test_quiet_and_the_default_print_no_progress(make_route, weather_response, fixed_now, capsys):
+    route_dir = make_route()
+    http = lambda url: weather_response()  # noqa: E731
+    build_day_plan.main([str(route_dir), "2026-06-21", "--quiet"], http=http, http_text=_text, now=fixed_now,
+                        progress=build_day_plan.AUTO_PROGRESS)
+    assert "[1/" not in capsys.readouterr().err
+    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now)
+    assert "[1/" not in capsys.readouterr().err
+
+
+def test_a_failing_plugin_is_a_failed_progress_line_and_the_plan_still_builds(make_route, weather_response, fixed_now,
+                                                                                capsys):
+    from day_plan.base import SectionPlugin
+
+    class Broken(SectionPlugin):
+        plugin_id, section_id = "fire", "hazards"
+
+        def run(self, ctx, shared):
+            raise RuntimeError("HTTP 503")
+
+    route_dir = make_route()
+    code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "es"], http=lambda url: weather_response(),
+                               http_text=_text, now=fixed_now, plugins=[Broken()],
+                               progress=build_day_plan.AUTO_PROGRESS)
+    err = capsys.readouterr().err
+    assert code == 0 and "[1/1] Peligro de incendio …" in err and "✗" in err and "RuntimeError: HTTP 503" in err
+
+
+def test_every_default_plugin_has_a_name_in_every_language():
+    from day_plan.i18n import LANGS, STRINGS
+    for plugin in build_day_plan.default_plugins():
+        for lang in LANGS:
+            assert f"pl_{plugin.plugin_id}" in STRINGS[lang], (plugin.plugin_id, lang)
```

- [ ] **Step 2: Run them and see them fail** — `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_cli.py -q` (import errors or assertion failures: the code does not exist yet).

- [ ] **Step 3: Write the implementation**

Modify `skills/osm-day-route-day-plan/scripts/day_plan/i18n.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/i18n.py
@@ -536,6 +536,125 @@
 }
 
 
+# Names of the plugins in the progress lines (one per plugin, all seven languages; the hz_* titles exist in en/ru only).
+PLUGIN_NAMES = {
+    "en": {
+        "pl_weather": "Weather",
+        "pl_light": "Daylight",
+        "pl_osm_features": "Map features (OSM)",
+        "pl_radiation": "Radiation",
+        "pl_snow_history": "Snow history",
+        "pl_trail_passability": "Trail and road passability",
+        "pl_transit": "Getting there",
+        "pl_poi_hours": "Opening hours",
+        "pl_mountain": "Mountain hazards",
+        "pl_fire": "Fire danger",
+        "pl_bio_hazards": "Ticks and biting insects",
+        "pl_air": "Air: pollen and pollution",
+        "pl_people_hazards": "People and access",
+        "pl_cell_coverage": "Mobile coverage",
+    },
+    "ru": {
+        "pl_weather": "Погода",
+        "pl_light": "Световой день",
+        "pl_osm_features": "Объекты на карте (OSM)",
+        "pl_radiation": "Радиация",
+        "pl_snow_history": "История снега",
+        "pl_trail_passability": "Проходимость троп и дорог",
+        "pl_transit": "Как добраться",
+        "pl_poi_hours": "Часы работы",
+        "pl_mountain": "Горные опасности",
+        "pl_fire": "Пожарная опасность",
+        "pl_bio_hazards": "Клещи и насекомые",
+        "pl_air": "Воздух: пыльца и загрязнение",
+        "pl_people_hazards": "Люди и доступ",
+        "pl_cell_coverage": "Мобильная связь",
+    },
+    "es": {
+        "pl_weather": "Tiempo",
+        "pl_light": "Luz diurna",
+        "pl_osm_features": "Elementos del mapa (OSM)",
+        "pl_radiation": "Radiación",
+        "pl_snow_history": "Historial de nieve",
+        "pl_trail_passability": "Transitabilidad de caminos",
+        "pl_transit": "Cómo llegar",
+        "pl_poi_hours": "Horarios",
+        "pl_mountain": "Peligros de montaña",
+        "pl_fire": "Peligro de incendio",
+        "pl_bio_hazards": "Garrapatas e insectos",
+        "pl_air": "Aire: polen y contaminación",
+        "pl_people_hazards": "Personas y acceso",
+        "pl_cell_coverage": "Cobertura móvil",
+    },
+    "fr": {
+        "pl_weather": "Météo",
+        "pl_light": "Lumière du jour",
+        "pl_osm_features": "Éléments de la carte (OSM)",
+        "pl_radiation": "Radiation",
+        "pl_snow_history": "Historique de la neige",
+        "pl_trail_passability": "Praticabilité des chemins",
+        "pl_transit": "Comment s'y rendre",
+        "pl_poi_hours": "Horaires d'ouverture",
+        "pl_mountain": "Dangers en montagne",
+        "pl_fire": "Risque d'incendie",
+        "pl_bio_hazards": "Tiques et insectes",
+        "pl_air": "Air : pollen et pollution",
+        "pl_people_hazards": "Personnes et accès",
+        "pl_cell_coverage": "Couverture mobile",
+    },
+    "de": {
+        "pl_weather": "Wetter",
+        "pl_light": "Tageslicht",
+        "pl_osm_features": "Kartenobjekte (OSM)",
+        "pl_radiation": "Strahlung",
+        "pl_snow_history": "Schneeverlauf",
+        "pl_trail_passability": "Begehbarkeit der Wege",
+        "pl_transit": "Anreise",
+        "pl_poi_hours": "Öffnungszeiten",
+        "pl_mountain": "Berggefahren",
+        "pl_fire": "Brandgefahr",
+        "pl_bio_hazards": "Zecken und Insekten",
+        "pl_air": "Luft: Pollen und Schadstoffe",
+        "pl_people_hazards": "Menschen und Zugang",
+        "pl_cell_coverage": "Mobilfunkabdeckung",
+    },
+    "pt": {
+        "pl_weather": "Meteorologia",
+        "pl_light": "Luz do dia",
+        "pl_osm_features": "Elementos do mapa (OSM)",
+        "pl_radiation": "Radiação",
+        "pl_snow_history": "Histórico de neve",
+        "pl_trail_passability": "Transitabilidade dos caminhos",
+        "pl_transit": "Como chegar",
+        "pl_poi_hours": "Horários",
+        "pl_mountain": "Perigos de montanha",
+        "pl_fire": "Perigo de incêndio",
+        "pl_bio_hazards": "Carraças e insetos",
+        "pl_air": "Ar: pólen e poluição",
+        "pl_people_hazards": "Pessoas e acesso",
+        "pl_cell_coverage": "Cobertura móvel",
+    },
+    "it": {
+        "pl_weather": "Meteo",
+        "pl_light": "Luce del giorno",
+        "pl_osm_features": "Elementi della mappa (OSM)",
+        "pl_radiation": "Radiazione",
+        "pl_snow_history": "Storico della neve",
+        "pl_trail_passability": "Percorribilità dei percorsi",
+        "pl_transit": "Come arrivare",
+        "pl_poi_hours": "Orari di apertura",
+        "pl_mountain": "Pericoli di montagna",
+        "pl_fire": "Pericolo di incendio",
+        "pl_bio_hazards": "Zecche e insetti",
+        "pl_air": "Aria: polline e inquinamento",
+        "pl_people_hazards": "Persone e accesso",
+        "pl_cell_coverage": "Copertura mobile",
+    },
+}
+for _lang, _names in PLUGIN_NAMES.items():
+    STRINGS[_lang].update(_names)
+
+
 def tr(key: str, lang: str, **fmt):
     """String for `key` in `lang`, English fallback for any missing key or
     unknown language. Formats with **fmt when given (lists are returned
```

Modify `skills/osm-day-route-day-plan/scripts/day_plan/service.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/day_plan/service.py
+++ b/skills/osm-day-route-day-plan/scripts/day_plan/service.py
@@ -5,7 +5,8 @@
 from dataclasses import dataclass
 
 from .base import SECTION_ORDER, Section
-from .i18n import activity_label, tr
+from .i18n import STRINGS, activity_label, tr
+from .progress import NullProgress
 from .summary import build_summary_section
 
 
@@ -53,20 +54,30 @@
                              f"(known: {', '.join(SECTION_ORDER)})")
 
 
-def run_plugins(ctx, plugins: list):
-    """Returns (sections_in_registration_order, shared, failures)."""
+def _plugin_name(plugin, lang: str) -> str:
+    """The plugin's name in the user's language for a progress line (the id itself for an unknown plugin)."""
+    key = f"pl_{plugin.plugin_id}"
+    return tr(key, lang) if key in STRINGS["en"] else plugin.plugin_id
+
+
+def run_plugins(ctx, plugins: list, progress=None):
+    """Returns (sections_in_registration_order, shared, failures). `progress` (optional, see progress.py) gets one
+    step per plugin: its name in the user's language, then how long it took or why it failed."""
     _validate_registration(plugins)
+    progress = progress or NullProgress()
     shared, failures, by_id = {}, [], {}
     for plugin in _ordered(plugins):
         deps = {d: shared[d] for d in plugin.depends_on if d in shared}
-        try:
-            section = plugin.run(ctx, deps)
-        except Exception as e:  # noqa: BLE001 — isolate any plugin failure
-            reason = _one_line(f"{type(e).__name__}: {e}")
-            failures.append((plugin.plugin_id, reason))
-            section = Section(plugin.section_id, tr("plugin_failed", ctx.lang, reason=reason), "no-data")
-        else:
-            shared[plugin.plugin_id] = section.shared
+        with progress.step("plugin", text=_plugin_name(plugin, ctx.lang)) as step:
+            try:
+                section = plugin.run(ctx, deps)
+            except Exception as e:  # noqa: BLE001 — isolate any plugin failure
+                reason = _one_line(f"{type(e).__name__}: {e}")
+                failures.append((plugin.plugin_id, reason))
+                step.fail(reason)
+                section = Section(plugin.section_id, tr("plugin_failed", ctx.lang, reason=reason), "no-data")
+            else:
+                shared[plugin.plugin_id] = section.shared
         if section.title is None and plugin.title_key:
             section.title = tr(plugin.title_key, ctx.lang)
         by_id[plugin.plugin_id] = section
@@ -120,8 +131,8 @@
     return "\n\n".join(parts) + "\n"
 
 
-def build_plan(ctx, plugins: list) -> PlanResult:
-    sections, shared, failures = run_plugins(ctx, plugins)
+def build_plan(ctx, plugins: list, progress=None) -> PlanResult:
+    sections, shared, failures = run_plugins(ctx, plugins, progress)
     try:
         summary = build_summary_section(sections, ctx.lang)
     except Exception as e:  # noqa: BLE001 — the summary is outside run_plugins' isolation
```

Modify `skills/osm-day-route-day-plan/scripts/build_day_plan.py` — apply this patch (`patch -p1`):

```diff
--- a/skills/osm-day-route-day-plan/scripts/build_day_plan.py
+++ b/skills/osm-day-route-day-plan/scripts/build_day_plan.py
@@ -3,7 +3,10 @@
 
 Standard-library only. Usage:
     python3 build_day_plan.py <route_dir> <YYYY-MM-DD>
-        [--lang <ISO 639-1>] [--departure "<city or station>"] [--start HH:MM]
+        [--lang <ISO 639-1>] [--departure "<city or station>"] [--start HH:MM] [--quiet]
+
+Progress (one line per plugin, in the --lang language, on stderr) is printed when run from the command line;
+--quiet switches it off. Library callers and tests get none unless they pass `progress`.
 
 --departure is written into the file, and the file is meant to be forwarded
 (it is embedded in map.html), so pass a city, station or stop — never a street
@@ -36,6 +39,7 @@
 from day_plan.plugins.trail_passability import TrailPassabilityPlugin
 from day_plan.plugins.transit import TransitPlugin
 from day_plan.plugins.weather import WeatherPlugin
+from day_plan.progress import Progress
 from day_plan.service import build_plan
 
 
@@ -83,13 +87,17 @@
     return text.strip(), False
 
 
-def main(argv=None, http=get_json, now=None, plugins=None, http_text=get_text) -> int:
+AUTO_PROGRESS = object()        # main(progress=AUTO_PROGRESS): a Progress in the --lang language unless --quiet
+
+
+def main(argv=None, http=get_json, now=None, plugins=None, http_text=get_text, progress=None) -> int:
     parser = argparse.ArgumentParser(description=__doc__)
     parser.add_argument("route_dir")
     parser.add_argument("date", help="YYYY-MM-DD")
     parser.add_argument("--lang", default="en")
     parser.add_argument("--departure", default=None)
     parser.add_argument("--start", default=None, help="planned start time HH:MM")
+    parser.add_argument("--quiet", action="store_true", help="no progress lines")
     args = parser.parse_args(argv)
 
     route_dir = Path(args.route_dir)
@@ -110,7 +118,10 @@
 
     ctx = build_context(route_dir, date, lang=args.lang, departure=departure, start_time=start,
                         http=http, http_text=http_text, now=now)
-    result = build_plan(ctx, plugins if plugins is not None else default_plugins())
+    plugin_list = plugins if plugins is not None else default_plugins()
+    if progress is AUTO_PROGRESS:
+        progress = None if args.quiet else Progress(total_steps=len(plugin_list), lang=args.lang)
+    result = build_plan(ctx, plugin_list, progress)
     out = route_dir / f"day-plan-{date.isoformat()}.md"
     out.write_text(result.markdown, encoding="utf-8")
     print(f"wrote {out.resolve()}")
@@ -142,4 +153,4 @@
 
 
 if __name__ == "__main__":
-    sys.exit(main())
+    sys.exit(main(progress=AUTO_PROGRESS))
```

Modify `skills/osm-day-route-day-plan/SKILL.md` — apply this patch (`patch -p1`):

````diff
--- a/skills/osm-day-route-day-plan/SKILL.md
+++ b/skills/osm-day-route-day-plan/SKILL.md
@@ -97,9 +97,11 @@
    ```bash
    python3 build_day_plan.py <route_dir> <YYYY-MM-DD> \
        --lang <ISO 639-1 of the person's language> \
-       [--departure "<city or station>"] [--start HH:MM]
+       [--departure "<city or station>"] [--start HH:MM] [--quiet]
    ```
-   Re-running for the same date overwrites that date's file; other dates are
+   While it runs, one progress line per part (weather, daylight, hazards …) is
+   printed to stderr **in the `--lang` language**, with how long each took or
+   why it failed; `--quiet` switches that off. Re-running for the same date overwrites that date's file; other dates are
    kept. Network results are cached in `<route_dir>/day_plan_cache.json`
    (forecasts 3 hours, Overpass lines 7 days, holiday lists 30 days, the
    route's country for good).
````

Modify `README.md` — apply this patch (`patch -p1`):

```diff
--- a/README.md
+++ b/README.md
@@ -50,6 +50,7 @@
 - Estimates duration and warns if the day may not fit in daylight.
 - Labels every claim about a place by how sure it is: `tag-backed` (OSM says so), `web-sourced` (found online, unverified in person), `derived` (an estimate), `no-data` (nothing found). It does not invent answers.
 - Checks the saved archive is complete before showing you the result.
+- Shows what it is doing while it works, in your language: one line per step (map download, road graph, elevations, routing), with counts and timings. A downloaded map area is kept for a day, so changing a point does not wait for the server again. Elevations in `route.geojson` are stored to 0.1 m.
 
 Revising: refer to an existing route ("change the start point", "make it a bike route") and it updates the same folder rather than creating a new one.
 
```

- [ ] **Step 4: Run the suites** of all three skills (`cd skills/osm-day-route-planning && python3 -m pytest tests -q`, the same in `skills/osm-day-route-show` and `skills/osm-day-route-day-plan`): all green.

- [ ] **Step 5: Commit**

```bash
git add skills README.md
git commit -m "Day plan: progress lines per plugin in the user's language, --quiet

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

### Task 8: Live check on real data

No new code unless a defect is found (then fix it with a test in the owning task's test file). Uses the real network; scratch folders are outside the repository and nothing is committed.

- [ ] **Step 1: Compare the old and the new `tag_edges` on real data.** Fetch the area of Pelayos de la Presa once (centre 40.3605 N, 4.3334 W, radius 7000 m, walk) and keep the answer; run the `tag_edges` of the commit before this plan (a scratch copy of `main` at that commit) and the new one on the same graph and compare the tags of every directed edge. Expected: identical, the new one under 5 s.
- [ ] **Step 2: Run the planner pipeline with progress in Russian** (a script like the SKILL example: Sokolniki, radius 1500 m, `Progress(lang="ru")`, `cache_dir` in a scratch folder) in the background with its output in a log. Expected: lines `[1/5] Запрос к Overpass …` through `[5/5] Прокладка маршрута …`, each closed by a `✓` line with seconds and counts, elevation ticks while the first fetch runs, no English words.
- [ ] **Step 3: Run it again.** Expected: the Overpass step says the cached answer was used (with its age), the elevation step reports its points as taken from the cache, and the whole run is fast.
- [ ] **Step 4: Check the written archive.** `archive_validate` passes; the LineString elevations have at most one decimal; `elevation_gain_m` and `elevation_loss_m` too.
- [ ] **Step 5: Day plan progress.** Build a day plan with `--lang ru` for that route and a winter date: one line per plugin with Russian names on stderr, nothing on stdout but the `wrote` line and the hints; with `--quiet` nothing; with `--lang de` German names.
- [ ] **Step 6: Unavailable Overpass.** Run the fetch against an unreachable endpoint list in a scratch script: the log shows the failed attempts and the endpoint switches, not a silence.
- [ ] **Step 7: Final state.** `git status` clean and the suites of all three skills green.
