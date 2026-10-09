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
    clock.advance(1.1)
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


# ---- review fixes -----------------------------------------------------------------------------------------------------------

def test_urls_in_error_texts_lose_query_fragment_and_credentials(make_log):
    log = make_log()
    with pytest.raises(OSError):
        with log.span("s"):
            with log.http_call("https://h.example/p"):
                raise OSError("failed GET https://u:p@h.example/p?key=SECRET#f (timeout)")
    text = Path(log.path).read_text(encoding="utf-8")
    assert "SECRET" not in text and "u:p" not in text
    evs = events(log)
    assert [e for e in evs if e["ev"] == "http"][0]["error"] == "OSError: failed GET https://h.example/p (timeout)"
    assert [e for e in evs if e["ev"] == "span_end"][0]["error"].startswith("OSError: failed GET https://h.example/p")


def test_status_failures_of_any_kind_silence_the_status_without_raising(make_log, tmp_path):
    log = make_log()
    log.step_start("a", "A", 1, 1, "en")
    log._status["bad"] = object()                               # json.dumps raises TypeError
    log.progress_tick(1, 2, "k")
    log._set_status(force=True)
    assert log._status_path is None
    log.event("metric", name="x", value=1)                      # still logging

    def broken_wall():
        raise ValueError("clock")
    log2 = make_log()
    log2._wall = broken_wall
    log2.step_start("a", "A", 1, 1, "en")
    assert log2._status_path is None


def test_close_cleans_up_even_if_the_run_end_event_raises(make_log, tmp_path):
    log = make_log()
    log.step_start("a", "A", 1, 1, "en")
    runlog.install(log)
    assert list((tmp_path / "status").glob("*.json"))
    fh = log._fh

    def boom(*args, **kwargs):
        raise RuntimeError("event failed")
    log.event = boom
    log.close()
    assert not list((tmp_path / "status").glob("*.json"))
    assert fh.closed and log._fh is None
    assert isinstance(runlog.current(), NullRunLog)


def test_start_never_raises_and_does_not_leak_the_handle(tmp_path, monkeypatch):
    opened = []
    real_open = open

    def tracking_open(*args, **kwargs):
        fh = real_open(*args, **kwargs)
        opened.append(fh)
        return fh

    def broken():
        raise RuntimeError("no home")
    monkeypatch.setattr("builtins.open", tracking_open)
    monkeypatch.setattr(runlog, "default_status_dir", broken)
    log = RunLog.start(tmp_path / "r", "plan", heartbeat=False, install_as_current=False)
    assert isinstance(log, NullRunLog)
    assert opened and all(fh.closed for fh in opened)


def test_a_later_status_overrides_an_earlier_error_status_unless_ok_was_explicit(make_log):
    log = make_log()
    with log.http_call("https://h.example/p") as call:
        call.set(status=503)
        call.set(status=200)
    with log.http_call("https://h.example/p") as call:
        call.set(ok=False)
        call.set(status=200)
    first, second = [e for e in events(log) if e["ev"] == "http"]
    assert first["ok"] is True and second["ok"] is False


def test_in_series_is_true_only_inside_a_series(make_log):
    log = make_log()
    assert not log.in_series()
    with log.http_series("s"):
        assert log.in_series()
    assert not log.in_series()
    assert not NullRunLog().in_series()


def test_error_tracebacks_and_failed_runs_do_not_leak_url_keys(make_log, tmp_path, clock):
    log = make_log()
    try:
        raise RuntimeError("failed https://h.example/p?key=SECRET now")
    except RuntimeError as exc:
        log.error("boom", exc)
    log.close()
    assert "SECRET" not in Path(log.path).read_text(encoding="utf-8")
    with pytest.raises(RuntimeError):
        with RunLog.start(tmp_path / "r2", "plan", clock=clock, heartbeat=False, status_dir=tmp_path / "s2") as run:
            path = run.path
            raise RuntimeError("https://h.example/p?key=SECRET")
    assert "SECRET" not in Path(path).read_text(encoding="utf-8")


def test_http_error_code_becomes_the_status(make_log):
    import urllib.error
    log = make_log()
    with pytest.raises(urllib.error.HTTPError):
        with log.http_call("https://h.example/p?key=SECRET"):
            raise urllib.error.HTTPError("https://h.example/p?key=SECRET", 503, "x", {}, None)
    log.close()
    e = next(x for x in events(log) if x["ev"] == "http")
    assert e["status"] == 503 and e["ok"] is False


def test_urls_are_scrubbed_in_span_errors_error_messages_and_message_params(make_log):
    log = make_log()
    url = "https://h.example/p?key=SECRET"
    with pytest.raises(RuntimeError):
        with log.span("s"):
            raise RuntimeError(url)
    token = log.span_start("t")
    log.span_end(token, ok=False, error=f"failed {url}")
    log.error(f"bad {url}")
    log.message("warn", "k", {"endpoint": url, "n": 3})
    log.message("note", "k2", {"endpoint": url})
    log.close()
    text = Path(log.path).read_text(encoding="utf-8")
    assert "SECRET" not in text and "https://h.example/p" in text


