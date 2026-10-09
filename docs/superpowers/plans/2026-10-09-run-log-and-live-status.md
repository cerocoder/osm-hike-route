# Run Log and Live Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every long planner / day-plan run writes a JSONL run log in the route folder (spans, every HTTP request and series with send→answer timing) and a live status file that a Claude Code statusline shows instead of the normal line while a skill runs.

**Architecture:** A stdlib-only `runlog.py` (identical copy in `osm-day-route-planning/scripts/` and `osm-day-route-day-plan/scripts/day_plan/`, like `progress.py`) owns the log file, the status file and a module-level "current run" so HTTP layers need no new parameters. `Progress` forwards its steps/ticks/notes to an optional `runlog`. `statusline.py` reads status files; `log_report.py` summarises a log.

**Tech Stack:** Python 3 stdlib, pytest. Run tests per skill: `cd skills/<skill> && python3 -m pytest -q`.

**Spec:** `docs/superpowers/specs/2026-10-09-run-log-and-live-status-design.md`

## Global Constraints

- Stdlib only; no new dependencies.
- Log language English with stable field names; console progress stays in the user's language.
- Log file: directly in the route folder, `<tool>-<UTC yyyymmddTHHMMSS>.log.jsonl`, no subfolder; the 20 newest `*.log.jsonl` per folder are kept.
- Every `http` event carries `t_sent`, `t_answer`, `dur` (send → answer); every series of requests gets one `http_series` event with `dur` = first request sent → last answer and `sum_dur` = sum of single `dur`s.
- Only host and path of a URL are ever logged (no query string, fragment or userinfo).
- A failing log or status write never raises into the work (first failure silences it).
- Status file: `~/.cache/osm-hike-route/status/<pid>.json` (override with env `OSM_HIKE_STATUS_DIR`), atomic write, at most once per second; heartbeat younger than 30 s and live pid = "running".
- Statusline: a running skill's progress line replaces the normal line; otherwise the `--fallback` command runs with the same stdin (2 s limit, failure prints nothing).
- `progress.py` and `runlog.py` copies in the two skills must stay byte-identical (tests compare them).
- Existing suites of all three skills stay green.

## Review Focus

- The status heartbeat must survive a single HTTP call longer than 30 s (Overpass 90 s timeout): a background thread refreshes it, otherwise the normal line would flash back mid-run. (Task 1, `test_heartbeat_thread_keeps_the_status_fresh_without_events`)
- Two runs in the same second in one folder must not overwrite each other's log. (Task 1, `test_two_runs_in_the_same_second_get_different_files`)
- A URL carrying a secret in its query string (`?key=SECRET`) must never reach the log. (Task 1 `test_http_call_logs_host_and_path_only`, Task 3 `test_query_overpass_logs_attempts_in_a_series_without_the_query`)
- A read-only or missing route folder, a closed stream or a full disk must not stop a planning run. (Task 1 `test_unwritable_folder_gives_a_null_log`, `test_a_failing_write_silences_the_log_without_raising`)
- A crashed run leaves a status file behind: the statusline must ignore it (dead pid / old heartbeat) and show the normal line. (Task 5 `test_dead_pid_and_stale_heartbeat_are_ignored`)
- A hung or broken fallback command must not hang or break the statusline. (Task 5 `test_slow_or_failing_fallback_prints_nothing`)

---

## File Structure

| File | Responsibility |
|---|---|
| `skills/osm-day-route-planning/scripts/runlog.py` (new) | `RunLog`, `NullRunLog`, module-level `current/install/http_call/http_series/span`, status file writer + heartbeat thread |
| `skills/osm-day-route-day-plan/scripts/day_plan/runlog.py` (new) | byte-identical copy |
| `skills/osm-day-route-planning/scripts/progress.py` + day-plan copy | `runlog=` parameter, `span=` on `step`, forwarding hooks, message `status_total` |
| `skills/osm-day-route-planning/scripts/overpass_query.py` | `http_call`/`http_series`/cache events in `query_overpass` |
| `skills/osm-day-route-planning/scripts/elevation/__init__.py` + providers | series `elevation`, one `http` event per provider batch, `host` attribute on providers |
| `skills/osm-day-route-planning/scripts/public_routes.py` | series `public_geometry` around `load_tracks` groups |
| `skills/osm-day-route-day-plan/scripts/day_plan/http.py`, `overpass.py`, `service.py`, `scripts/build_day_plan.py` | http events, overpass series, per-plugin span + series, `--no-log`, log in the route folder |
| `skills/osm-day-route-planning/scripts/statusline.py` (new) | the one `statusLine` command |
| `skills/osm-day-route-planning/scripts/log_report.py` (new) | text report of a log |
| SKILL.md ×2, `README.md`, spec | documentation |

---

### Task 1: `runlog.py` — log file, spans, HTTP timing, status file

**Files:**
- Create: `skills/osm-day-route-planning/scripts/runlog.py`
- Create: `skills/osm-day-route-day-plan/scripts/day_plan/runlog.py` (copy)
- Create: `skills/osm-day-route-planning/tests/test_runlog.py`
- Modify: `skills/osm-day-route-planning/tests/conftest.py` (autouse isolation)

**Interfaces:**
- Produces (used by every later task):
  - `RunLog.start(folder, tool, argv=None, install_as_current=True, status_dir=None, heartbeat=True, heartbeat_interval=HEARTBEAT_INTERVAL_S, clock=time.monotonic, wall=time.time, keep=KEEP_LOGS) -> RunLog | NullRunLog` (never raises)
  - `RunLog.now() -> float`, `.event(ev, **fields)`, `.span(name, **fields)` (context manager), `.span_start(name, **fields) -> token`, `.span_end(token, ok=True, error=None, **fields)`, `.http_call(url, attempt=1)` (context manager yielding a call with `.set(status=None, nbytes=None, ok=None, cache=None)`), `.http_series(name)` (context manager), `.cache(kind, result, age_s=None)`, `.metric(name, value)`, `.warn(msg, **fields)`, `.error(msg, exc=None)`, `.close(ok=True, **fields)`, `with RunLog.start(...) as log:`
  - Progress hooks: `.step_start(span_name, title, index, total, lang)`, `.step_end(ok, error, detail)`, `.progress_tick(done, total, key)`, `.message(level, key, params)`
  - `NullRunLog` with the same surface (all no-ops)
  - module level: `current()`, `install(log_or_None)`, `http_call(url, attempt=1)`, `http_series(name)`, `span(name, **fields)`, `default_status_dir()`, `split_url(url) -> (host, path)`
  - Event shapes exactly as in the spec table, plus `note` = `{"ev":"note","key":<message key>,"params":{...}}` and `warn` from `message("warn", ...)` = `{"ev":"warn","msg":<message key>,"params":{...}}`.

- [ ] **Step 1: Isolate tests from the real status folder and the global "current" log**

Append to `skills/osm-day-route-planning/tests/conftest.py`:

```python
import pytest


@pytest.fixture(autouse=True)
def isolated_runlog(tmp_path, monkeypatch):
    """No test may write to the real ~/.cache status folder or leak an installed run log into the next test."""
    monkeypatch.setenv("OSM_HIKE_STATUS_DIR", str(tmp_path / "_status"))
    yield
    import runlog
    runlog.install(None)
```

(`runlog` does not exist yet, so the first run below fails at teardown too; that is expected.)

- [ ] **Step 2: Write the failing tests**

Create `skills/osm-day-route-planning/tests/test_runlog.py`:

