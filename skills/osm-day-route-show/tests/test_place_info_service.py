from place_info import PlaceInfoService
from place_info.providers.base import PlaceInfoProvider, PlaceInfoResult


class _FakeProvider(PlaceInfoProvider):
    def __init__(self, provider_id, result=None, raises=False):
        self.provider_id = provider_id
        self._result = result
        self._raises = raises
        self.call_count = 0

    def fetch(self, names, lat, lon, wikidata_qid):
        self.call_count += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._result


def test_fetch_all_returns_results_from_every_provider_that_found_something(tmp_path):
    p1 = _FakeProvider("p1", result=PlaceInfoResult(provider_id="p1", summary="A"))
    p2 = _FakeProvider("p2", result=None)
    p3 = _FakeProvider("p3", result=PlaceInfoResult(provider_id="p3", url="https://example.org"))
    service = PlaceInfoService([p1, p2, p3], cache_path=tmp_path / "place_info.json")

    results = service.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/1")

    assert [r.provider_id for r in results] == ["p1", "p3"]


def test_fetch_all_survives_a_single_provider_raising(tmp_path):
    """Review Focus #5: one plugin's bug must not take down the others."""
    ok_provider = _FakeProvider("ok", result=PlaceInfoResult(provider_id="ok", summary="fine"))
    broken_provider = _FakeProvider("broken", raises=True)
    service = PlaceInfoService([broken_provider, ok_provider], cache_path=tmp_path / "place_info.json")

    results = service.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/2")

    assert [r.provider_id for r in results] == ["ok"]


def test_fetch_all_uses_cache_on_second_call(tmp_path):
    provider = _FakeProvider("p1", result=PlaceInfoResult(provider_id="p1", summary="cached"))
    cache_path = tmp_path / "place_info.json"

    PlaceInfoService([provider], cache_path=cache_path).fetch_all(
        {"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/3")
    provider.call_count = 0
    second = PlaceInfoService([provider], cache_path=cache_path)
    results = second.fetch_all({"ru": "Точка"}, 55.0, 37.0, wikidata_qid=None, identity="node/3")

    assert results[0].summary == "cached"
    assert provider.call_count == 0
