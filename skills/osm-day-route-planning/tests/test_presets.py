import copy

import pytest
from presets import (load_preset, build_weights, revise_weights, PresetNotFoundError,
                     resolve_length_range, LengthRequiredError)

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


def test_revise_weights_changes_only_named_top_level_fields():
    existing = build_weights(load_preset("bike", style="leisure"), max_distance_km=12.0)

    revised = revise_weights(existing, {"max_distance_km": 18.0})

    assert revised["max_distance_km"] == 18.0
    assert revised["max_duration_hours"] == existing["max_duration_hours"]
    assert revised["mode"] == "bike"
    assert revised["style"] == "leisure"
    assert revised["preferences"] == existing["preferences"]


def test_revise_weights_merges_preferences_key_instead_of_replacing():
    existing = build_weights(load_preset("walk"))

    revised = revise_weights(existing, {"preferences": {"avoid_near_water": 5.0}})

    assert revised["preferences"]["avoid_near_water"] == 5.0
    # Untouched preference keys survive the partial preferences update.
    assert revised["preferences"]["prefer_forest"] == existing["preferences"]["prefer_forest"]


def test_revise_weights_does_not_mutate_existing_argument():
    existing = build_weights(load_preset("walk"))
    frozen_copy = copy.deepcopy(existing)

    revise_weights(existing, {"max_distance_km": 5.0})

    assert existing == frozen_copy


@pytest.mark.parametrize("style", ["leisure", "sport"])
def test_bike_presets_allow_the_extra_highway_types(style):
    preset = load_preset("bike", style=style)
    for value in ("tertiary", "unclassified", "service", "road", "steps", "corridor",
                  "footway", "pedestrian", "bridleway"):
        assert value in preset["routable_highway"], value
    assert "steps" not in preset["hard_exclude_tags"].get("highway", [])
    assert set(preset["fallback_highway"]) == {"service", "road"}
    assert set(preset["bicycle_explicit_highway"]) == {"footway", "pedestrian"}
    assert preset["preferences"]["fallback_way_cost"] >= 100
    assert preset["preferences"]["steps_cost"] > 1


def test_walk_preset_allows_bridleway():
    assert "bridleway" in load_preset("walk")["routable_highway"]


def test_only_a_maximum_gives_half_of_it_as_the_minimum():
    r = resolve_length_range(max_km=30)
    assert (r["min_distance_km"], r["max_distance_km"]) == (15, 30)
    assert r["min_duration_hours"] is None and r["max_duration_hours"] is None


def test_only_a_time_gives_half_of_it_as_the_minimum():
    r = resolve_length_range(max_h=4)
    assert (r["min_duration_hours"], r["max_duration_hours"]) == (2, 4)
    assert r["min_distance_km"] is None


def test_explicit_minimum_is_kept():
    assert resolve_length_range(min_km=10, max_km=30)["min_distance_km"] == 10


def test_no_length_raises():
    with pytest.raises(LengthRequiredError):
        resolve_length_range()


def test_a_minimum_without_a_maximum_raises():
    with pytest.raises(LengthRequiredError):
        resolve_length_range(min_km=10)


def test_minimum_above_maximum_raises_value_error():
    with pytest.raises(ValueError):
        resolve_length_range(min_km=40, max_km=30)


def test_build_weights_stores_the_minimums():
    w = build_weights(load_preset("walk"), max_distance_km=30, min_distance_km=15)
    assert w["min_distance_km"] == 15 and w["min_duration_hours"] is None