```python
import json
import os
import time
from pathlib import Path

import pytest

import runlog
from runlog import NullRunLog, RunLog, split_url


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_log(tmp_path, clock):
    def _make(**kw):
        kw.setdefault("status_dir", tmp_path / "status")
        kw.setdefault("heartbeat", False)
        kw.setdefault("install_as_current", False)
        return RunLog.start(tmp_path / "route", "plan", argv=["plan", "--lang", "ru"], clock=clock,
                            wall=lambda: 1_700_000_000.0 + (clock.t - 100.0), **kw)
    return _make


def events(log):
    return [json.loads(line) for line in Path(log.path).read_text(encoding="utf-8").splitlines()]


# ---- the file ---------------------------------------------------------------------------------------------------------------

def test_start_creates_the_log_in_the_route_folder_and_writes_run_start(make_log, tmp_path):
    log = make_log()
    assert log.path.parent == tmp_path / "route"
    assert log.path.name == "plan-20231114T221320.log.jsonl"
    first = events(log)[0]
    assert first["ev"] == "run_start" and first["t"] == 0.0
    assert first["tool"] == "plan" and first["argv"] == ["plan", "--lang", "ru"] and first["version"] == 1
    assert "python" in first and "platform" in first


def test_two_runs_in_the_same_second_get_different_files(make_log):
    first, second = make_log(), make_log()
    assert first.path != second.path and second.path.name.endswith("-2.log.jsonl")
    assert first.path.exists() and second.path.exists()


def test_every_line_is_flushed_at_once(make_log):
    log = make_log()
    log.event("metric", name="x", value=1)
    assert events(log)[-1]["name"] == "x"                      # readable while the file is still open


def test_non_ascii_argv_is_kept_readable(tmp_path, clock):
    log = RunLog.start(tmp_path / "r", "plan", argv=["--name", "Дорога №1"], clock=clock, heartbeat=False,
                       install_as_current=False, status_dir=tmp_path / "s")
    assert "Дорога №1" in Path(log.path).read_text(encoding="utf-8")


def test_retention_keeps_the_newest_logs_only(tmp_path, clock):
    route = tmp_path / "route"
    route.mkdir()
    for i in range(25):
        f = route / f"plan-old{i:02d}.log.jsonl"
        f.write_text("{}\n")
        os.utime(f, (1000 + i, 1000 + i))
    (route / "route.geojson").write_text("{}")
    log = RunLog.start(route, "plan", clock=clock, heartbeat=False, install_as_current=False, status_dir=tmp_path / "s")
    names = sorted(p.name for p in route.glob("*.log.jsonl"))
    assert len(names) == 20 and log.path.name in names and "plan-old00.log.jsonl" not in names
    assert (route / "route.geojson").exists()                  # only logs are pruned


def test_unwritable_folder_gives_a_null_log(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = RunLog.start(blocker / "route", "plan", heartbeat=False, install_as_current=False, status_dir=tmp_path / "s")
    assert isinstance(log, NullRunLog)
    log.event("metric", name="x", value=1)                     # and it is harmless
    with log.span("a"), log.http_call("https://h/p") as call:
        call.set(status=200)


def test_a_failing_write_silences_the_log_without_raising(make_log):
    log = make_log()

    class Broken:
        def write(self, text):
            raise OSError("disk full")

        def flush(self):
            pass

        def close(self):
            pass

    log._fh = Broken()
    log.event("metric", name="x", value=1)
    log.event("metric", name="y", value=2)                     # silenced for good, still no exception
    log.close()


# ---- spans ------------------------------------------------------------------------------------------------------------------

def test_spans_nest_and_carry_their_duration(make_log, clock):
    log = make_log()
    with log.span("graph"):
        clock.advance(2)
        with log.span("inner"):
            clock.advance(1.5)
            log.metric("edges", 5)
    evs = events(log)
    assert [(e["ev"], e["span"]) for e in evs[1:]] == [
        ("span_start", "graph"), ("span_start", "graph.inner"), ("metric", "graph.inner"),
        ("span_end", "graph.inner"), ("span_end", "graph")]
    assert evs[-2]["dur"] == 1.5 and evs[-1]["dur"] == 3.5 and evs[-1]["ok"] is True


def test_a_span_that_raises_is_closed_with_the_error_and_reraises(make_log):
    log = make_log()
    with pytest.raises(ValueError):
        with log.span("tag"):
            raise ValueError("bad\nthing")
    end = events(log)[-1]
    assert end["ev"] == "span_end" and end["ok"] is False and end["error"] == "ValueError: bad thing"


# ---- http: single requests and series ---------------------------------------------------------------------------------------

def test_http_call_logs_send_to_answer_time(make_log, clock):
    log = make_log()
    clock.advance(1)
    with log.http_call("https://api.example.org/v1/data?key=SECRET&x=1#frag", attempt=2) as call:
        clock.advance(0.75)
        call.set(status=200, nbytes=1234)
    e = events(log)[-1]
    assert e["ev"] == "http" and e["host"] == "api.example.org" and e["path"] == "/v1/data"
    assert (e["t_sent"], e["t_answer"], e["dur"]) == (1.0, 1.75, 0.75)
    assert e["status"] == 200 and e["bytes"] == 1234 and e["attempt"] == 2 and e["ok"] is True
    assert "SECRET" not in Path(log.path).read_text(encoding="utf-8")


def test_http_call_logs_host_and_path_only():
    assert split_url("https://u:p@h.example:8080/a/b?key=SECRET#f") == ("h.example:8080", "/a/b")
    assert split_url("not a url") == ("", "not a url")
    assert split_url(None)[0] == ""                            # never raises


def test_http_call_that_raises_is_logged_as_failed_with_its_time(make_log, clock):
    log = make_log()
    with pytest.raises(OSError):
        with log.http_call("https://h.example/p"):
            clock.advance(3)
            raise OSError("timed out")
    e = events(log)[-1]
    assert e["ok"] is False and e["dur"] == 3.0 and e["error"] == "OSError: timed out"


def test_an_error_status_marks_the_call_failed(make_log):
    log = make_log()
    with log.http_call("https://h.example/p") as call:
        call.set(status=503)
    assert events(log)[-1]["ok"] is False


def test_series_reports_wall_time_first_sent_to_last_answer_and_the_sum_of_singles(make_log, clock):
    log = make_log()
    with log.http_series("elevation"):
        with log.http_call("https://h.example/a") as call:
            clock.advance(0.5)
            call.set(status=200, nbytes=10)
        clock.advance(1.0)                                      # rate-limit pause between requests
        with log.http_call("https://h.example/b") as call:
            clock.advance(0.25)
            call.set(status=500)
    evs = events(log)
    singles = [e for e in evs if e["ev"] == "http"]
    assert all(e["series"] == "elevation" for e in singles)
    s = evs[-1]
    assert s["ev"] == "http_series" and s["series"] == "elevation"
    assert (s["n"], s["ok"], s["failed"], s["bytes"]) == (2, 1, 1, 10)
    assert (s["t_first_sent"], s["t_last_answer"], s["dur"], s["sum_dur"]) == (0.0, 1.75, 1.75, 0.75)


def test_an_empty_series_writes_nothing_and_nested_series_both_count(make_log):
    log = make_log()
    with log.http_series("empty"):
        pass
    assert all(e["ev"] != "http_series" for e in events(log))
    with log.http_series("outer"):
        with log.http_series("inner"):
            with log.http_call("https://h.example/a"):
                pass
    series = {e["series"]: e for e in events(log) if e["ev"] == "http_series"}
    assert series["outer"]["n"] == 1 and series["inner"]["n"] == 1
    assert [e for e in events(log) if e["ev"] == "http"][0]["series"] == "inner"


def test_cache_note_warn_and_error_events(make_log):
    log = make_log()
    log.cache("overpass", "hit", age_s=3600)
    log.message("note", "overpass_attempt", {"endpoint": "h", "n": 2, "m": 3})
    log.message("warn", "overpass_failed", {"endpoint": "h", "reason": "504"})
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        log.error("plugin fire failed", exc)
    c, n, w, er = events(log)[-4:]
    assert c["ev"] == "cache" and (c["kind"], c["result"], c["age_s"]) == ("overpass", "hit", 3600)
    assert n["ev"] == "note" and n["key"] == "overpass_attempt" and n["params"]["n"] == 2
    assert w["ev"] == "warn" and w["msg"] == "overpass_failed" and w["params"]["reason"] == "504"
    assert er["ev"] == "error" and "RuntimeError: boom" in "".join(er["traceback"])


def test_metric_ticks_are_rate_limited_but_the_last_one_is_kept(make_log, clock):
    log = make_log()
    log.step_start("tag_edges", "Tagging", 1, 3, "en")
    for done in range(1, 6):
        log.progress_tick(done, 5, "tag_progress")
        clock.advance(1)                                        # five ticks within 5 s
    log.progress_tick(5, 5, "tag_progress")
    metrics = [e for e in events(log) if e["ev"] == "metric"]
    assert [m["done"] for m in metrics] == [1, 5, 5] and metrics[0]["name"] == "tag_progress"


def test_close_writes_run_end_once_and_uninstalls(tmp_path, clock):
    log = RunLog.start(tmp_path / "r", "plan", clock=clock, heartbeat=False, status_dir=tmp_path / "s")
    assert runlog.current() is log
    clock.advance(4)
    log.close()
    log.close()
    ends = [e for e in events(log) if e["ev"] == "run_end"]
    assert len(ends) == 1 and ends[0]["dur"] == 4.0 and ends[0]["ok"] is True
    assert isinstance(runlog.current(), NullRunLog)


def test_context_manager_records_a_crash(tmp_path, clock):
    with pytest.raises(RuntimeError):
        with RunLog.start(tmp_path / "r", "plan", clock=clock, heartbeat=False, install_as_current=False,
                          status_dir=tmp_path / "s") as log:
            raise RuntimeError("boom")
    evs = events(log)
    assert evs[-2]["ev"] == "error" and evs[-1]["ev"] == "run_end" and evs[-1]["ok"] is False


def test_module_helpers_use_the_installed_log_and_are_harmless_without_one(make_log):
    with runlog.http_call("https://h.example/p") as call:       # no log installed: nothing happens
        call.set(status=200)
    log = make_log()
    runlog.install(log)
    with runlog.http_series("s"), runlog.http_call("https://h.example/p"), runlog.span("x"):
        pass
    assert {"http", "http_series", "span_end"} <= {e["ev"] for e in events(log)}


def test_the_null_log_accepts_every_call():
    log = NullRunLog()
    log.event("x")
    log.cache("a", "hit")
    log.step_start("a", "t", 1, 2, "en")
    log.step_end(True, None, None)
    log.progress_tick(1, 2, "k")
    log.message("note", "k", {})
    log.close()
    with log.span("a"), log.http_series("b"), log.http_call("https://h/p") as call:
        call.set(status=200, nbytes=1, ok=True, cache="hit")


def test_the_day_plan_copy_is_identical():
    copy = Path(__file__).resolve().parents[2] / "osm-day-route-day-plan" / "scripts" / "day_plan" / "runlog.py"
    if not copy.exists():
        pytest.skip("osm-day-route-day-plan is not next to this skill")
    assert copy.read_text(encoding="utf-8") == Path(runlog.__file__).read_text(encoding="utf-8")


# ---- status file ------------------------------------------------------------------------------------------------------------

def status_of(tmp_path):
    files = list((tmp_path / "status").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_step_start_writes_the_status_file(make_log, tmp_path, clock):
    log = make_log()
    clock.advance(5)
    log.step_start("elevation", "Высоты", 3, 9, "ru")
    st = status_of(tmp_path)
    assert st["pid"] == os.getpid() and st["tool"] == "plan" and st["lang"] == "ru"
    assert (st["step_title"], st["i"], st["n"]) == ("Высоты", 3, 9)
    assert st["done"] is None and st["total"] is None
    assert st["step_started"] == 1_700_000_005.0 and st["run_started"] == 1_700_000_000.0
    assert st["log"] == str(log.path) and st["heartbeat"] == 1_700_000_005.0


def test_ticks_update_done_and_total_at_most_once_a_second(make_log, tmp_path, clock):
    log = make_log()
    log.step_start("elevation", "Высоты", 1, 2, "ru")
    log.progress_tick(1, 91, "elevation_batch")
    clock.advance(0.2)
    log.progress_tick(2, 91, "elevation_batch")                 # inside the same second: not written
    assert status_of(tmp_path)["done"] == 1
    clock.advance(1.0)
    log.progress_tick(3, 91, "elevation_batch")
    st = status_of(tmp_path)
    assert (st["done"], st["total"]) == (3, 91)


def test_a_step_change_is_written_immediately(make_log, tmp_path, clock):
    log = make_log()
    log.step_start("a", "A", 1, 2, "en")
    clock.advance(0.1)
    log.step_start("b", "B", 2, 2, "en")
    assert status_of(tmp_path)["step_title"] == "B"


def test_status_file_is_removed_on_close_and_the_write_is_atomic(make_log, tmp_path):
    log = make_log()
    log.step_start("a", "A", 1, 1, "en")
    assert not list((tmp_path / "status").glob("*.tmp"))
    log.close()
    assert not list((tmp_path / "status").glob("*.json"))


def test_heartbeat_thread_keeps_the_status_fresh_without_events(tmp_path):
    log = RunLog.start(tmp_path / "r", "plan", heartbeat=True, heartbeat_interval=0.05, install_as_current=False,
                       status_dir=tmp_path / "status")
    try:
        log.step_start("overpass", "Overpass", 1, 5, "en")
        first = json.loads(next((tmp_path / "status").glob("*.json")).read_text())["heartbeat"]
        time.sleep(0.4)                                          # one long request: no events at all
        later = json.loads(next((tmp_path / "status").glob("*.json")).read_text())["heartbeat"]
        assert later > first
    finally:
        log.close()


def test_an_unwritable_status_folder_never_breaks_the_run(tmp_path, clock):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = RunLog.start(tmp_path / "r", "plan", clock=clock, heartbeat=False, install_as_current=False,
                       status_dir=blocker / "status")
    log.step_start("a", "A", 1, 1, "en")
    log.progress_tick(1, 2, "k")
    log.step_end(True, None, None)
    log.close()
    assert events(log)[-1]["ev"] == "run_end"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_runlog.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'runlog'`.

