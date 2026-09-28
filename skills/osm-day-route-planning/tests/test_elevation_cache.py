import json
from elevation.cache import cache_key, load_cache, save_entry


def test_cache_key_rounds_coordinates_consistently():
    key_a = cache_key(55.123456, 37.654321, "srtm90m")
    key_b = cache_key(55.123459, 37.654328, "srtm90m")  # rounds to the same key
    key_c = cache_key(55.999999, 37.654321, "srtm90m")

    assert key_a == key_b
    assert key_a != key_c


def test_load_cache_returns_empty_dict_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "elevation.json") == {}


def test_save_entry_persists_immediately_and_is_reloadable(tmp_path):
    path = tmp_path / "elevation.json"
    cache = load_cache(path)

    save_entry(path, cache, cache_key(55.0, 37.0, "srtm90m"), 55.0, 37.0, 123.4, "open_topo_data", "srtm90m")

    reloaded = load_cache(path)
    key = cache_key(55.0, 37.0, "srtm90m")
    assert reloaded[key] == {
        "lat": 55.0, "lon": 37.0, "elevation": 123.4,
        "provider_id": "open_topo_data", "dataset": "srtm90m",
    }
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert key in on_disk


def test_save_entry_does_not_lose_previously_saved_entries(tmp_path):
    path = tmp_path / "elevation.json"
    cache = load_cache(path)
    save_entry(path, cache, "key-a", 0.0, 0.0, 1.0, "open_topo_data", "srtm90m")

    cache_reloaded = load_cache(path)
    save_entry(path, cache_reloaded, "key-b", 0.0, 0.0, 2.0, "open_meteo", "copernicus_glo90")

    final = load_cache(path)
    assert set(final.keys()) == {"key-a", "key-b"}
