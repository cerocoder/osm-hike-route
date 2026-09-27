import pytest
from presets import load_preset, PresetNotFoundError

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