- [ ] **Step 4: Implement `runlog.py`**

Create `skills/osm-day-route-planning/scripts/runlog.py`:

```python
"""Run log (JSONL, one file per run, in the route folder) and the live status file behind the statusline.

    log = RunLog.start(route_dir, "plan", argv=sys.argv)      # never raises; a NullRunLog when the folder is unwritable
    with log.http_series("elevation"):                        # wall time first request sent -> last answer
        with log.http_call("https://api.example.org/v1?key=X") as call:   # only host and path are logged
            ...
            call.set(status=200, nbytes=len(raw))
    log.close()

`install_as_current` (the default) makes the log the module's current one, so HTTP layers call the module-level
`http_call` / `http_series` / `span` without a parameter; without a current log these are no-ops. Everything here is
decoration for the work it reports on: the first failed write silences the file (or the status) and never raises.

The same file is kept in osm-day-route-day-plan/scripts/day_plan/runlog.py (a planning test compares them).
"""
import atexit
import contextlib
import itertools
import json
import os
import platform
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

LOG_VERSION = 1
KEEP_LOGS = 20
STATUS_INTERVAL_S = 1.0
HEARTBEAT_INTERVAL_S = 5.0
METRIC_INTERVAL_S = 5.0


def default_status_dir() -> Path:
    override = os.environ.get("OSM_HIKE_STATUS_DIR")
    return Path(override) if override else Path.home() / ".cache" / "osm-hike-route" / "status"


def split_url(url):
    """(host[:port], path) of a URL: no query string, fragment or credentials, never an exception."""
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        if host and parts.port:
            host += f":{parts.port}"
        return host, parts.path
    except Exception:  # noqa: BLE001
        return "", ""


def _one_line(exc) -> str:
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:300]


class _Series:
    def __init__(self, name):
        self.name = name
        self.n = self.ok = self.failed = self.bytes = 0
        self.first_sent = self.last_answer = None
        self.sum_dur = 0.0

    def add(self, t_sent, t_answer, ok, nbytes):
        self.n += 1
        self.ok += 1 if ok else 0
        self.failed += 0 if ok else 1
        self.first_sent = t_sent if self.first_sent is None else min(self.first_sent, t_sent)
        self.last_answer = t_answer if self.last_answer is None else max(self.last_answer, t_answer)
        self.sum_dur += t_answer - t_sent
        self.bytes += nbytes or 0


class _Call:
    def __init__(self, log, url, attempt):
        self._log = log
        self.host, self.path = split_url(url)
        self.attempt = attempt
        self.status = self.nbytes = self.cache = self.error = None
        self.ok = True
        self._finished = False
        self.t_sent = log.now()

    def set(self, status=None, nbytes=None, ok=None, cache=None):
        if isinstance(status, int) and not isinstance(status, bool):
            self.status = status
            if status >= 400 and ok is None:
                self.ok = False
        if isinstance(nbytes, int) and not isinstance(nbytes, bool):
            self.nbytes = nbytes
        if ok is not None:
            self.ok = bool(ok)
        if cache is not None:
            self.cache = cache

    def finish(self, error=None):
        if self._finished:
            return
        self._finished = True
        if error is not None:
            self.ok, self.error = False, error
        self._log._finish_call(self)


class _NullCall:
    def set(self, *args, **kwargs):
        pass

    def finish(self, *args, **kwargs):
        pass


class NullRunLog:
    """The default: every call does nothing."""
    path = None

    def now(self):
        return 0.0

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *args, **kwargs: None

    @contextlib.contextmanager
    def span(self, *args, **kwargs):
        yield

    @contextlib.contextmanager
    def http_series(self, *args, **kwargs):
        yield

    @contextlib.contextmanager
    def http_call(self, *args, **kwargs):
        yield _NullCall()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RunLog:
    def __init__(self, fh, path, tool, clock, wall, status_dir, heartbeat, heartbeat_interval):
        self._fh, self.path, self.tool = fh, Path(path), tool
        self._clock, self._wall = clock, wall
        self._t0 = clock()
        self._spans, self._tokens, self._series = [], [], []
        self._closed = False
        self._last_metric = float("-inf")
        self._status_lock = threading.RLock()
        self._status_path = Path(status_dir) / f"{os.getpid()}.json" if status_dir is not None else None
        self._status = {"pid": os.getpid(), "tool": tool, "lang": "en", "step_title": None, "i": None, "n": None,
                        "done": None, "total": None, "step_started": None, "run_started": wall(),
                        "heartbeat": wall(), "log": str(path)}
        self._status_written = float("-inf")
        self._stop = threading.Event()
        self._thread = None
        if heartbeat and self._status_path is not None:
            self._thread = threading.Thread(target=self._beat, args=(heartbeat_interval,), daemon=True)
            self._thread.start()
        atexit.register(self._atexit)

    # ---- construction -----------------------------------------------------------------------------------------------------
    @classmethod
    def start(cls, folder, tool, argv=None, install_as_current=True, status_dir=None, heartbeat=True,
              heartbeat_interval=HEARTBEAT_INTERVAL_S, clock=time.monotonic, wall=time.time, keep=KEEP_LOGS):
        try:
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromtimestamp(wall(), timezone.utc).strftime("%Y%m%dT%H%M%S")
            for n in itertools.count(1):
                name = f"{tool}-{stamp}.log.jsonl" if n == 1 else f"{tool}-{stamp}-{n}.log.jsonl"
                try:
                    fh = open(folder / name, "x", encoding="utf-8")
                    break
                except FileExistsError:
                    continue
        except OSError:
            return NullRunLog()
        log = cls(fh, folder / name, tool, clock, wall,
                  default_status_dir() if status_dir is None else status_dir, heartbeat, heartbeat_interval)
        log.event("run_start", tool=tool, argv=list(argv) if argv is not None else None,
                  python=platform.python_version(), platform=platform.platform(), version=LOG_VERSION,
                  started_at=datetime.fromtimestamp(wall(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _prune(folder, keep, log.path)
        if install_as_current:
            install(log)
        return log

    def now(self) -> float:
        return self._clock() - self._t0

    # ---- events -----------------------------------------------------------------------------------------------------------
    def event(self, ev, **fields):
        if self._fh is not None:
            record = {"t": round(self.now(), 3), "ev": ev}
            if self._spans and "span" not in fields:
                record["span"] = ".".join(self._spans)
            record.update({k: v for k, v in fields.items() if v is not None})
            try:
                self._fh.write(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
                self._fh.flush()
            except Exception:  # noqa: BLE001 — a log is never a failure of the work it reports on
                self._fh = None
        self._write_status()                                    # refreshes the heartbeat, at most once per second

    def metric(self, name, value):
        self.event("metric", name=name, value=value)

    def cache(self, kind, result, age_s=None):
        self.event("cache", kind=kind, result=result, age_s=age_s)

    def warn(self, msg, **fields):
        self.event("warn", msg=msg, **fields)

    def error(self, msg, exc=None):
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__) if exc is not None else None
        self.event("error", msg=msg, traceback=tb)

    def message(self, level, key, params):
        """A Progress note/warning, keyed by its message key (never the translated text)."""
        if level == "warn":
            self.event("warn", msg=key, params=dict(params))
        else:
            self.event("note", key=key, params=dict(params))

    # ---- spans ------------------------------------------------------------------------------------------------------------
    def span_start(self, name, **fields):
        self._spans.append(name)
        path = ".".join(self._spans)
        self.event("span_start", span=path, **fields)
        return (len(self._spans), path, self.now())

    def span_end(self, token, ok=True, error=None, **fields):
        depth, path, t0 = token
        del self._spans[depth - 1:]
        self.event("span_end", span=path, dur=round(self.now() - t0, 3), ok=ok, error=error, **fields)

    @contextlib.contextmanager
    def span(self, name, **fields):
        token = self.span_start(name, **fields)
        try:
            yield
        except BaseException as exc:
            self.span_end(token, ok=False, error=_one_line(exc))
            raise
        else:
            self.span_end(token)

    # ---- http -------------------------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def http_call(self, url, attempt=1):
        call = _Call(self, url, attempt)
        try:
            yield call
        except BaseException as exc:
            call.finish(error=_one_line(exc))
            raise
        else:
            call.finish()

    def _finish_call(self, call):
        t_answer = self.now()
        series = self._series[-1].name if self._series else None
        for s in self._series:
            s.add(call.t_sent, t_answer, call.ok, call.nbytes)
        self.event("http", host=call.host, path=call.path, status=call.status, bytes=call.nbytes,
                   attempt=call.attempt, cache=call.cache, t_sent=round(call.t_sent, 3),
                   t_answer=round(t_answer, 3), dur=round(t_answer - call.t_sent, 3), ok=call.ok,
                   error=call.error, series=series)

    @contextlib.contextmanager
    def http_series(self, name):
        s = _Series(name)
        self._series.append(s)
        try:
            yield s
        finally:
            self._series.remove(s)
            if s.n:
                self.event("http_series", series=name, n=s.n, ok=s.ok, failed=s.failed,
                           t_first_sent=round(s.first_sent, 3), t_last_answer=round(s.last_answer, 3),
                           dur=round(s.last_answer - s.first_sent, 3), sum_dur=round(s.sum_dur, 3), bytes=s.bytes)

    # ---- Progress hooks ---------------------------------------------------------------------------------------------------
    def step_start(self, span_name, title, index, total, lang):
        self._tokens.append(self.span_start(span_name, title=title))
        self._last_metric = float("-inf")
        self._set_status(force=True, lang=lang, step_title=title, i=index, n=total, done=None, total=None,
                         step_started=self._wall())

    def step_end(self, ok, error, detail):
        if self._tokens:
            self.span_end(self._tokens.pop(), ok=ok, error=error, detail=detail)

    def progress_tick(self, done, total, key):
        self._set_status(done=done, total=total)
        now = self.now()
        if done >= total or now - self._last_metric >= METRIC_INTERVAL_S:
            self._last_metric = now
            self.event("metric", name=key, done=done, total=total)

    # ---- status file ------------------------------------------------------------------------------------------------------
    def _set_status(self, force=False, **fields):
        with self._status_lock:
            self._status.update(fields)
            self._write_status(force)

    def _write_status(self, force=False):
        with self._status_lock:
            if self._status_path is None:
                return
            now = self._wall()
            if not force and now - self._status_written < STATUS_INTERVAL_S:
                return
            self._status["heartbeat"] = self._status_written = now
            temporary = self._status_path.with_suffix(f".{threading.get_ident()}.tmp")
            try:
                self._status_path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(self._status, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, self._status_path)
            except OSError:
                self._status_path = None                        # silenced for good
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _beat(self, interval):
        while not self._stop.wait(interval):                    # a request may take 90 s without a single event
            self._write_status(force=True)

    def _remove_status(self):
        with self._status_lock:
            if self._status_path is not None:
                try:
                    self._status_path.unlink()
                except OSError:
                    pass
                self._status_path = None

    # ---- end --------------------------------------------------------------------------------------------------------------
    def close(self, ok=True, **fields):
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self.event("run_end", dur=round(self.now(), 3), ok=ok, **fields)
        self._remove_status()
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None
        if current() is self:
            install(None)
        try:
            atexit.unregister(self._atexit)
        except Exception:  # noqa: BLE001
            pass

    def _atexit(self):
        self.close(ok=False, note="not closed explicitly")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.error(_one_line(exc), exc)
        self.close(ok=exc is None)
        return False


def _prune(folder, keep, own):
    try:
        logs = sorted(folder.glob("*.log.jsonl"), key=lambda p: p.stat().st_mtime)
        for old in logs[:max(0, len(logs) - keep)]:
            if old != own:
                old.unlink()
    except OSError:
        pass


# ---- the current run (so HTTP layers need no parameter) ---------------------------------------------------------------------
_current = NullRunLog()


def current():
    return _current


def install(log):
    global _current
    _current = log if log is not None else NullRunLog()


def http_call(url, attempt=1):
    return _current.http_call(url, attempt)


def http_series(name):
    return _current.http_series(name)


def span(name, **fields):
    return _current.span(name, **fields)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_runlog.py -q`
