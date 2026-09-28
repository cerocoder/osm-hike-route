import pytest
from elevation.resample import cumulative_distances, sample_positions, interpolate_at_distances


def test_cumulative_distances_starts_at_zero_and_is_nondecreasing():
    coords = [(55.0, 37.0), (55.001, 37.0), (55.002, 37.0)]
    dists = cumulative_distances(coords)

    assert dists[0] == 0.0
    assert dists[1] < dists[2]


def test_sample_positions_always_includes_start_and_end():
    coords = [(55.0, 37.0), (55.01, 37.0)]  # roughly 1.1 km

    samples = sample_positions(coords, interval_m=150.0)

    assert samples[0][2] == pytest.approx(0.0)
    total = cumulative_distances(coords)[-1]
    assert samples[-1][2] == pytest.approx(total)


def test_sample_positions_spacing_is_close_to_requested_interval():
    coords = [(55.0, 37.0), (55.01, 37.0)]

    samples = sample_positions(coords, interval_m=150.0)
    gaps = [b[2] - a[2] for a, b in zip(samples, samples[1:])]

    assert all(gap <= 200.0 for gap in gaps)  # generous tolerance around 150m


def test_interpolate_at_distances_is_linear_between_samples():
    sample_dists = [0.0, 100.0, 200.0]
    sample_elevations = [10.0, 20.0, 10.0]

    result = interpolate_at_distances(sample_dists, sample_elevations, [0.0, 50.0, 100.0, 150.0, 200.0])

    assert result == pytest.approx([10.0, 15.0, 20.0, 15.0, 10.0])


def test_interpolate_clamps_targets_outside_sample_range():
    result = interpolate_at_distances([0.0, 100.0], [5.0, 15.0], [-10.0, 110.0])
    assert result == pytest.approx([5.0, 15.0])
