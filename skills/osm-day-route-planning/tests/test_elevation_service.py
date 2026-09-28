from elevation import ElevationService
from elevation.providers.base import ElevationProvider


class _FakeProvider(ElevationProvider):
    def __init__(self, provider_id, max_batch=100, rate_limit_per_sec=100.0, responses=None, fail=False):
        self.provider_id = provider_id
        self.max_batch = max_batch
        self.rate_limit_per_sec = rate_limit_per_sec
        self._responses = responses or {}
        self.fail = fail
        self.calls = []

    def fetch(self, locations):
        self.calls.append(list(locations))
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