Expected: all pass except `test_the_day_plan_copy_is_identical` (skipped or failing until Step 6; it is skipped only if the day-plan skill is missing — here it fails).

- [ ] **Step 6: Create the day-plan copy and run both**

```bash
cp skills/osm-day-route-planning/scripts/runlog.py skills/osm-day-route-day-plan/scripts/day_plan/runlog.py
cd skills/osm-day-route-planning && python3 -m pytest -q
```
Expected: whole planning suite passes, including the identity test.

- [ ] **Step 7: Commit**

```bash
git add skills/osm-day-route-planning/scripts/runlog.py skills/osm-day-route-day-plan/scripts/day_plan/runlog.py skills/osm-day-route-planning/tests/test_runlog.py skills/osm-day-route-planning/tests/conftest.py
git commit -m "runlog: JSONL run log, HTTP send-to-answer timing and series, live status file

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `Progress` forwards to `RunLog`

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/progress.py` then copy to `skills/osm-day-route-day-plan/scripts/day_plan/progress.py`
- Modify: `skills/osm-day-route-planning/tests/test_progress.py` (append tests)

**Interfaces:**
- Consumes: `RunLog` hooks from Task 1 (`step_start/step_end/progress_tick/message`).
- Produces: `Progress(total_steps=None, lang="en", stream=None, clock=..., tty=None, color=None, tick_interval=..., runlog=None)`; `Progress.step(key, text=None, span=None, **params)`; new message key `status_total` (used by Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `skills/osm-day-route-planning/tests/test_progress.py`:

```python
# ---- forwarding to a run log ----------------------------------------------------------------------------------------------

class _Rec:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a))


def _p(rec, **kw):
    return pr.Progress(total_steps=3, lang="ru", stream=io.StringIO(), runlog=rec, **kw)


def test_a_step_is_forwarded_with_its_localized_title_and_counter():
    rec = _Rec()
    with _p(rec).step("graph") as step:
        step.detail("graph_done", nodes=1, edges=2)
    assert rec.calls[0] == ("step_start", ("graph", "Граф дорог", 1, 3, "ru"))
    assert rec.calls[-1] == ("step_end", (True, None, "1 вершин, 2 рёбер"))


def test_the_span_name_can_differ_from_the_message_key():
    rec = _Rec()
    with _p(rec).step("plugin", text="Погода", span="plugin.weather"):
        pass
    assert rec.calls[0] == ("step_start", ("plugin.weather", "Погода", 1, 3, "ru"))


def test_a_failed_or_raising_step_is_forwarded_as_not_ok():
    rec = _Rec()
    with _p(rec).step("graph") as step:
        step.fail("HTTP 503")
    assert rec.calls[-1] == ("step_end", (False, "HTTP 503", None))
    rec2 = _Rec()
    with pytest.raises(ValueError):
        with _p(rec2).step("graph"):
            raise ValueError("bad")
    assert rec2.calls[-1] == ("step_end", (False, "ValueError: bad", None))


def test_ticks_notes_and_warnings_are_forwarded_with_their_keys():
    rec = _Rec()
    progress = _p(rec)
    progress.tick(5, 10, "tag_progress")
    progress.note("overpass_cache_hit", age=3)
    progress.warn("overpass_failed", endpoint="h", reason="504")
    assert ("progress_tick", (5, 10, "tag_progress")) in rec.calls
    assert ("message", ("note", "overpass_cache_hit", {"age": 3})) in rec.calls
    assert ("message", ("warn", "overpass_failed", {"endpoint": "h", "reason": "504"})) in rec.calls


def test_a_run_log_that_raises_never_breaks_progress():
    class Boom:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise RuntimeError("log is broken")
            return fail

    out = io.StringIO()
    progress = pr.Progress(total_steps=1, lang="en", stream=out, runlog=Boom())
    with progress.step("graph"):
        progress.tick(1, 2)
        progress.note("overpass_cache_hit", age=1)
    assert "[1/1]" in out.getvalue()


def test_status_total_exists_in_every_language():
    assert set(pr.MESSAGES["status_total"]) == set(pr.LANGS)


def test_a_real_run_log_receives_the_steps(tmp_path):
    import runlog
    log = runlog.RunLog.start(tmp_path, "plan", heartbeat=False, install_as_current=False, status_dir=tmp_path / "s")
    progress = pr.Progress(total_steps=1, lang="de", stream=io.StringIO(), runlog=log)
    with progress.step("graph"):
        pass
    log.close()
    lines = [json.loads(l) for l in log.path.read_text(encoding="utf-8").splitlines()]
    start = next(e for e in lines if e["ev"] == "span_start")
    assert start["span"] == "graph" and start["title"] == "Wegegraph"
```

Check that `json`, `io`, `pytest` are imported at the top of `test_progress.py` (they are used by the existing tests: `io`, `pytest`, `re`); add `import json` if it is missing.

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_progress.py -q`
Expected: new tests FAIL (`unexpected keyword argument 'runlog'`).

- [ ] **Step 3: Implement in `progress.py`**

Edits to `skills/osm-day-route-planning/scripts/progress.py`:

1. Add to `MESSAGES` (next to `unit_s`):

```python
    "status_total": _m("total", "всего", "total", "total", "gesamt", "total", "totale"),
```

2. In `Progress.__init__` add the parameter and attribute:

```python
    def __init__(self, total_steps=None, lang="en", stream=None, clock=time.monotonic, tty=None, color=None,
                 tick_interval=TICK_INTERVAL_S, runlog=None):
        ...
        self._log = runlog                                      # optional RunLog; every call into it is guarded
```

3. Add the guarded forwarder in the "output helpers" section:

```python
    def _to_log(self, name, *args) -> None:
        """Forward to the run log. A log that raises is dropped; progress never fails because of it."""
        if self._log is None:
            return
        try:
            getattr(self._log, name)(*args)
        except Exception:  # noqa: BLE001 — the log is decoration like the console lines
            self._log = None
```

4. `step()` gets a `span` argument:

```python
    def step(self, key: str, text: str | None = None, span: str | None = None, **params):
        """... `span` names the step in the run log (default: the message key)."""
        return _Step(self, key, text, params, span)
```

5. `tick`, `note`, `warn` forward first thing:

```python
    def tick(self, done, total, key: str = "tag_progress", **params) -> None:
        self._to_log("progress_tick", done, total, key)
        now = self._clock()
        ...
    def note(self, key: str, **params) -> None:
        self._to_log("message", "note", key, params)
        self._write(...)
    def warn(self, key: str, **params) -> None:
        self._to_log("message", "warn", key, params)
        self._write(...)
```

6. `_Step`:

```python
    def __init__(self, progress, key, text, params, span=None):
        self.p = progress
        self.key, self.text, self.params = key, text, params
        self.span = span or key
        ...

    def __enter__(self):
        ...                                                     # after p._write(f"{counter} {title} {p._dots}")
        p._to_log("step_start", self.span, title, p._count, p.total_steps, p.lang)
        self.started = p._clock()
        return self

    def __exit__(self, exc_type, exc, tb):
        p = self.p
        seconds = p._seconds(p._clock() - self.started)
        if exc_type is not None:
            reason = " ".join(f"{exc_type.__name__}: {exc}".split())
            p._write(...)
            p._to_log("step_end", False, reason, None)
        elif self.failure is not None:
            p._write(...)
            p._to_log("step_end", False, self.failure, None)
        else:
            extra = ...
            p._write(...)
            p._to_log("step_end", True, None, self.detail_text)
        p._current = None
        return False
```

(`NullProgress.step(self, *args, **kwargs)` already accepts `span`.)

- [ ] **Step 4: Run to verify pass, copy, run the suite**

```bash
cp skills/osm-day-route-planning/scripts/progress.py skills/osm-day-route-day-plan/scripts/day_plan/progress.py
cd skills/osm-day-route-planning && python3 -m pytest -q
cd ../osm-day-route-day-plan && python3 -m pytest -q
```
Expected: both pass (the identity test for `progress.py` passes after the copy).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/progress.py skills/osm-day-route-day-plan/scripts/day_plan/progress.py skills/osm-day-route-planning/tests/test_progress.py
git commit -m "progress: forward steps, ticks, notes and warnings to an optional run log

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Planner HTTP instrumentation of Overpass, elevations and public routes

**Files:**
- Modify: `skills/osm-day-route-planning/scripts/overpass_query.py` (`query_overpass`)
- Modify: `skills/osm-day-route-planning/scripts/elevation/__init__.py` and the four providers in `scripts/elevation/providers/`
- Modify: `skills/osm-day-route-planning/scripts/public_routes.py` (`load_tracks`)
- Create: `skills/osm-day-route-planning/tests/test_http_logging.py`

**Interfaces:**
- Consumes: module-level `runlog.http_call/http_series/current` (Task 1).
- Produces: `http`/`http_series`/`cache` events with series names `overpass`, `elevation`, `public_geometry`; provider class attribute `host: str`.

- [ ] **Step 1: Write the failing tests**

Create `skills/osm-day-route-planning/tests/test_http_logging.py`:

```python
import json
from pathlib import Path

import pytest

import overpass_query
import runlog
from elevation import ElevationService
from elevation.providers.base import ElevationProvider
from runlog import RunLog


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def log(tmp_path):
    clock = Clock()
    log = RunLog.start(tmp_path / "route", "plan", clock=clock, heartbeat=False, status_dir=tmp_path / "s")
    log.clock = clock
    yield log
    log.close()


def events(log):
    return [json.loads(l) for l in Path(log.path).read_text(encoding="utf-8").splitlines()]


class _Response:
    def __init__(self, payload, status=200):
        self.status, self._raw = status, json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_query_overpass_logs_attempts_in_a_series_without_the_query(log, monkeypatch):
    answers = [_Response({}, status=504), _Response({"elements": []})]
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: answers.pop(0))
    monkeypatch.setattr(overpass_query.time, "sleep", lambda s: None)
    overpass_query.query_overpass("[out:json];node(1);out;SECRET_KEY=abc")
    evs = events(log)
    calls = [e for e in evs if e["ev"] == "http"]
    assert [c["status"] for c in calls] == [504, 200] and [c["ok"] for c in calls] == [False, True]
    assert all(c["series"] == "overpass" and c["host"] == "overpass-api.de" for c in calls[:1])
    series = next(e for e in evs if e["ev"] == "http_series")
    assert series["series"] == "overpass" and series["n"] == 2 and series["failed"] == 1
    assert "SECRET_KEY" not in Path(log.path).read_text(encoding="utf-8")


