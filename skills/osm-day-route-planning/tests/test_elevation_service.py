from unittest.mock import patch
from elevation import ElevationService
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
