from pathlib import Path
from unittest.mock import patch

import elevation
from elevation import ElevationService
from elevation.cache import load_cache, cache_key
from elevation.providers.base import ElevationProvider


class _FakeProvider(ElevationProvider):
    def __init__(self, provider_id, max_batch=100, rate_limit_per_sec=100.0, responses=None, fail=False, raise_error=False):
        self.provider_id = provider_id
        self.max_batch = max_batch
        self.rate_limit_per_sec = rate_limit_per_sec
        self._responses = responses or {}
        self.fail = fail
        self.raise_error = raise_error
        self.calls = []

    def fetch(self, locations):
        self.calls.append(list(locations))
        if self.raise_error:
            raise RuntimeError(f"Provider {self.provider_id} failed")
        if self.fail:
            return [None] * len(locations)
        return [self._responses.get(loc) for loc in locations]


def test_get_elevations_returns_values_from_first_working_provider(tmp_path):
    provider = _FakeProvider("p1", responses={(55.0, 37.0): 100.0})
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [100.0]


def test_get_elevations_fails_over_to_next_provider_for_unresolved_points(tmp_path):
    failing = _FakeProvider("p1", fail=True)
    working = _FakeProvider("p2", responses={(55.0, 37.0): 200.0})
    service = ElevationService([failing, working], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [200.0]
    assert working.calls == [[(55.0, 37.0)]]


def test_get_elevations_returns_none_when_all_providers_fail(tmp_path):
    """Review Focus #2: no crash, no exception — just None for that point."""
    service = ElevationService(
        [_FakeProvider("p1", fail=True), _FakeProvider("p2", fail=True)],
        cache_path=tmp_path / "elevation.json",
    )

    result = service.get_elevations([(55.0, 37.0), (56.0, 38.0)])

    assert result == [None, None]


def test_get_elevations_uses_cache_and_does_not_call_provider_again(tmp_path):
    provider = _FakeProvider("p1", responses={(55.0, 37.0): 100.0})
    cache_path = tmp_path / "elevation.json"

    ElevationService([provider], cache_path=cache_path).get_elevations([(55.0, 37.0)])
    provider.calls.clear()
    second_service = ElevationService([provider], cache_path=cache_path)
    result = second_service.get_elevations([(55.0, 37.0)])

    assert result == [100.0]
    assert provider.calls == []


def test_get_elevations_splits_requests_into_max_batch_chunks(tmp_path):
    provider = _FakeProvider("p1", max_batch=2, responses={
        (1.0, 1.0): 1.0, (2.0, 2.0): 2.0, (3.0, 3.0): 3.0,
    })
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)])

    assert result == [1.0, 2.0, 3.0]
    assert len(provider.calls) == 2
    assert len(provider.calls[0]) == 2
    assert len(provider.calls[1]) == 1


def test_get_elevations_handles_provider_exception_and_fails_over(tmp_path):
    """Provider exception treated as batch failure (all None); fail over to next provider."""
    raising = _FakeProvider("p1", raise_error=True)
    working = _FakeProvider("p2", responses={(55.0, 37.0): 200.0})
    service = ElevationService([raising, working], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [200.0]
    assert raising.calls == [[(55.0, 37.0)]]
    assert working.calls == [[(55.0, 37.0)]]


def test_get_elevations_does_not_crash_when_last_provider_raises(tmp_path):
    """Last provider raises exception — returns None, no crash."""
    raising = _FakeProvider("p1", raise_error=True)
    service = ElevationService([raising], cache_path=tmp_path / "elevation.json")

    result = service.get_elevations([(55.0, 37.0)])

    assert result == [None]


def test_respect_rate_limit_tracks_per_provider_id_independently(tmp_path):
    """Two different providers, each called once, must not rate-limit each
    other — only repeat calls to the SAME provider_id should trigger a
    sleep. This is the one behavior that distinguishes correct per-provider
    scoping from an (incorrect) single global rate limiter."""
    service = ElevationService([], cache_path=tmp_path / "elevation.json")
    provider_a = _FakeProvider("a", rate_limit_per_sec=1.0)
    provider_b = _FakeProvider("b", rate_limit_per_sec=1.0)

    with patch("time.sleep") as mock_sleep:
        service._respect_rate_limit(provider_a)  # first call ever for 'a'
        service._respect_rate_limit(provider_b)  # first call ever for 'b' — different id, must not sleep
    mock_sleep.assert_not_called()

    with patch("time.sleep") as mock_sleep_again:
        service._respect_rate_limit(provider_a)  # second call for 'a' — must sleep ~1.0s now
    mock_sleep_again.assert_called_once()
    assert abs(mock_sleep_again.call_args[0][0] - 1.0) < 0.1


_FIVE_POINTS = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0), (5.0, 5.0)]