def test_query_overpass_logs_cache_hit_and_miss(log, tmp_path, monkeypatch):
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen",
                        lambda req, timeout=None: _Response({"elements": [{"id": 1}]}))
    cache = tmp_path / "cache"
    overpass_query.query_overpass("QL", cache_dir=cache)
    overpass_query.query_overpass("QL", cache_dir=cache)
    results = [(e["kind"], e["result"]) for e in events(log) if e["ev"] == "cache"]
    assert results == [("overpass", "miss"), ("overpass", "hit")]
    assert len([e for e in events(log) if e["ev"] == "http"]) == 1      # the second call made no request


class _Provider(ElevationProvider):
    def __init__(self, pid, host, results=None, raises=False):
        self.provider_id, self.host, self.max_batch, self.rate_limit_per_sec = pid, host, 2, 1000.0
        self._results, self._raises = results, raises

    def fetch(self, locations):
        if self._raises:
            raise RuntimeError("down")
        return self._results or [None] * len(locations)


def test_elevation_batches_are_a_series_with_one_http_event_each(log, tmp_path):
    provider = _Provider("p1", "elev.example", results=[1.0, 2.0])
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")
    service.get_elevations([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0)])
    evs = events(log)
    calls = [e for e in evs if e["ev"] == "http"]
    assert len(calls) == 2 and all(c["host"] == "elev.example" and c["series"] == "elevation" for c in calls)
    assert [e["n"] for e in evs if e["ev"] == "http_series"] == [2]


def test_a_provider_that_answers_nothing_or_raises_is_a_failed_call(log, tmp_path):
    service = ElevationService([_Provider("empty", "a.example"), _Provider("boom", "b.example", raises=True)],
                               cache_path=tmp_path / "elevation.json")
    service.get_elevations([(1.0, 1.0)])
    calls = [e for e in events(log) if e["ev"] == "http"]
    assert [(c["host"], c["ok"]) for c in calls] == [("a.example", False), ("b.example", False)]


def test_every_real_provider_declares_its_host():
    from elevation.providers.open_topo_data import OpenTopoDataProvider
    from elevation.providers.open_meteo import OpenMeteoProvider
    from elevation.providers.elevation_api_eu import ElevationApiEuProvider
    from elevation.providers.open_elevation import OpenElevationProvider
    hosts = {p.host for p in (OpenTopoDataProvider, OpenMeteoProvider, ElevationApiEuProvider, OpenElevationProvider)}
    assert hosts == {"api.opentopodata.org", "api.open-meteo.com", "www.elevation-api.eu", "api.open-elevation.com"}


def test_load_tracks_geometry_queries_are_one_series(log, monkeypatch):
    import public_routes
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: _Response({"elements": []}))
    public_routes.load_tracks([{"id": 1}, {"id": 2}, {"id": 3}], batch=1)
    series = [e for e in events(log) if e["ev"] == "http_series"]
    assert [s["series"] for s in series] == ["public_geometry"] and series[0]["n"] == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_http_logging.py -q`
Expected: FAIL (no `http` events, no `host` attribute).

- [ ] **Step 3: Implement**

`overpass_query.py` — add `import runlog` to the imports and change `query_overpass`:

```python
    cache_path = _cache_file(cache_dir, ql) if cache_dir is not None else None
    if cache_path is not None and not refresh:
        cached = _read_cache(cache_path, max_age_s)
        if cached is not None:
            runlog.current().cache("overpass", "hit", age_s=int(cached[1]))
            if progress is not None:
                progress.note("overpass_cache_hit", age=int(cached[1] // 3600))
            return cached[0]
    if cache_path is not None:
        runlog.current().cache("overpass", "miss")
    body = urllib.parse.urlencode({"data": ql}).encode()
    last_error = None
    with runlog.http_series("overpass"):
        for endpoint_index, endpoint in enumerate(ENDPOINTS):
            for attempt in range(retries):
                if progress is not None and (endpoint_index, attempt) != (0, 0):
                    progress.note("overpass_attempt", endpoint=_host(endpoint), n=attempt + 1, m=retries)
                try:
                    req = urllib.request.Request(endpoint, data=body, headers=HEADERS)
                    with runlog.http_call(endpoint, attempt=attempt + 1) as call:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            raw = resp.read()
                            call.set(status=resp.status, nbytes=len(raw))
                            if resp.status != 200:
                                last_error = f"{endpoint}: HTTP {resp.status}"
                                continue
                            text = raw.decode("utf-8", errors="replace")
                            if "runtime error" in text.lower() or "timeout" in text.lower() and text.lstrip().startswith("<"):
                                call.set(ok=False)
                                last_error = f"{endpoint}: server-side timeout/error body"
                                time.sleep(2)
                                continue
                            result = json.loads(text)
                    if cache_path is not None:
                        _write_cache(cache_path, result)
                    return result
                except Exception as e:
                    last_error = f"{endpoint}: {e}"
                    if progress is not None:
                        progress.warn("overpass_failed", endpoint=_host(endpoint), reason=" ".join(str(e).split())[:80])
                    time.sleep(2)
    raise RuntimeError(f"Overpass query failed on all endpoints/attempts: {last_error}")
```

Keep the existing body semantics exactly (the structure above is the current loop re-indented under the series, with `http_call` around the request). Note `continue` inside `with` blocks is fine; a `call.set(status=504)` already marks the call failed.

`elevation/__init__.py` — add `import runlog` and wrap the provider loop:

```python
        with runlog.http_series("elevation"):
            for provider in self._providers:
                ...
                for batch_indices in self._chunk(pending_indices, provider.max_batch):
                    batch_locations = [locations[i] for i in batch_indices]
                    self._respect_rate_limit(provider)
                    batches_done += 1
                    batches_total = max(batches_total, batches_done)
                    if progress is not None:
                        progress.tick(batches_done, batches_total, "elevation_batch")
                    host = getattr(provider, "host", provider.provider_id)
                    try:
                        with runlog.http_call(f"https://{host}/") as call:
                            batch_results = provider.fetch(batch_locations)
                            call.set(ok=any(r is not None for r in batch_results))
                    except Exception:
                        still_pending.extend(batch_indices)
                        continue
                    ...                                              # the rest unchanged
                pending_indices = still_pending
        return results
```

Add to each provider class: `host = "api.opentopodata.org"` (open_topo_data), `host = "api.open-meteo.com"` (open_meteo), `host = "www.elevation-api.eu"` (elevation_api_eu), `host = "api.open-elevation.com"` (open_elevation), next to `provider_id`. Add `host: str` (annotation only) to `ElevationProvider` in `base.py`.

`public_routes.py` — `import runlog` next to the other imports and wrap the group loop in `load_tracks`:

```python
    loaded, lost = [], 0
    with runlog.http_series("public_geometry"):
        for number, group in enumerate(groups, 1):
            ...                                                      # body unchanged, one level deeper
    return loaded, lost
```

- [ ] **Step 4: Run to verify pass**

Run: `cd skills/osm-day-route-planning && python3 -m pytest -q`
Expected: everything passes (existing Overpass/elevation/public-route tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning
git commit -m "planner: log Overpass attempts, elevation batches and geometry queries with send-to-answer timing

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Day-plan HTTP events, Overpass series, per-plugin spans and series, log in the route folder

**Files:**
- Modify: `skills/osm-day-route-day-plan/scripts/day_plan/http.py`, `overpass.py`, `service.py`
- Modify: `skills/osm-day-route-day-plan/scripts/build_day_plan.py`
- Modify: `skills/osm-day-route-day-plan/tests/conftest.py`
- Create: `skills/osm-day-route-day-plan/tests/test_run_log.py`

**Interfaces:**
- Consumes: `day_plan.runlog` (copy from Task 1), `Progress(runlog=…)`/`step(span=…)` (Task 2).
- Produces: `--no-log` flag; `<route_dir>/day-plan-<UTC>.log.jsonl`; series `plugin.<id>` per plugin and `overpass`.

- [ ] **Step 1: Isolate the day-plan tests**

Append to `skills/osm-day-route-day-plan/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def isolated_runlog(tmp_path, monkeypatch):
    """No test writes to the real ~/.cache status folder or leaks an installed run log."""
    monkeypatch.setenv("OSM_HIKE_STATUS_DIR", str(tmp_path / "_status"))
    yield
    from day_plan import runlog
    runlog.install(None)
```

- [ ] **Step 2: Write the failing tests**

Create `skills/osm-day-route-day-plan/tests/test_run_log.py`:

```python
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

import build_day_plan
from day_plan import runlog
from day_plan.http import HttpError, get_json, get_text
from day_plan.overpass import run


def _events(route_dir):
    logs = list(Path(route_dir).glob("day-plan-*.log.jsonl"))
    assert len(logs) == 1, logs
    return [json.loads(l) for l in logs[0].read_text(encoding="utf-8").splitlines()]


class _Resp:
    status = 200

    def __init__(self, raw=b"{}"):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_get_json_logs_host_path_status_and_bytes_but_not_the_query(tmp_path):
    log = runlog.RunLog.start(tmp_path, "t", heartbeat=False, status_dir=tmp_path / "s")
    with patch("day_plan.http._open", return_value=_Resp(b'{"a": 1}')):
        assert get_json("https://api.example.org/v1/f?key=SECRET") == {"a": 1}
    log.close()
    e = next(x for x in map(json.loads, log.path.read_text().splitlines()) if x["ev"] == "http")
    assert (e["host"], e["path"], e["status"], e["bytes"], e["ok"]) == ("api.example.org", "/v1/f", 200, 8, True)
    assert "SECRET" not in log.path.read_text()


def test_a_failed_get_is_logged_and_still_an_http_error(tmp_path):
    log = runlog.RunLog.start(tmp_path, "t", heartbeat=False, status_dir=tmp_path / "s")
    with patch("day_plan.http._open", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(HttpError):
            get_text("https://api.example.org/x")
    log.close()
    e = next(x for x in map(json.loads, log.path.read_text().splitlines()) if x["ev"] == "http")
    assert e["ok"] is False and "boom" in e["error"]


def test_overpass_mirror_attempts_are_one_series(tmp_path):
    log = runlog.RunLog.start(tmp_path, "t", heartbeat=False, status_dir=tmp_path / "s")
    answers = [HttpError("504"), {"elements": []}]

    def web(url):
        answer = answers.pop(0)
        with runlog.http_call(url):
            if isinstance(answer, Exception):
                raise answer
            return answer

    run(web, "QL", sleep=lambda s: None)
    log.close()
    series = [x for x in map(json.loads, log.path.read_text().splitlines()) if x["ev"] == "http_series"]
    assert [(s["series"], s["n"], s["failed"]) for s in series] == [("overpass", 2, 1)]


def test_the_cli_writes_the_log_next_to_the_plan_with_a_span_and_series_per_plugin(
        make_route, weather_response, fixed_now):
    route_dir = make_route()

    def http(url):
        with runlog.http_call(url):
            return weather_response()

    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru", "--quiet"], http=http,
                        http_text=lambda url, timeout=10.0: "", now=fixed_now, progress=build_day_plan.AUTO_PROGRESS)
    events = _events(route_dir)
    assert events[0]["ev"] == "run_start" and events[0]["tool"] == "day-plan"
    assert events[-1]["ev"] == "run_end" and events[-1]["ok"] is True
    spans = {e["span"] for e in events if e["ev"] == "span_end"}
    assert "plugin.weather" in spans
    assert any(e["ev"] == "http_series" and e["series"] == "plugin.weather" for e in events)
    assert (route_dir / "route.geojson").exists() and list(route_dir.glob("day-plan-2026-06-21.md"))


def test_no_log_flag_and_library_callers_write_no_log(make_route, weather_response, fixed_now):
    route_dir = make_route()
    http = lambda url: weather_response()  # noqa: E731
    build_day_plan.main([str(route_dir), "2026-06-21", "--no-log"], http=http, http_text=lambda u, timeout=10.0: "",
                        now=fixed_now, progress=build_day_plan.AUTO_PROGRESS)
    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=lambda u, timeout=10.0: "", now=fixed_now)
    assert not list(route_dir.glob("*.log.jsonl"))


def test_quiet_does_not_silence_the_log(make_route, weather_response, fixed_now):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21", "--quiet"], http=lambda url: weather_response(),
                        http_text=lambda u, timeout=10.0: "", now=fixed_now, progress=build_day_plan.AUTO_PROGRESS)
    assert len(list(route_dir.glob("day-plan-*.log.jsonl"))) == 1


