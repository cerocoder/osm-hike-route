import pytest
from duration import estimate_duration_hours, duration_warning


def test_estimate_duration_flat_route_uses_pace_only():
    hours = estimate_duration_hours(distance_km=10.0, elevation_gain_m=0.0,
                                     pace_kmh=5.0, ascent_minutes_per_100m=10.0)
    assert hours == pytest.approx(2.0)


def test_estimate_duration_adds_ascent_penalty():
    flat = estimate_duration_hours(10.0, 0.0, pace_kmh=5.0, ascent_minutes_per_100m=10.0)
    with_climb = estimate_duration_hours(10.0, 500.0, pace_kmh=5.0, ascent_minutes_per_100m=10.0)

    # 500m of ascent at 10 min/100m = 50 extra minutes = 0.833h
    assert with_climb - flat == pytest.approx(50 / 60, rel=1e-3)


def test_duration_warning_none_when_under_threshold():
    assert duration_warning(estimated_hours=5.0, duration_warning_hours=10.0) is None


def test_duration_warning_present_when_over_threshold():
    message = duration_warning(estimated_hours=13.0, duration_warning_hours=10.0)
    assert message is not None
    assert "световой день" in message


def test_duration_warning_present_even_when_over_24_hours():
    """Spec §3.9: still just a soft warning, never a hard block."""
    message = duration_warning(estimated_hours=30.0, duration_warning_hours=10.0)
    assert message is not None