def test_start_removes_stale_status_files_but_keeps_a_live_fresh_one(tmp_path):
    status = tmp_path / "status"
    status.mkdir()
    now = 1_700_000_000.0
    stale_day = status / "999999.json"
    stale_day.write_text(json.dumps({"heartbeat": now - 2 * 86400}))
    dead = status / "2147483646.json"
    dead.write_text(json.dumps({"heartbeat": now - 120}))
    fresh = status / f"{os.getppid()}.json"            # a live pid, fresh heartbeat
    fresh.write_text(json.dumps({"heartbeat": now - 5}))
    log = RunLog.start(tmp_path / "route", "plan", status_dir=status, heartbeat=False, install_as_current=False,
                       wall=lambda: now)
    log.close()
    assert not stale_day.exists() and not dead.exists() and fresh.exists()


# ---- adhoc log, activity ---------------------------------------------------------------------------------------------------
def _fresh_autostart(monkeypatch, tmp_path, **env):
    monkeypatch.delenv("OSM_HIKE_NO_LOG", raising=False)
    monkeypatch.delenv("OSM_HIKE_ROUTE_DIR", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(runlog, "_autostart_tried", False)
    runlog.install(None)


def test_ensure_started_logs_next_to_the_cache_dir_and_says_what_the_script_was(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path)
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    log = runlog.current()
    assert isinstance(log, RunLog) and log.path.parent == tmp_path / "routes" / ".logs"
    with runlog.http_call("https://h.example/p?key=SECRET") as call:
        call.set(status=200)
    log.close()
    events = [json.loads(x) for x in log.path.read_text().splitlines()]
    assert events[0]["tool"] == "adhoc" and events[0]["adhoc"] is True and events[0]["cwd"] and events[0]["script"]
    assert events[-1]["ev"] == "run_end" and "SECRET" not in log.path.read_text()


def test_ensure_started_prefers_the_route_dir_from_the_environment(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path, OSM_HIKE_ROUTE_DIR=tmp_path / "my-route")
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    assert runlog.current().path.parent == tmp_path / "my-route"
    runlog.current().close()


def test_ensure_started_does_nothing_without_a_folder_when_switched_off_or_when_a_log_exists(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path)
    runlog.ensure_started(None)
    assert isinstance(runlog.current(), NullRunLog)
    _fresh_autostart(monkeypatch, tmp_path, OSM_HIKE_NO_LOG="1")
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    assert isinstance(runlog.current(), NullRunLog) and not (tmp_path / "routes").exists()
    _fresh_autostart(monkeypatch, tmp_path)
    own = RunLog.start(tmp_path / "own", "plan", heartbeat=False, status_dir=tmp_path / "s")
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    assert runlog.current() is own and not (tmp_path / "routes").exists()
    own.close()


def test_ensure_started_tries_once_per_process(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path)
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    runlog.current().close()
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    assert isinstance(runlog.current(), NullRunLog)


def test_an_adhoc_log_is_closed_ok_at_exit(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path)
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    log = runlog.current()
    log._atexit()
    end = json.loads(log.path.read_text().splitlines()[-1])
    assert end["ev"] == "run_end" and end["ok"] is True and "adhoc" in end["note"]


def test_the_status_shows_the_latest_request_host_count_and_failures(tmp_path):
    log = RunLog.start(tmp_path, "adhoc", heartbeat=False, status_dir=tmp_path / "s")
    with pytest.raises(RuntimeError):
        with log.http_call("https://a.example/x"):
            raise RuntimeError("boom")
    with log.http_call("https://b.example/y"):
        status = json.loads(next((tmp_path / "s").glob("*.json")).read_text())      # in flight: request 2
        assert status["activity"] == "b.example #2 1✗" and status["activity_started"]
    log.close()


def test_start_puts_extra_context_into_run_start(tmp_path):
    log = RunLog.start(tmp_path, "t", heartbeat=False, status_dir=tmp_path / "s", note="x https://h/p?k=SECRET")
    log.close()
    assert "SECRET" not in log.path.read_text() and '"note":"x https://h/p"' in log.path.read_text()


def test_an_uncaught_exception_makes_the_adhoc_run_not_ok(monkeypatch, tmp_path):
    _fresh_autostart(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.excepthook", lambda *a: None)       # restored by monkeypatch; ensure_started wraps it
    runlog.ensure_started(tmp_path / "routes" / ".cache")
    log = runlog.current()
    import sys
    try:
        raise RuntimeError("tile failed")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    log._atexit()
    events = [json.loads(x) for x in log.path.read_text().splitlines()]
    assert any(e["ev"] == "error" and "tile failed" in e["msg"] for e in events)
    assert events[-1]["ok"] is False and "uncaught" in events[-1]["note"]
