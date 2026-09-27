import json
from weights_io import save_weights, load_weights


def test_load_weights_returns_none_when_file_missing(tmp_path):
    assert load_weights(tmp_path) is None


def test_save_then_load_round_trips(tmp_path):
    weights = {"mode": "walk", "preferences": {"prefer_forest": 1.5}, "max_distance_km": None}

    save_weights(tmp_path, weights)
    loaded = load_weights(tmp_path)

    assert loaded == weights
    assert json.loads((tmp_path / "weights.json").read_text(encoding="utf-8")) == weights


def test_save_weights_creates_route_dir_if_missing(tmp_path):
    route_dir = tmp_path / "encinar-de-boadilla-2026-09-28"
    save_weights(route_dir, {"mode": "walk"})
    assert (route_dir / "weights.json").exists()
