from render_map import lang_priority, t, build_gpx


def test_lang_priority_orders_user_local_english_deduplicated():
    assert lang_priority("ru", "ru") == ["ru", "en"]
    assert lang_priority("ru", "es") == ["ru", "es", "en"]


def test_t_falls_back_to_english_for_unknown_language():
    assert t("wikipedia", "xx") == t("wikipedia", "en")


def _geojson_3d():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0]]},
                "properties": {"name": "Тестовый маршрут"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005, 105.0]},
                "properties": {"name": "Родник", "type": "spring"},
            },
        ],
    }


def _geojson_2d_legacy():
    """Pre-this-round archive: no third coordinate anywhere."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
                "properties": {"name": "Старый маршрут"},
            },
        ],
    }


def test_build_gpx_does_not_raise_on_3d_coordinates():
    gpx = build_gpx(_geojson_3d(), "Тестовый маршрут")
    assert "<gpx" in gpx


def test_build_gpx_emits_ele_for_3d_track_points_and_waypoints():
    gpx = build_gpx(_geojson_3d(), "Тестовый маршрут")

    assert "<ele>100.0</ele>" in gpx
    assert "<ele>110.0</ele>" in gpx
    assert "<ele>105.0</ele>" in gpx


def test_build_gpx_omits_ele_for_2d_legacy_coordinates():
    gpx = build_gpx(_geojson_2d_legacy(), "Старый маршрут")

    assert "<ele>" not in gpx
    assert '<trkpt lat="55.0" lon="37.0"/>' in gpx or "<trkpt" in gpx
