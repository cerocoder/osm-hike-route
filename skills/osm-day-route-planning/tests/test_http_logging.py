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
    assert all(c["series"] == "overpass" and c["host"] == "overpass-api.de" for c in calls)
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


def test_the_overpass_backoff_after_an_error_body_is_not_part_of_the_call(log, monkeypatch):
    def fake_sleep(s):
        log.clock.t += s
    class _Body(_Response):
        def read(self):
            return b"<html>runtime error: timeout</html>"
    answers = [_Body({}), _Response({"elements": []})]
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: answers.pop(0))
    monkeypatch.setattr(overpass_query.time, "sleep", fake_sleep)
    overpass_query.query_overpass("QL")
    first = next(e for e in events(log) if e["ev"] == "http")
    assert first["ok"] is False and first["dur"] == 0
    assert log.clock.t == 2


def test_query_overpass_logs_what_the_query_asked_and_what_came_back(log, monkeypatch):
    answers = [_Response({}, status=504), _Response({"elements": [1, 2, 3]})]
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: answers.pop(0))
    monkeypatch.setattr(overpass_query.time, "sleep", lambda s: None)
    ql = "[out:json][timeout:25];way(around:6000,57.0,60.0);out;"
    overpass_query.query_overpass(ql)
    query = next(e for e in events(log) if e["ev"] == "overpass")
    assert query["ok"] is True and query["elements"] == 3 and query["tries"] == 2
    assert query["timeout_s"] == 25 and query["radius_m"] == 6000 and query["ql_bytes"] == len(ql)


def test_a_failed_query_is_logged_with_its_size(log, monkeypatch):
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: _Response({}, status=500))
    monkeypatch.setattr(overpass_query.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        overpass_query.query_overpass("[out:json];node(1);out;", retries=1)
    query = next(e for e in events(log) if e["ev"] == "overpass")
    assert query["ok"] is False and query["tries"] == len(overpass_query.ENDPOINTS) and "500" in query["error"]


def test_a_script_without_a_log_gets_an_adhoc_one_from_the_overpass_layer(tmp_path, monkeypatch):
    monkeypatch.delenv("OSM_HIKE_NO_LOG", raising=False)
    monkeypatch.setattr(runlog, "_autostart_tried", False)
    runlog.install(None)
    monkeypatch.setattr(overpass_query.urllib.request, "urlopen", lambda req, timeout=None: _Response({"elements": []}))
    overpass_query.query_overpass("[out:json];node(1);out;", cache_dir=tmp_path / "routes" / ".cache")
    log = runlog.current()
    assert isinstance(log, RunLog) and log.path.parent == tmp_path / "routes" / ".logs"
    log.close()
    assert any(json.loads(l)["ev"] == "overpass" for l in log.path.read_text().splitlines())


def test_a_script_without_a_log_gets_an_adhoc_one_from_the_elevation_layer(tmp_path, monkeypatch):
    monkeypatch.delenv("OSM_HIKE_NO_LOG", raising=False)
    monkeypatch.setattr(runlog, "_autostart_tried", False)
    runlog.install(None)
    ElevationService([], cache_path=tmp_path / "routes" / ".cache" / "elevation.json").get_elevations([(1.0, 2.0)])
    log = runlog.current()
    assert isinstance(log, RunLog) and log.path.parent == tmp_path / "routes" / ".logs"
    log.close()
