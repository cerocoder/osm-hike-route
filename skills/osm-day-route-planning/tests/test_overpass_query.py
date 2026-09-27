from overpass_query import haversine


def test_haversine_zero_distance_for_identical_points():
    assert haversine(55.75, 37.61, 55.75, 37.61) == 0.0


def test_haversine_known_distance_moscow_spb():
    # Moscow to Saint Petersburg is roughly 635 km great-circle distance.
    km = haversine(55.7558, 37.6173, 59.9343, 30.3351) / 1000
    assert 620 <= km <= 650