def test_get_elevations_writes_cache_file_once_per_batch_not_per_point(tmp_path):
    """Behavioural guard for the O(n) whole-file-rewrite-per-point bug:
    5 points in batches of 2 -> 3 batches -> 3 disk writes, not 5."""
    provider = _FakeProvider("p1", max_batch=2,
                             responses={loc: float(i) for i, loc in enumerate(_FIVE_POINTS)})
    cache_path = tmp_path / "elevation.json"
    service = ElevationService([provider], cache_path=cache_path)
    original_write_text = Path.write_text

    with patch.object(Path, "write_text", autospec=True,
                      side_effect=original_write_text) as mock_write_text:
        result = service.get_elevations(_FIVE_POINTS)

    assert result == [0.0, 1.0, 2.0, 3.0, 4.0]
    cache_writes = [c for c in mock_write_text.call_args_list if Path(c.args[0]) == cache_path]
    assert len(cache_writes) == 3


def test_get_elevations_calls_write_cache_once_per_batch_and_loses_nothing(tmp_path):
    provider = _FakeProvider("p1", max_batch=2,
                             responses={loc: float(i) for i, loc in enumerate(_FIVE_POINTS)})
    cache_path = tmp_path / "elevation.json"
    service = ElevationService([provider], cache_path=cache_path)

    with patch("elevation.write_cache", wraps=elevation.cache.write_cache) as mock_write:
        service.get_elevations(_FIVE_POINTS)

    assert mock_write.call_count == 3
    on_disk = load_cache(cache_path)
    for i, (lat, lon) in enumerate(_FIVE_POINTS):
        entry = on_disk[cache_key(lat, lon, "srtm90m")]
        assert entry["elevation"] == float(i)
        assert entry["provider_id"] == "p1"


def test_get_elevations_does_not_write_cache_for_batch_that_resolved_nothing(tmp_path):
    service = ElevationService([_FakeProvider("p1", max_batch=2, fail=True)],
                               cache_path=tmp_path / "elevation.json")

    with patch("elevation.write_cache", wraps=elevation.cache.write_cache) as mock_write:
        result = service.get_elevations(_FIVE_POINTS)

    assert result == [None] * 5
    mock_write.assert_not_called()
    assert not (tmp_path / "elevation.json").exists()


class _Recorder:
    def __init__(self):
        self.ticks = []

    def tick(self, done, total, key="tag_progress", **params):
        self.ticks.append((done, total, key))


def test_get_elevations_ticks_once_per_batch_and_remembers_the_cache_share(tmp_path):
    points = [(55.0 + i * 0.001, 37.0) for i in range(5)]
    provider = _FakeProvider("p1", max_batch=2, responses={p: 100.0 + i for i, p in enumerate(points)})
    service = ElevationService([provider], cache_path=tmp_path / "elevation.json")
    recorder = _Recorder()

    service.get_elevations(points[:1], progress=recorder)                      # one point goes to the cache
    recorder = _Recorder()
    service.get_elevations(points, progress=recorder)

    assert recorder.ticks == [(1, 2, "elevation_batch"), (2, 2, "elevation_batch")]     # 4 pending points, 2 per batch
    assert service.last_request == {"points": 5, "cached": 1}


def test_the_tick_total_grows_when_a_failover_needs_more_requests(tmp_path):
    points = [(55.0 + i * 0.001, 37.0) for i in range(4)]
    failing = _FakeProvider("p1", max_batch=4, fail=True)
    working = _FakeProvider("p2", max_batch=2, responses={p: 1.0 for p in points})
    service = ElevationService([failing, working], cache_path=tmp_path / "elevation.json")
    recorder = _Recorder()

    service.get_elevations(points, progress=recorder)

    assert recorder.ticks == [(1, 1, "elevation_batch"), (2, 2, "elevation_batch"), (3, 3, "elevation_batch")]
