import pytest
from presets import load_preset, build_weights, PresetNotFoundError

REQUIRED_KEYS = {
    "mode", "routable_highway", "hard_exclude_tags",
    "exclude_highway_without_infra", "blocking_barrier_tags", "buffers_m",
    "preferences", "gradient_threshold_pct", "pace_kmh",
    "ascent_minutes_per_100m", "duration_warning_hours",
}


def test_load_walk_preset_has_all_required_keys():
    preset = load_preset("walk")
    assert REQUIRED_KEYS.issubset(preset.keys())
    assert preset["mode"] == "walk"
    assert "style" not in preset


@pytest.mark.parametrize("style", ["leisure", "sport"])
def test_load_bike_preset_has_all_required_keys(style):
    preset = load_preset("bike", style=style)
    assert REQUIRED_KEYS.issubset(preset.keys())
    assert preset["mode"] == "bike"
    assert preset["style"] == style


def test_bike_without_style_raises():
    with pytest.raises(PresetNotFoundError):
        load_preset("bike")


def test_unknown_mode_raises():
    with pytest.raises(PresetNotFoundError):
        load_preset("ski")


def test_build_weights_merges_preference_overrides_without_mutating_preset():
    preset = load_preset("walk")
    original_prefer_forest = preset["preferences"]["prefer_forest"]

    weights = build_weights(preset, preference_overrides={"prefer_forest": 3.0})

    assert weights["preferences"]["prefer_forest"] == 3.0
    assert weights["preferences"]["avoid_open_field"] == preset["preferences"]["avoid_open_field"]
    assert preset["preferences"]["prefer_forest"] == original_prefer_forest  # preset untouched


def test_build_weights_defaults_budget_to_none():
    weights = build_weights(load_preset("walk"))
    assert weights["max_distance_km"] is None
    assert weights["max_duration_hours"] is None


def test_build_weights_sets_given_budget():
    weights = build_weights(load_preset("walk"), max_distance_km=10.0)
    assert weights["max_distance_km"] == 10.0
    assert weights["max_duration_hours"] is None
