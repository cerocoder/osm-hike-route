import json

from tile_providers.cache import cache_key, load_cache, save_entry


_URL = "https://example.org/{z}/{x}/{y}"


def test_cache_key_is_order_independent_for_same_point_set():
    """Two access points passed in either order must hash to the same key —
    otherwise a cache miss on point-order alone defeats the whole cache."""
    k1 = cache_key("cyclosm", [(40.1, -3.1), (40.2, -3.2)], _URL)
    k2 = cache_key("cyclosm", [(40.2, -3.2), (40.1, -3.1)], _URL)
    assert k1 == k2


def test_cache_key_differs_by_provider_and_by_points():
    base = cache_key("cyclosm", [(40.1, -3.1)], _URL)
    assert base != cache_key("ign_es_mtn", [(40.1, -3.1)], _URL)
    assert base != cache_key("cyclosm", [(41.1, -3.1)], _URL)


def test_cache_key_differs_by_url_template():
    """Changing a provider's URL template (e.g. fixing a broken hostname)
    must naturally invalidate any stale cached entry for it."""
    assert cache_key("cyclosm", [(40.1, -3.1)], _URL) != cache_key(
        "cyclosm", [(40.1, -3.1)], "https://example.org/other/{z}/{x}/{y}"
    )


def test_load_cache_returns_empty_dict_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "tile_coverage.json") == {}


def test_load_cache_returns_empty_dict_on_corrupt_json(tmp_path):
    path = tmp_path / "tile_coverage.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_cache(path) == {}


def test_save_entry_then_load_round_trips(tmp_path):
    path = tmp_path / "tile_coverage.json"
    cache = {}
    save_entry(path, cache, "cyclosm|40.1:-3.1", True)

    reloaded = load_cache(path)

    assert reloaded == {"cyclosm|40.1:-3.1": True}


def test_save_entry_preserves_earlier_entries(tmp_path):
    """Review Focus: incremental writes must not lose prior probe results
    if a later probe in the same run fails or the run is interrupted."""
    path = tmp_path / "tile_coverage.json"
    cache = {}
    save_entry(path, cache, "cyclosm|40.1:-3.1", True)
    save_entry(path, cache, "ign_es_mtn|40.1:-3.1", False)

    on_disk = json.loads(path.read_text(encoding="utf-8"))

    assert on_disk == {"cyclosm|40.1:-3.1": True, "ign_es_mtn|40.1:-3.1": False}
