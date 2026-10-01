from route_output import build_geojson


def _sample_call(**overrides):
    kwargs = dict(
        path_coords=[(37.0, 55.0, 100.0), (37.001, 55.001, 110.0)],
        route_name="Тестовый маршрут",
        mode="bike", style="leisure",
        distance_km=5.2, elevation_gain_m=10.0, elevation_loss_m=0.0,
        duration_estimate_hours=1.1, duration_warning=None,
        curated_routes_count=3, is_loop=True,
        skipped_interest_points=["Дальняя точка"],
        way_segments=[{"from": 0, "to": 1, "way_id": 5, "highway": "track", "surface": "gravel"}],
        point_features=[{
            "lon": 37.0005, "lat": 55.0005, "ele": 105.0,
            "name": "Родник", "type": "spring", "tier": "tag-backed",
            "role": None, "note": None, "source": None, "osm_id": "node/1",
            "wikidata": None, "wikipedia": None, "search_names": None,
            "opening_hours": None, "access_notes": None,
        }],
    )
    kwargs.update(overrides)
    return build_geojson(**kwargs)


def test_linestring_coordinates_are_3d():
    result = _sample_call()
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert line["geometry"]["coordinates"] == [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0]]


def test_linestring_carries_all_computed_properties():
    result = _sample_call()
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    props = line["properties"]

    assert props["name"] == "Тестовый маршрут"
    assert props["mode"] == "bike"
    assert props["style"] == "leisure"
    assert props["distance_km"] == 5.2
    assert props["elevation_gain_m"] == 10.0
    assert props["elevation_loss_m"] == 0.0
    assert props["duration_estimate_hours"] == 1.1
    assert props["duration_warning"] is None
    assert props["curated_routes_count"] == 3
    assert props["is_loop"] is True
    assert props["skipped_interest_points"] == ["Дальняя точка"]


def test_point_feature_omits_none_optional_properties():
    result = _sample_call()
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")

    assert point["geometry"]["coordinates"] == [37.0005, 55.0005, 105.0]
    assert point["properties"]["name"] == "Родник"
    assert point["properties"]["osm_id"] == "node/1"
    assert "wikidata" not in point["properties"]
    assert "opening_hours" not in point["properties"]


def test_access_point_keeps_opening_hours_and_access_notes_when_present():
    result = _sample_call(point_features=[{
        "lon": 37.0, "lat": 55.0, "ele": None,
        "name": "Станция Бажуково", "type": "access", "tier": None,
        "role": "start", "note": None, "source": None, "osm_id": "node/2",
        "wikidata": None, "wikipedia": None, "search_names": None,
        "opening_hours": "Mo-Su 06:00-23:00", "access_notes": "Билеты у кондуктора.",
    }])
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")

    assert point["properties"]["opening_hours"] == "Mo-Su 06:00-23:00"
    assert point["properties"]["access_notes"] == "Билеты у кондуктора."
    assert point["geometry"]["coordinates"] == [37.0, 55.0]  # no ele known for this point


def test_linestring_coerces_none_elevation_to_zero():
    result = _sample_call(path_coords=[(37.0, 55.0, 100.0), (37.001, 55.001, None)])
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert line["geometry"]["coordinates"] == [[37.0, 55.0, 100.0], [37.001, 55.001, 0.0]]


def test_linestring_carries_the_way_segments():
    result = _sample_call()
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")

    assert line["properties"]["segments"] == [{"from": 0, "to": 1, "way_id": 5, "highway": "track", "surface": "gravel"}]


def test_way_segments_have_no_default_so_they_cannot_be_left_out():
    import inspect
    assert inspect.signature(build_geojson).parameters["way_segments"].default is inspect.Parameter.empty



def test_elevations_are_stored_to_a_tenth_of_a_metre():
    result = _sample_call(
        path_coords=[(37.0, 55.0, 682.020635343171), (37.001, 55.001, 542.0), (37.002, 55.002, 100.04)],
        elevation_gain_m=840.3456, elevation_loss_m=839.96,
        point_features=[{"lon": 37.0005, "lat": 55.0005, "ele": 615.9931371309518, "name": "P", "type": "viewpoint"}])
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert [c[2] for c in line["geometry"]["coordinates"]] == [682.0, 542.0, 100.0]
    assert line["properties"]["elevation_gain_m"] == 840.3 and line["properties"]["elevation_loss_m"] == 840.0
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")
    assert point["geometry"]["coordinates"] == [37.0005, 55.0005, 616.0]


def test_rounding_keeps_coordinates_and_the_unknown_elevation_rules():
    result = _sample_call(
        path_coords=[(37.123456789, 55.987654321, None), (37.1, 55.9, 10.0)],
        point_features=[{"lon": 37.0, "lat": 55.0, "ele": None, "name": "P", "type": "viewpoint"}])
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert line["geometry"]["coordinates"][0] == [37.123456789, 55.987654321, 0.0]     # unknown stays 0.0
    point = next(f for f in result["features"] if f["geometry"]["type"] == "Point")
    assert point["geometry"]["coordinates"] == [37.0, 55.0]                              # and no elevation for a point


def test_an_unknown_gain_or_loss_is_written_as_null_not_a_crash():
    result = _sample_call(elevation_gain_m=None, elevation_loss_m=None)
    line = next(f for f in result["features"] if f["geometry"]["type"] == "LineString")
    assert line["properties"]["elevation_gain_m"] is None and line["properties"]["elevation_loss_m"] is None


def test_curated_source_is_written_only_when_given():
    assert "curated_source" not in next(f for f in _sample_call()["features"] if f["geometry"]["type"] == "LineString")["properties"]
    source = {"relation_id": 42, "name": "Ruta", "fidelity": 0.95}
    line = next(f for f in _sample_call(curated_source=source)["features"] if f["geometry"]["type"] == "LineString")
    assert line["properties"]["curated_source"] == source