def test_a_failing_plugin_is_an_error_in_the_log_and_the_run_still_ends(make_route, weather_response, fixed_now):
    route_dir = make_route()

    class Boom:
        plugin_id, section_id, version, depends_on, title_key = "boom", "summary", "1", (), None

        def run(self, ctx, deps):
            raise RuntimeError("kaput")

    build_day_plan.main([str(route_dir), "2026-06-21", "--quiet"], http=lambda url: weather_response(),
                        http_text=lambda u, timeout=10.0: "", now=fixed_now, plugins=[Boom()],
                        progress=build_day_plan.AUTO_PROGRESS)
    events = _events(route_dir)
    end = next(e for e in events if e["ev"] == "span_end" and e["span"] == "plugin.boom")
    assert end["ok"] is False and "kaput" in end["error"]
    assert events[-1]["ev"] == "run_end"
```

(`weather_response`, `fixed_now`, `make_route` are the existing fixtures; if the stub plugin attributes differ from the real `Plugin` base class in `day_plan/base.py`, build `Boom` from that base class instead — read it first.)

- [ ] **Step 3: Run to verify failure**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest tests/test_run_log.py -q`
Expected: FAIL (no events; `--no-log` unknown).

- [ ] **Step 4: Implement**

`day_plan/http.py` — `from . import runlog` and wrap the request in both getters (inside the existing `try`, so failures are logged and then converted to `HttpError`):

```python
def get_text(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with runlog.http_call(url) as call:
            with _open(req, timeout) as resp:
                raw = resp.read()
                call.set(status=getattr(resp, "status", None), nbytes=len(raw))
            return raw.decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e


def get_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with runlog.http_call(url) as call:
            with _open(req, timeout) as resp:
                raw = resp.read()
                call.set(status=getattr(resp, "status", None), nbytes=len(raw))
            return json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e
```

Existing day-plan tests whose fake `_open` returns an object without `read()` returning bytes (e.g. a `MagicMock`) must keep passing; `call.set` ignores non-int `status`, and `len(raw)` only needs `raw` to be bytes — if a test double returns a non-bytes object, adjust the double, not the production code.

`day_plan/overpass.py` — `from . import runlog`; in `run`, wrap everything from `for attempt in range(retries + 1):` to the final `raise` in `with runlog.http_series("overpass"):` (body unchanged, one level deeper; `raise OverpassError(last)` stays inside or after the `with`, either is fine).

`day_plan/service.py` — `from . import runlog`; in `run_plugins` pass the span and wrap the plugin in a series:

```python
        with progress.step("plugin", text=_plugin_name(plugin, ctx.lang), span=f"plugin.{plugin.plugin_id}") as step, \
                runlog.http_series(f"plugin.{plugin.plugin_id}"):
            try:
                section = plugin.run(ctx, deps)
            ...
```

(Because `progress` may be `NullProgress`, a run without Progress logs no plugin spans; the CLI always has a `Progress` unless `--quiet`… see next step: with `--quiet` the CLI still builds a `Progress` writing to a null stream so spans reach the log.)

`build_day_plan.py`:

```python
from day_plan import runlog as runlog_module
from day_plan.runlog import RunLog
...
    parser.add_argument("--quiet", action="store_true", help="no progress lines on stderr (the run log is kept)")
    parser.add_argument("--no-log", action="store_true", help="do not write the run log and the live status file")
...
    log = None
    if progress is AUTO_PROGRESS:
        if not args.no_log:
            log = RunLog.start(route_dir, "day-plan", argv=sys.argv if argv is None else list(argv))
        stream = io.StringIO() if args.quiet else None          # --quiet: no console lines, the log still gets every step
        if args.quiet and log is None:
            progress = None
        else:
            progress = Progress(total_steps=len(plugin_list), lang=args.lang, stream=stream, runlog=log)
    try:
        result = build_plan(ctx, plugin_list, progress)
    except BaseException as exc:
        if log is not None:
            log.error(f"{type(exc).__name__}: {exc}", exc)
            log.close(ok=False)
        raise
    ...                                                          # write the plan, print `wrote …`, hints (unchanged)
    if log is not None:
        log.close(ok=True)
    return 0
```

Add `import io` at the top. `log.close(ok=True)` goes right before each `return 0`/at the end of `main` (all paths after the log opened: only the one normal path and the exception path exist after `build_plan`).

- [ ] **Step 5: Run to verify pass**

Run: `cd skills/osm-day-route-day-plan && python3 -m pytest -q`
Expected: all pass. If an existing test asserts the exact content of the route folder or of stderr under `--quiet`, adapt only that assertion to ignore `*.log.jsonl`.

- [ ] **Step 6: Commit**

```bash
git add skills/osm-day-route-day-plan
git commit -m "day plan: run log in the route folder, http events, overpass series, span and series per plugin, --no-log

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `statusline.py`

**Files:**
- Create: `skills/osm-day-route-planning/scripts/statusline.py`
- Create: `skills/osm-day-route-planning/tests/test_statusline.py`

**Interfaces:**
- Consumes: status files written by Task 1; `progress.MESSAGES["status_total"]`.
- Produces: CLI `python3 statusline.py [--fallback "<cmd>"] [--status-dir DIR]`; functions `pick_status(status_dir, now, alive=pid_alive) -> dict | None`, `render(status, now) -> str`, `main(argv=None, stdin=None, stdout=None, now=time.time) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `skills/osm-day-route-planning/tests/test_statusline.py`:

