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
    assert any(e["ev"] == "http_series" and e["series"] == "plugin.osm_features" for e in events)
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
