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
import re
import sys
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


_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>)\]]+")


def _scrub_urls(text) -> str:
    """Every URL in a text reduced to scheme://host/path: no query string, fragment or credentials."""
    def one(match):
        url = match.group(0)
        host, path = split_url(url)
        if not host:
            return url.split("://", 1)[0] + "://"
        return f"{url.split('://', 1)[0]}://{host}{path}"
    return _URL_IN_TEXT.sub(one, text)


def _one_line(exc) -> str:
    try:
        return _scrub_urls(" ".join(f"{type(exc).__name__}: {exc}".split()))[:300]
    except Exception:  # noqa: BLE001
        return type(exc).__name__


def _scrub_params(params) -> dict:
    return {k: (_scrub_urls(v) if isinstance(v, str) else v) for k, v in dict(params).items()}


def _prune_status(status_dir, wall, max_age_s=86400.0, dead_age_s=30.0):
    """Best effort: status files of killed runs (older than a day, or a dead pid and a heartbeat older than 30 s)."""
    try:
        now = wall()
        for path in Path(status_dir).glob("*.json"):
            try:
                try:
                    heartbeat = float(json.loads(path.read_text(encoding="utf-8")).get("heartbeat"))
                except Exception:  # noqa: BLE001
                    heartbeat = path.stat().st_mtime
                age = now - heartbeat
                if age > max_age_s or (age > dead_age_s and not _pid_alive(path.stem)):
                    path.unlink()
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