```python
import io
import json
import os
import sys

import pytest

import statusline

NOW = 1_700_000_100.0


def put(directory, pid, **fields):
    status = {"pid": pid, "tool": "plan", "lang": "ru", "step_title": "Высоты", "i": 3, "n": 9, "done": 41,
              "total": 91, "step_started": NOW - 80, "run_started": NOW - 245, "heartbeat": NOW - 2, "log": "/x"}
    status.update(fields)
    (directory / f"{pid}.json").write_text(json.dumps(status), encoding="utf-8")


def run(directory, argv=(), now=NOW, stdin="{}"):
    out = io.StringIO()
    code = statusline.main(["--status-dir", str(directory), *argv], stdin=io.StringIO(stdin), stdout=out,
                           now=lambda: now, alive=lambda pid: True)
    return code, out.getvalue()


def test_a_running_skill_replaces_the_normal_line(tmp_path):
    put(tmp_path, 111)
    code, out = run(tmp_path, ["--fallback", "echo NORMAL"])
    assert code == 0 and out.strip() == "🥾 [3/9] Высоты 41/91 · 1:20 · всего 4:05"


def test_english_label_and_a_step_without_counters(tmp_path):
    put(tmp_path, 111, lang="en", step_title="Road graph", done=None, total=None, n=None, i=2)
    _, out = run(tmp_path)
    assert out.strip() == "🥾 [2] Road graph · 1:20 · total 4:05"


def test_nothing_running_runs_the_fallback_with_the_same_stdin(tmp_path):
    code, out = run(tmp_path, ["--fallback", f"{sys.executable} -c \"import sys; print('NORMAL', sys.stdin.read())\""],
                    stdin='{"model": "x"}')
    assert code == 0 and out.strip() == 'NORMAL {"model": "x"}'


def test_no_fallback_and_nothing_running_prints_nothing(tmp_path):
    assert run(tmp_path) == (0, "")


def test_dead_pid_and_stale_heartbeat_are_ignored(tmp_path):
    put(tmp_path, 222)
    put(tmp_path, 333, heartbeat=NOW - 31)
    out = io.StringIO()
    statusline.main(["--status-dir", str(tmp_path)], stdin=io.StringIO("{}"), stdout=out, now=lambda: NOW,
                    alive=lambda pid: pid != 222)
    assert out.getvalue() == ""


def test_the_freshest_of_several_live_runs_wins_and_junk_is_skipped(tmp_path):
    put(tmp_path, 1, step_title="Старый", heartbeat=NOW - 10)
    put(tmp_path, 2, step_title="Новый", heartbeat=NOW - 1)
    (tmp_path / "3.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "4.json").write_text("[]", encoding="utf-8")
    _, out = run(tmp_path)
    assert "Новый" in out


def test_a_missing_status_folder_is_not_an_error(tmp_path):
    assert run(tmp_path / "nope") == (0, "")


def test_slow_or_failing_fallback_prints_nothing(tmp_path):
    assert run(tmp_path, ["--fallback", "exit 3"])[1] == ""
    slow = f"{sys.executable} -c \"import time; time.sleep(10)\""
    import time
    started = time.monotonic()
    assert run(tmp_path, ["--fallback", slow])[1] == ""
    assert time.monotonic() - started < 5


def test_pid_alive_for_this_process_and_a_dead_one():
    assert statusline.pid_alive(os.getpid()) is True
    assert statusline.pid_alive(2 ** 22 + 12345) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_statusline.py -q`
Expected: collection error `No module named 'statusline'`.

- [ ] **Step 3: Implement**

Create `skills/osm-day-route-planning/scripts/statusline.py`:

```python
#!/usr/bin/env python3
"""The Claude Code `statusLine` command: while a planner / day-plan run is alive, its progress REPLACES the normal
line; otherwise the user's normal statusline command (--fallback) runs with the same stdin and its output is shown.

    python3 statusline.py --fallback "npx -y ccusage@latest statusline"

Reads the status files written by runlog.py (~/.cache/osm-hike-route/status/<pid>.json, or $OSM_HIKE_STATUS_DIR).
A run counts as live when its pid exists and its heartbeat is younger than 30 s. Never raises and never hangs.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progress import MESSAGES  # noqa: E402
from runlog import default_status_dir  # noqa: E402

STALE_AFTER_S = 30.0
FALLBACK_TIMEOUT_S = 2.0


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError, TypeError):
        return True                                              # exists, but not ours: treat as alive
    return True


def pick_status(status_dir, now, alive=pid_alive):
    """The freshest status of a live run, or None."""
    best = None
    try:
        files = list(Path(status_dir).glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
            heartbeat = float(status["heartbeat"])
            if not isinstance(status, dict) or now - heartbeat >= STALE_AFTER_S or not alive(status["pid"]):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if best is None or heartbeat > float(best["heartbeat"]):
            best = status
    return best


def _clock(seconds) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(status, now) -> str:
    lang = status.get("lang") if status.get("lang") in MESSAGES["status_total"] else "en"
    counter = f"[{status['i']}/{status['n']}]" if status.get("n") else f"[{status.get('i') or 1}]"
    line = f"🥾 {counter} {status.get('step_title') or ''}".rstrip()
    if status.get("total"):
        line += f" {status.get('done') or 0}/{status['total']}"
    if status.get("step_started"):
        line += f" · {_clock(now - status['step_started'])}"
    if status.get("run_started"):
        line += f" · {MESSAGES['status_total'][lang]} {_clock(now - status['run_started'])}"
    return line


def _fallback(command, stdin_text) -> str:
    try:
        process = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError:
        return ""
    try:
        out, _ = process.communicate(stdin_text, timeout=FALLBACK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.communicate()
        return ""
    except Exception:  # noqa: BLE001
        return ""
    return out.rstrip("\n") if process.returncode == 0 else ""


def main(argv=None, stdin=None, stdout=None, now=time.time, alive=pid_alive) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fallback", default=None, help="the normal statusline command")
    parser.add_argument("--status-dir", default=None)
    args = parser.parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        stdin_text = stdin.read()
    except Exception:  # noqa: BLE001
        stdin_text = ""
    status = pick_status(args.status_dir or default_status_dir(), now(), alive)
    if status is not None:
        line = render(status, now())
    else:
        line = _fallback(args.fallback, stdin_text) if args.fallback else ""
    if line:
        stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_statusline.py -q`
Expected: pass. Then a manual smoke check:

```bash
OSM_HIKE_STATUS_DIR=/tmp/osm-status-demo python3 -c "
import sys, time; sys.path.insert(0, 'skills/osm-day-route-planning/scripts')
from runlog import RunLog
log = RunLog.start('/tmp/osm-route-demo', 'plan', heartbeat=False)
log.step_start('elevation', 'Высоты', 3, 9, 'ru'); log.progress_tick(41, 91, 'elevation_batch')
import subprocess; print(subprocess.run([sys.executable, 'skills/osm-day-route-planning/scripts/statusline.py', '--fallback', 'echo NORMAL'], input='{}', capture_output=True, text=True).stdout)
log.close()
print(subprocess.run([sys.executable, 'skills/osm-day-route-planning/scripts/statusline.py', '--fallback', 'echo NORMAL'], input='{}', capture_output=True, text=True).stdout)"
```
Expected: first print `🥾 [3/9] Высоты 41/91 · 0:00 · всего 0:00`, second `NORMAL`.

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/statusline.py skills/osm-day-route-planning/tests/test_statusline.py
git commit -m "statusline: show skill progress instead of the normal line while a run is alive

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `log_report.py`

**Files:**
- Create: `skills/osm-day-route-planning/scripts/log_report.py`
- Create: `skills/osm-day-route-planning/tests/test_log_report.py`

**Interfaces:**
- Consumes: the JSONL event shapes from Task 1.
- Produces: CLI `python3 log_report.py <log.jsonl> [--top N]`; `load(path) -> list[dict]` (skips unreadable lines), `report(events, top=10) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `skills/osm-day-route-planning/tests/test_log_report.py`:

```python
import json

import log_report

EVENTS = [
    {"t": 0.0, "ev": "run_start", "tool": "plan", "argv": ["plan"]},
    {"t": 0.0, "ev": "span_start", "span": "overpass"},
    {"t": 0.1, "ev": "http", "host": "overpass-api.de", "path": "/api", "status": 504, "ok": False, "dur": 2.0,
     "t_sent": 0.1, "t_answer": 2.1, "bytes": 10, "series": "overpass", "attempt": 1},
    {"t": 5.0, "ev": "http", "host": "overpass-api.de", "path": "/api", "status": 200, "ok": True, "dur": 2.9,
     "t_sent": 2.1, "t_answer": 5.0, "bytes": 1000, "series": "overpass", "attempt": 2},
    {"t": 5.0, "ev": "http_series", "series": "overpass", "n": 2, "ok": 1, "failed": 1, "t_first_sent": 0.1,
     "t_last_answer": 5.0, "dur": 4.9, "sum_dur": 4.9, "bytes": 1010},
    {"t": 5.0, "ev": "span_end", "span": "overpass", "dur": 5.0, "ok": True},
    {"t": 5.0, "ev": "span_start", "span": "elevation"},
    {"t": 5.0, "ev": "span_start", "span": "elevation.inner"},
    {"t": 7.0, "ev": "span_end", "span": "elevation.inner", "dur": 2.0, "ok": True},
    {"t": 95.0, "ev": "http_series", "series": "elevation", "n": 91, "ok": 90, "failed": 1, "t_first_sent": 7.0,
     "t_last_answer": 95.0, "dur": 88.0, "sum_dur": 40.0, "bytes": 5000},
    {"t": 95.0, "ev": "span_end", "span": "elevation", "dur": 90.0, "ok": True},
    {"t": 95.0, "ev": "cache", "kind": "overpass", "result": "hit", "age_s": 60},
    {"t": 95.0, "ev": "cache", "kind": "overpass", "result": "miss"},
    {"t": 95.0, "ev": "warn", "msg": "overpass_failed", "params": {"endpoint": "h", "reason": "504"}},
    {"t": 96.0, "ev": "error", "msg": "plugin fire failed"},
    {"t": 100.0, "ev": "run_end", "dur": 100.0, "ok": True},
]


def test_report_has_the_total_the_span_tree_and_the_slowest_spans():
    text = log_report.report(EVENTS, top=2)
    assert "plan" in text and "100.0 s" in text and "ok" in text
    tree = text.split("Span tree")[1].split("Slowest")[0]
    assert tree.index("overpass") < tree.index("elevation") < tree.index("elevation.inner")
    assert "90.0 s" in tree and "90%" in tree                    # elevation is 90 % of the run
    assert "elevation.inner" in tree and "2.2%" not in tree
    slowest = text.split("Slowest")[1].split("HTTP")[0]
    assert slowest.index("elevation") < slowest.index("overpass") and "elevation.inner" not in slowest.split("\n", 3)[3]


def test_report_summarises_http_per_host_and_per_series_with_the_waiting_share():
    text = log_report.report(EVENTS)
    host = next(l for l in text.splitlines() if l.strip().startswith("overpass-api.de"))
    assert "2 requests" in host and "1 failed" in host and "max 2.9" in host
    series = next(l for l in text.splitlines() if l.strip().startswith("elevation") and "wall" in l)
    assert "91 requests" in series and "wall 88.0 s" in series and "sum 40.0 s" in series and "waiting 48.0 s" in series


def test_report_lists_cache_hit_rate_warnings_and_errors():
    text = log_report.report(EVENTS)
    assert "overpass: 1 hit, 1 miss" in text
    assert "overpass_failed" in text and "plugin fire failed" in text


def test_an_unfinished_run_is_reported_not_crashed():
    text = log_report.report(EVENTS[:6])
    assert "unfinished" in text.lower()


