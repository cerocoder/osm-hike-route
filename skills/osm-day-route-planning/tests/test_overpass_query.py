from overpass_query import haversine, build_curated_routes_query, count_curated_routes


def test_haversine_zero_distance_for_identical_points():
    assert haversine(55.75, 37.61, 55.75, 37.61) == 0.0


def test_haversine_known_distance_moscow_spb():
    # Moscow to Saint Petersburg is roughly 635 km great-circle distance.
    km = haversine(55.7558, 37.6173, 59.9343, 30.3351) / 1000
    assert 620 <= km <= 650


def test_build_curated_routes_query_includes_tags_and_radius():
    ql = build_curated_routes_query(55.0, 37.0, radius_m=2000, route_tags=["hiking", "foot"])

    assert "hiking|foot" in ql
    assert "2000" in ql
    assert "relation" in ql


def test_count_curated_routes_counts_relation_elements_only():
    result = {"elements": [
        {"type": "relation", "id": 1}, {"type": "relation", "id": 2}, {"type": "way", "id": 3},
    ]}

    assert count_curated_routes(result) == 2


def test_count_curated_routes_zero_when_no_elements():
    assert count_curated_routes({"elements": []}) == 0
