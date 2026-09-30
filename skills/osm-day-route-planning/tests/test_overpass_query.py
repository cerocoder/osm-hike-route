from overpass_query import haversine, build_curated_routes_query, count_curated_routes


def test_haversine_zero_distance_for_identical_points():
    assert haversine(55.75, 37.61, 55.75, 37.61) == 0.0


def test_haversine_known_distance_moscow_spb():
    # Moscow to Saint Petersburg is roughly 635 km great-circle distance.
    km = haversine(55.7558, 37.6173, 59.9343, 30.3351) / 1000
    assert 620 <= km <= 650


def test_build_curated_routes_query_includes_tags_and_radius():
    ql = build_curated_routes_query(55.0, 37.0, radius_m=2000, route_tags=["hiking", "foot"])

    assert "hiking|foot" in ql
    assert "2000" in ql
    assert "relation" in ql
    assert "out count" in ql


def test_count_curated_routes_reads_relations_field_from_count_element():
    result = {"elements": [{"type": "count", "id": 0, "tags": {
        "nodes": "0", "ways": "0", "relations": "2", "areas": "0", "total": "2",
    }}]}
    assert count_curated_routes(result) == 2


def test_count_curated_routes_zero_when_no_elements():
    assert count_curated_routes({"elements": []}) == 0


def test_count_curated_routes_zero_when_count_element_missing():
    assert count_curated_routes({"elements": [{"type": "way", "id": 1}]}) == 0


# ---- the on-disk answer cache and the progress notes ---------------------------------------------------------------------

import json
import os
import time

import pytest

import overpass_query
from overpass_query import query_overpass


class _Response:
    status = 200

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Server:
    """Stands in for urllib.request.urlopen: answers come from a list of payloads or exceptions."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


class _Recorder:
    def __init__(self):
        self.events = []

    def note(self, key, **params):
        self.events.append(("note", key, params))

    def warn(self, key, **params):
        self.events.append(("warn", key, params))


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(overpass_query.time, "sleep", lambda s: None)

    def install(*outcomes):
        fake = _Server(*outcomes)
        monkeypatch.setattr(overpass_query.urllib.request, "urlopen", fake)
        return fake
    return install


def test_without_cache_dir_every_call_asks_the_server(server):
    fake = server({"elements": [1]}, {"elements": [2]})
    assert query_overpass("q") == {"elements": [1]} and query_overpass("q") == {"elements": [2]}
    assert fake.calls == 2


def test_a_fresh_cached_answer_is_returned_without_a_request_and_reported(server, tmp_path):
    fake = server({"elements": [1]})
    recorder = _Recorder()
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [1]}
    assert query_overpass("q", cache_dir=tmp_path, progress=recorder) == {"elements": [1]}
    assert fake.calls == 1 and recorder.events == [("note", "overpass_cache_hit", {"age": 0})]


def test_the_key_is_the_query_text(server, tmp_path):
    fake = server({"elements": [1]}, {"elements": [2]})
    assert query_overpass("around:1500,55.0,37.0", cache_dir=tmp_path) == {"elements": [1]}
    assert query_overpass("around:2000,55.0,37.0", cache_dir=tmp_path) == {"elements": [2]}
    assert fake.calls == 2 and len(list((tmp_path / "overpass").glob("*.json"))) == 2


def test_an_expired_entry_is_fetched_again_and_the_age_is_reported_in_hours(server, tmp_path):
    fake = server({"elements": [1]}, {"elements": [2]})
    query_overpass("q", cache_dir=tmp_path)
    entry = next((tmp_path / "overpass").glob("*.json"))
    three_hours_ago = time.time() - 3 * 3600 - 60
    os.utime(entry, (three_hours_ago, three_hours_ago))
    recorder = _Recorder()
    assert query_overpass("q", cache_dir=tmp_path, progress=recorder) == {"elements": [1]}         # 3 h old: still fresh
    assert recorder.events == [("note", "overpass_cache_hit", {"age": 3})]
    two_days_ago = time.time() - 48 * 3600
    os.utime(entry, (two_days_ago, two_days_ago))
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2


def test_refresh_skips_the_read_but_updates_the_entry(server, tmp_path):
    fake = server({"elements": [1]}, {"elements": [2]})
    query_overpass("q", cache_dir=tmp_path)
    assert query_overpass("q", cache_dir=tmp_path, refresh=True) == {"elements": [2]}
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2


def test_a_malformed_entry_is_ignored_not_an_error(server, tmp_path):
    fake = server({"elements": [1]}, {"elements": [2]})
    query_overpass("q", cache_dir=tmp_path)
    next((tmp_path / "overpass").glob("*.json")).write_text("{broken", encoding="utf-8")
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2


def test_old_entries_are_pruned_when_a_new_one_is_written(server, tmp_path):
    server({"elements": [1]}, {"elements": [2]})
    query_overpass("old", cache_dir=tmp_path)
    old = next((tmp_path / "overpass").glob("*.json"))
    ten_days_ago = time.time() - 10 * 24 * 3600
    os.utime(old, (ten_days_ago, ten_days_ago))
    query_overpass("new", cache_dir=tmp_path)
    assert not old.exists() and len(list((tmp_path / "overpass").glob("*.json"))) == 1
    assert not list((tmp_path / "overpass").glob("*.tmp"))


def test_an_unwritable_cache_never_fails_the_query(server, tmp_path):
    server({"elements": [1]})
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    assert query_overpass("q", cache_dir=blocker) == {"elements": [1]}


def test_failures_and_retries_are_reported(server):
    server(OSError("HTTP Error 504: Gateway Timeout"), {"elements": [3]})
    recorder = _Recorder()
    assert query_overpass("q", progress=recorder) == {"elements": [3]}
    assert recorder.events == [
        ("warn", "overpass_failed", {"endpoint": "overpass-api.de", "reason": "HTTP Error 504: Gateway Timeout"}),
        ("note", "overpass_attempt", {"endpoint": "overpass-api.de", "n": 2, "m": 2})]


def test_all_endpoints_failing_still_raises(server):
    server(*[OSError("down")] * 4)
    with pytest.raises(RuntimeError, match="failed on all endpoints"):
        query_overpass("q")


def test_a_cache_file_from_the_future_is_not_fresh(server, tmp_path):
    fake = server({"elements": [1]}, {"elements": [2]})
    query_overpass("q", cache_dir=tmp_path)
    entry = next((tmp_path / "overpass").glob("*.json"))
    tomorrow = time.time() + 24 * 3600
    os.utime(entry, (tomorrow, tomorrow))
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2


@pytest.mark.parametrize("content", ["null", "[]", "42", '"text"'])
def test_a_cache_entry_that_is_not_an_object_is_ignored(server, tmp_path, content):
    fake = server({"elements": [1]}, {"elements": [2]})
    query_overpass("q", cache_dir=tmp_path)
    next((tmp_path / "overpass").glob("*.json")).write_text(content, encoding="utf-8")
    assert query_overpass("q", cache_dir=tmp_path) == {"elements": [2]} and fake.calls == 2


def test_orphaned_temporary_files_are_pruned(server, tmp_path):
    server({"elements": [1]})
    folder = tmp_path / "overpass"
    folder.mkdir()
    orphan = folder / "crashed.tmp"
    orphan.write_text("partial", encoding="utf-8")
    ten_days_ago = time.time() - 10 * 24 * 3600
    os.utime(orphan, (ten_days_ago, ten_days_ago))
    query_overpass("a", cache_dir=tmp_path)
    assert not orphan.exists() and not list(folder.glob("*.tmp"))