def test_load_skips_broken_lines(tmp_path):
    path = tmp_path / "x.log.jsonl"
    path.write_text(json.dumps(EVENTS[0]) + "\n{broken\n\n" + json.dumps(EVENTS[-1]) + "\n", encoding="utf-8")
    assert [e["ev"] for e in log_report.load(path)] == ["run_start", "run_end"]


def test_main_prints_the_report(tmp_path, capsys):
    path = tmp_path / "x.log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in EVENTS), encoding="utf-8")
    assert log_report.main([str(path), "--top", "3"]) == 0
    assert "Span tree" in capsys.readouterr().out
    assert log_report.main([str(tmp_path / "missing.jsonl")]) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_log_report.py -q`
Expected: `No module named 'log_report'`.

- [ ] **Step 3: Implement**

Create `skills/osm-day-route-planning/scripts/log_report.py`:

```python
#!/usr/bin/env python3
"""Text report of a run log (<tool>-<time>.log.jsonl): where did the time go?

    python3 log_report.py routes/<slug>-<date>/plan-20261009T101500.log.jsonl [--top 10]

Sections: run summary, span tree (time and share of the run), slowest spans, HTTP per host and per series
(wall time first-sent -> last-answer, sum of single times, the waiting between requests), cache, warnings and errors.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path) -> list:
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _s(value) -> str:
    return f"{value:.1f} s"


def report(events: list, top: int = 10) -> str:
    start = next((e for e in events if e.get("ev") == "run_start"), {})
    end = next((e for e in reversed(events) if e.get("ev") == "run_end"), None)
    total = end["dur"] if end else max((e.get("t", 0) for e in events), default=0.0)
    out = []
    state = "ok" if end and end.get("ok") else ("FAILED" if end else "unfinished (no run_end: the run was killed or is still going)")
    out.append(f"Run: {start.get('tool', '?')}  total {_s(total)}  {state}")
    if start.get("argv"):
        out.append("argv: " + " ".join(map(str, start["argv"])))

    spans = [e for e in events if e.get("ev") == "span_end"]
    out.append("")
    out.append("Span tree")
    for span in sorted(spans, key=lambda e: e["t"] - e["dur"]):
        depth = span["span"].count(".")
        share = 100 * span["dur"] / total if total else 0
        flag = "" if span.get("ok", True) else f"  FAILED: {span.get('error', '')}"
        out.append(f"{'  ' * (depth + 1)}{span['span']}  {_s(span['dur'])}  {share:.0f}%{flag}")

    out.append("")
    out.append(f"Slowest spans (top {top})")
    leaves = [s for s in spans if not any(o["span"].startswith(s["span"] + ".") for o in spans)]
    for span in sorted(spans, key=lambda e: -e["dur"])[:top]:
        out.append(f"  {span['span']}  {_s(span['dur'])}")
    del leaves

    calls = [e for e in events if e.get("ev") == "http"]
    out.append("")
    out.append("HTTP per host")
    hosts = defaultdict(list)
    for call in calls:
        hosts[call.get("host", "?")].append(call)
    for host, items in sorted(hosts.items(), key=lambda kv: -sum(c["dur"] for c in kv[1])):
        failed = sum(1 for c in items if not c.get("ok", True))
        retries = sum(1 for c in items if c.get("attempt", 1) > 1)
        out.append(f"  {host}  {len(items)} requests, {failed} failed, {retries} retries, total {_s(sum(c['dur'] for c in items))}, "
                   f"max {max(c['dur'] for c in items):.1f} s, {sum(c.get('bytes') or 0 for c in items)} bytes")

    out.append("")
    out.append("HTTP series (wall time first request sent -> last answer)")
    for s in sorted((e for e in events if e.get("ev") == "http_series"), key=lambda e: -e["dur"]):
        waiting = max(0.0, s["dur"] - s["sum_dur"])
        out.append(f"  {s['series']}  {s['n']} requests, {s.get('failed', 0)} failed, wall {_s(s['dur'])}, "
                   f"sum {_s(s['sum_dur'])}, waiting {_s(waiting)}, {s.get('bytes', 0)} bytes")

    cache = defaultdict(lambda: defaultdict(int))
    for e in events:
        if e.get("ev") == "cache":
            cache[e.get("kind", "?")][e.get("result", "?")] += 1
    if cache:
        out.append("")
        out.append("Cache")
        for kind, results in cache.items():
            out.append(f"  {kind}: " + ", ".join(f"{n} {name}" for name, n in sorted(results.items())))

    problems = [e for e in events if e.get("ev") in ("warn", "error")]
    if problems:
        out.append("")
        out.append("Warnings and errors")
        for e in problems:
            extra = f" {e['params']}" if e.get("params") else ""
            out.append(f"  [{e['t']:.1f} s] {e['ev']}: {e.get('msg', '')}{extra}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        events = load(args.log)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(report(events, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Remove the unused `leaves` lines when you implement (they are dead code from drafting): the "Slowest spans" section needs only `sorted(spans, key=...)[:top]`. If the first test's assertions about `elevation.inner` being excluded from the slowest list contradict the simple implementation, relax the test to what the spec requires (top-N by `dur`), not the code.

- [ ] **Step 4: Run to verify pass**

Run: `cd skills/osm-day-route-planning && python3 -m pytest tests/test_log_report.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add skills/osm-day-route-planning/scripts/log_report.py skills/osm-day-route-planning/tests/test_log_report.py
git commit -m "log_report: span tree, slowest spans, HTTP per host and per series, cache, warnings

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Documentation and wiring in the SKILL files

**Files:**
- Modify: `skills/osm-day-route-planning/SKILL.md` (pipeline example ~line 427, "Progress output" ~line 530, Archive section ~line 608)
- Modify: `skills/osm-day-route-day-plan/SKILL.md` (step 4, ~line 100)
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-09-run-log-and-live-status-design.md` (event table: add `note`; API name `RunLog.start`)

**Interfaces:** consumes everything above; produces documentation only. No code besides the SKILL.md pipeline snippet.

- [ ] **Step 1: Planner SKILL.md pipeline snippet**

In the pipeline code block, next to `from progress import Progress` add `from runlog import RunLog`, and replace the `progress = Progress(...)` line with:

```python
route_dir = Path("routes") / f"{slug}-{date}"          # resolved/created BEFORE the first step (pipeline step 2)
log = RunLog.start(route_dir, "plan", argv=sys.argv)   # <route_dir>/plan-<UTC time>.log.jsonl + the live status file
progress = Progress(total_steps=5, lang=user_lang, runlog=log)   # user_lang: the language of the conversation / notes.md
```

and as the last line of the pipeline block `log.close()  # also on failure: wrap the pipeline in `with RunLog.start(...) as log:` if the script can raise`.

- [ ] **Step 2: Planner SKILL.md "Progress output" paragraph**

Replace the sentence "Run the planning script so that its output reaches the user while it works: …" with:

```
**Run log and live progress.** A planning script is always started in the background (`Bash` with
`run_in_background`), because the Bash tool does not stream a running command's output to the user. Two things make the
run visible: (1) the **run log** `routes/<slug>-<date>/plan-<time>.log.jsonl` (every step, every HTTP request with its
send→answer time, every series of requests with first-sent→last-answer time, cache hits, warnings); read it with
`python3 scripts/log_report.py <log>` for a tree of where the time went. (2) The **statusline**: while the script
runs, `scripts/statusline.py` shows `🥾 [3/9] <step> 41/91 · 1:20 · total 4:05` instead of the normal status line and
the normal line returns when the run ends. Setup is the user's decision, one entry in their `settings.json` (offer it,
never write it unasked):
`"statusLine": {"type": "command", "command": "python3 <path to this skill>/scripts/statusline.py --fallback '<their current statusline command>'"}`.
When asked "why was it slow?", run `log_report.py` on the latest log of the route instead of guessing.
```

- [ ] **Step 3: Archive layout**

In the Archive tree add under `<slug>-<date>/`: `plan-<time>.log.jsonl     # run log (log_report.py reads it); the newest 20 per folder are kept`.

- [ ] **Step 4: Day-plan SKILL.md step 4**

After the sentence about progress lines add:

```
   The run also writes `<route_dir>/day-plan-<UTC time>.log.jsonl` (every plugin as a span, every HTTP request with its
   send→answer time, per-plugin series times); `--no-log` switches the log and the live status file off, `--quiet` only
   the stderr lines. Run it in the background and, for "why is it slow", read the log with
   `python3 ../osm-day-route-planning/scripts/log_report.py <log>`. While it runs, the user's statusline (see the
   planning skill) shows the current plugin.
```

- [ ] **Step 5: README and spec**

README: one short paragraph "Run log and live status" naming the log location, `log_report.py` and the statusline setup (same text as Step 2, condensed). Spec: add the `note` row (`{"ev":"note","key":<message key>,"params":{…}}`), say that `warn` events from Progress carry `msg` = message key plus `params`, and use `RunLog.start` wherever the spec names the constructor.

- [ ] **Step 6: Whole suites**

```bash
cd skills/osm-day-route-planning && python3 -m pytest -q
cd ../osm-day-route-day-plan && python3 -m pytest -q
cd ../osm-day-route-show && python3 -m pytest -q
```
Expected: all green. Also confirm no stray files: `git status --short`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: run log, log_report and statusline setup in the SKILL files, README and spec

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** log in route folder (Task 1 `start`, Task 4 CLI, Task 7 docs) · event types incl. `run_start/span/http/http_series/cache/metric/warn/error/run_end` (Task 1) · request timing rule single + series (Task 1; wired in Tasks 3, 4) · log retention 20 per folder (Task 1) · write failures silent (Task 1) · `Progress(runlog=…)` (Task 2) · HTTP wrapper without touching plugins (Task 4 `http.py`) · per-plugin span and series (Task 4) · `--no-log`, `--quiet` keeps the log (Task 4) · status file, rate limit, removal, heartbeat (Task 1) · statusline replace-then-fallback incl. 2 s limit (Task 5) · `log_report.py` (Task 6) · SKILL.md background-run instructions and statusline setup (Task 7) · tests listed in the spec (each task). Out-of-scope items untouched.

**Placeholder scan:** none; the two places that say "adapt the test/double" in Tasks 4 and 6 describe what to do when an existing fixture differs and name the rule (production code stays as specified).

**Type consistency:** `RunLog.start` (not `open`) everywhere; hook names `step_start/step_end/progress_tick/message` identical in Tasks 1, 2; `http_call(url, attempt=1)` / `call.set(status, nbytes, ok, cache)` used the same way in Tasks 3 and 4; series names `overpass`, `elevation`, `public_geometry`, `plugin.<id>` match tests and the report; `status_total` defined in Task 2, used in Task 5; status file fields identical in Task 1 (writer) and Task 5 (reader).