def _pid_alive(stem) -> bool:
    try:
        pid = int(stem)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ValueError, OSError):
        return False


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
        self._ok_explicit = False
        self._finished = False
        self.t_sent = log.now()
        log._activity(self.host, 1 + log._counts["http_ok"] + log._counts["http_failed"], force=True)

    def set(self, status=None, nbytes=None, ok=None, cache=None):
        if isinstance(status, int) and not isinstance(status, bool):
            self.status = status
            if ok is None and not self._ok_explicit:
                self.ok = status < 400
        if isinstance(nbytes, int) and not isinstance(nbytes, bool):
            self.nbytes = nbytes
        if ok is not None:
            self.ok = bool(ok)
            self._ok_explicit = True
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

    @contextlib.contextmanager
    def attempt(self, *args, **kwargs):
        yield

    def snapshot(self):
        return {}

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
        self._attempts = []
        self._counts = {"http_ok": 0, "http_failed": 0, "cache_hit": 0, "cache_miss": 0, "cache_stale": 0}
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
              heartbeat_interval=HEARTBEAT_INTERVAL_S, clock=time.monotonic, wall=time.time, keep=KEEP_LOGS,
              **context):
        fh = None
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
            log = cls(fh, folder / name, tool, clock, wall,
                      default_status_dir() if status_dir is None else status_dir, heartbeat, heartbeat_interval)
            log.event("run_start", tool=tool, argv=list(argv) if argv is not None else None,
                      python=platform.python_version(), platform=platform.platform(), version=LOG_VERSION,
                      started_at=datetime.fromtimestamp(wall(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      **_scrub_params(context))
            _prune(folder, keep, log.path)
            if log._status_path is not None:
                _prune_status(log._status_path.parent, wall)
            if install_as_current:
                install(log)
            return log
        except Exception:  # noqa: BLE001 — "never raises": no log is better than a failed run
            try:
                if fh is not None:
                    fh.close()
            except Exception:  # noqa: BLE001
                pass
            return NullRunLog()

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
        key = f"cache_{result}"
        if key in self._counts:
            self._counts[key] += 1
        self.event("cache", kind=kind, result=result, age_s=age_s)

    def _activity(self, host, requests, force=False):
        """What the status line shows when no Progress step does: the host of the latest request, how many were made,
        how many failed, and (through activity_started) how long ago that was."""
        failed = self._counts["http_failed"]
        text = f"{host} #{requests}" + (f" {failed}✗" if failed else "")
        self._set_status(force=force, activity=text, activity_started=self._safe_wall())

    def snapshot(self) -> dict:
        """Running totals (HTTP answers, cache lookups); the difference of two snapshots is what a span did."""
        return dict(self._counts)

    def warn(self, msg, **fields):
        self.event("warn", msg=msg, **fields)

    def error(self, msg, exc=None):
        msg = _scrub_urls(str(msg))
        tb = ([_scrub_urls(line) for line in traceback.format_exception(type(exc), exc, exc.__traceback__)]
              if exc is not None else None)
        self.event("error", msg=msg, traceback=tb)

    def message(self, level, key, params):
        """A Progress note/warning, keyed by its message key (never the translated text)."""
        if level == "warn":
            self.event("warn", msg=key, params=_scrub_params(params))
        else:
            self.event("note", key=key, params=_scrub_params(params))

    # ---- spans ------------------------------------------------------------------------------------------------------------
    def span_start(self, name, **fields):
        self._spans.append(name)
        path = ".".join(self._spans)
        self.event("span_start", span=path, **fields)
        return (len(self._spans), path, self.now())

    def span_end(self, token, ok=True, error=None, **fields):
        depth, path, t0 = token
        del self._spans[depth - 1:]
        if isinstance(error, str):
            error = _scrub_urls(error)
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
    def attempt(self, n):
        """Calls made inside carry attempt=n (the retry round of a caller that knows it, e.g. the Overpass mirrors)."""
        self._attempts.append(n)
        try:
            yield
        finally:
            if self._attempts:
                self._attempts.pop()

    @contextlib.contextmanager
    def http_call(self, url, attempt=None):
        if attempt is None:
            attempt = self._attempts[-1] if self._attempts else 1
        call = _Call(self, url, attempt)
        try:
            yield call
        except BaseException as exc:
            code = getattr(exc, "code", None)               # urllib's HTTPError: the status of the 4xx/5xx answer
            if isinstance(code, int) and not isinstance(code, bool):
                call.status = code
            call.finish(error=_one_line(exc))
            raise
        else:
            call.finish()

    def _finish_call(self, call):
        t_answer = self.now()
        self._counts["http_ok" if call.ok else "http_failed"] += 1
        self._activity(call.host, self._counts["http_ok"] + self._counts["http_failed"])
        series = self._series[-1].name if self._series else None
        for s in self._series:
            s.add(call.t_sent, t_answer, call.ok, call.nbytes)
        self.event("http", host=call.host, path=call.path, status=call.status, bytes=call.nbytes,
                   attempt=call.attempt, cache=call.cache, t_sent=round(call.t_sent, 3),
                   t_answer=round(t_answer, 3), dur=round(t_answer - call.t_sent, 3), ok=call.ok,
                   error=call.error, series=series)

    def in_series(self) -> bool:
        return bool(self._series)

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
                         step_started=self._safe_wall())

    def _safe_wall(self):
        try:
            return self._wall()
        except Exception:  # noqa: BLE001
            return None

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
            temporary = None
            try:
                now = self._wall()
                if not force and now - self._status_written < STATUS_INTERVAL_S:
                    return
                self._status["heartbeat"] = self._status_written = now
                temporary = self._status_path.with_suffix(f".{threading.get_ident()}.tmp")
                self._status_path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(self._status, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, self._status_path)
            except Exception:  # noqa: BLE001 — the status is decoration: silenced for good
                self._status_path = None
                try:
                    if temporary is not None:
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
        try:
            self.event("run_end", dur=round(self.now(), 3), ok=ok, **fields)
        except Exception:  # noqa: BLE001
            pass
        finally:                                                # cleanup always runs; close never raises
            for cleanup in (self._remove_status, self._close_file, self._uninstall):
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass
            try:
                atexit.unregister(self._atexit)
            except Exception:  # noqa: BLE001
                pass

    def _close_file(self):
        fh, self._fh = self._fh, None
        if fh is not None:
            fh.close()

    def _uninstall(self):
        if current() is self:
            install(None)

    def _atexit(self):
        if getattr(self, "adhoc", False):                       # nobody was going to close it: that is its normal end
            failed = getattr(self, "adhoc_failed", False)
            self.close(ok=not failed, note="adhoc: closed at exit" + (" after an uncaught exception" if failed else ""))
        else:
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


_autostart_tried = False


def ensure_started(cache_dir=None):
    """The safety net for scripts that never called RunLog.start: the first network call of the process starts an
    `adhoc` log. Folder: $OSM_HIKE_ROUTE_DIR (a route folder), else <cache_dir>/../.logs (routes/.logs); with neither
    nothing is started. Once per process; $OSM_HIKE_NO_LOG switches it off. Never raises."""
    global _autostart_tried
    try:
        if _autostart_tried or not isinstance(_current, NullRunLog) or os.environ.get("OSM_HIKE_NO_LOG"):
            return
        route_dir = os.environ.get("OSM_HIKE_ROUTE_DIR")
        if route_dir:
            folder = Path(route_dir)
        elif cache_dir is not None:
            folder = Path(cache_dir).parent / ".logs"
        else:
            return
        _autostart_tried = True
        log = RunLog.start(folder, "adhoc", argv=sys.argv, adhoc=True, cwd=os.getcwd(),
                           script=sys.argv[0] if sys.argv else None,
                           cache_dir=str(cache_dir) if cache_dir is not None else None)
        if isinstance(log, RunLog):
            log.adhoc = True
            previous = sys.excepthook

            def hook(exc_type, exc, tb):                        # an uncaught exception ends the script: the log says so
                try:
                    log.adhoc_failed = True
                    log.error(_one_line(exc), exc)
                except Exception:  # noqa: BLE001
                    pass
                previous(exc_type, exc, tb)
            sys.excepthook = hook
    except Exception:  # noqa: BLE001
        pass


def http_call(url, attempt=None):
    return _current.http_call(url, attempt)


def attempt(n):
    return _current.attempt(n)


def http_series(name):
    return _current.http_series(name)


def in_series():
    return _current.in_series()


def span(name, **fields):
    return _current.span(name, **fields)


def snapshot() -> dict:
    return _current.snapshot() or {}


def event(ev, **fields):
    """A free-form event on the current log; text values have their URLs reduced to scheme://host/path."""
    _current.event(ev, **{k: (_scrub_urls(v) if isinstance(v, str) else v) for k, v in fields.items()})


def cache(kind, result, age_s=None):
    _current.cache(kind, result, age_s)
