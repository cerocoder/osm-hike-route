from tile_providers import TileProviderService
from tile_providers.providers.base import TileProviderPlugin


class _FakeProvider(TileProviderPlugin):
    def __init__(self, provider_id, always_available=False, result=True, raises=False):
        self.provider_id = provider_id
        self.always_available = always_available
        self._result = result
        self._raises = raises
        self.call_count = 0

    def covers(self, points, timeout=5.0):
        if self.always_available:
            return True
        self.call_count += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._result


def test_always_available_provider_is_offered_without_probing(tmp_path):
    provider = _FakeProvider("esri_street", always_available=True)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["esri_street"]
    assert provider.call_count == 0


def test_provider_that_covers_is_offered(tmp_path):
    provider = _FakeProvider("cyclosm", result=True)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["cyclosm"]


def test_provider_that_does_not_cover_is_excluded(tmp_path):
    provider = _FakeProvider("ign_es_mtn", result=False)
    service = TileProviderService([provider], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(55.0, 37.0)])  # Moscow — outside Spain

    assert result == []


def test_one_provider_raising_does_not_affect_others(tmp_path):
    """Review Focus: a broken provider must degrade to 'not offered', never
    take down the render or the other providers — same as PlaceInfoService."""
    broken = _FakeProvider("broken", raises=True)
    ok = _FakeProvider("ok", result=True)
    service = TileProviderService([broken, ok], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["ok"]


def test_empty_points_excludes_non_always_available_providers_without_raising(tmp_path):
    """Review Focus: a route with no access/interest points must skip
    probing entirely and still render (only always_available offered)."""
    always = _FakeProvider("esri_street", always_available=True)
    probed = _FakeProvider("cyclosm", result=True)
    service = TileProviderService([always, probed], cache_path=tmp_path / "tile_coverage.json")

    result = service.available_providers([])

    assert [p.provider_id for p in result] == ["esri_street"]
    assert probed.call_count == 0  # covers([]) never even gets to probing


def test_second_call_reuses_cache_and_does_not_reprobe(tmp_path):
    """Review Focus: a second render of the same route must not re-probe
    CyclOSM/IGN over the network."""
    provider = _FakeProvider("cyclosm", result=True)
    cache_path = tmp_path / "tile_coverage.json"

    TileProviderService([provider], cache_path=cache_path).available_providers([(40.0, -3.0)])
    provider.call_count = 0
    second_service = TileProviderService([provider], cache_path=cache_path)
    result = second_service.available_providers([(40.0, -3.0)])

    assert [p.provider_id for p in result] == ["cyclosm"]
    assert provider.call_count == 0
