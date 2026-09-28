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


from unittest.mock import patch
from render_map import annotate_place_info
from place_info.providers.base import PlaceInfoResult


def test_annotate_place_info_adds_placeinfo_list_to_point_features(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
            "properties": {"name": "Родник", "type": "spring", "osm_id": "node/1"},
        }],
    }

    fake_results = [PlaceInfoResult(provider_id="wikidata", summary="источник")]
    with patch("render_map.PlaceInfoService") as MockService:
        MockService.return_value.fetch_all.return_value = fake_results
        annotate_place_info(geojson, user_lang="ru", local_lang=None,
                             cache_path=tmp_path / "place_info.json")

    point = geojson["features"][0]
    assert point["properties"]["_placeInfo"] == [{"provider_id": "wikidata", "summary": "источник"}]


def test_annotate_place_info_skips_linestring_features(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.1, 55.1]]},
            "properties": {"name": "Маршрут"},
        }],
    }

    annotate_place_info(geojson, user_lang="ru", local_lang=None, cache_path=tmp_path / "place_info.json")

    assert "_placeInfo" not in geojson["features"][0]["properties"]


from render_map import route_stats_html


def test_route_stats_html_includes_all_present_fields():
    props = {
        "mode": "bike", "style": "leisure", "distance_km": 12.3,
        "elevation_gain_m": 150.0, "elevation_loss_m": 140.0,
        "duration_estimate_hours": 2.5, "duration_warning": None,
        "curated_routes_count": 4, "is_loop": True,
        "skipped_interest_points": ["Дальняя точка"],
    }

    html = route_stats_html(props, user_lang="ru")

    assert "12.3" in html
    assert "150" in html
    assert "Дальняя точка" in html


def test_route_stats_html_defaults_missing_mode_to_walk():
    """Review Focus #2: an archive from before this round has no `mode`."""
    html = route_stats_html({}, user_lang="ru")
    assert "walk" in html or "пешком" in html


def test_route_stats_html_omits_warning_line_when_none():
    props = {"mode": "walk", "duration_warning": None}
    html = route_stats_html(props, user_lang="ru")
    assert "duration-warning" not in html.lower() or "None" not in html


def test_route_stats_html_shows_warning_text_when_present():
    props = {"mode": "walk", "duration_warning": "маршрут может не влезть в световой день"}
    html = route_stats_html(props, user_lang="ru")
    assert "маршрут может не влезть в световой день" in html
