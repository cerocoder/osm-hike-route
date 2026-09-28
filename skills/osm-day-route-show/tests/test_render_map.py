import json

from render_map import lang_priority, t, build_gpx, build_map_html


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


def test_annotate_place_info_never_constructs_opentripmap_without_key(tmp_path, monkeypatch):
    """Final-review Fix 1: OpenTripMapProvider must not even be instantiated
    (let alone queried) when no key is configured — otherwise
    PlaceInfoService.fetch_all would cache its None result as a permanent
    negative in place_info.json before a key is ever set, and a later
    render (once a key IS configured) would stay poisoned by that stale
    cache entry."""
    monkeypatch.delenv("OSM_DAY_ROUTE_OPENTRIPMAP_KEY", raising=False)
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
            "properties": {"name": "Родник", "type": "spring", "osm_id": "node/1"},
        }],
    }

    # Mock PlaceInfoService itself too (same pattern as the other
    # annotate_place_info tests) so the *other* three providers' real
    # fetch() methods never make live network calls in this suite —
    # only what's actually under test here (whether OpenTripMapProvider
    # gets constructed at all) should run for real.
    with patch("render_map.OpenTripMapProvider") as MockOpenTripMap, \
         patch("render_map.PlaceInfoService") as MockService:
        MockService.return_value.fetch_all.return_value = []
        annotate_place_info(geojson, user_lang="ru", local_lang=None,
                             cache_path=tmp_path / "place_info.json")

    MockOpenTripMap.assert_not_called()
    providers_passed = MockService.call_args[0][0]
    assert len(providers_passed) == 3  # wikipedia, wikidata, wikimedia_commons only


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


from render_map import point_popup_html


def test_point_popup_includes_opening_hours_and_access_notes_for_access_point():
    props = {
        "name": "Станция Бажуково", "type": "access", "role": "start",
        "opening_hours": "Mo-Su 06:00-23:00", "access_notes": "Билеты у кондуктора.",
    }

    html = point_popup_html(props)

    assert "Mo-Su 06:00-23:00" in html
    assert "Билеты у кондуктора." in html


def test_point_popup_includes_all_place_info_entries():
    props = {
        "name": "Родник", "type": "spring",
        "_placeInfo": [
            {"provider_id": "wikidata", "summary": "источник питьевой воды"},
            {"provider_id": "wikimedia_commons", "image_url": "https://commons.wikimedia.org/wiki/File:X.jpg"},
        ],
    }

    html = point_popup_html(props)

    assert "источник питьевой воды" in html
    assert "https://commons.wikimedia.org/wiki/File:X.jpg" in html
    assert "wikidata" in html
    assert "wikimedia_commons" in html


def test_point_popup_omits_placeinfo_block_when_nothing_found():
    html = point_popup_html({"name": "Точка", "type": "waypoint"})
    assert "_placeInfo" not in html


def test_build_map_html_renders_3d_archive_without_crashing(tmp_path):
    """spec §7: a render-level smoke test, not just per-function unit tests
    — a full current-schema archive (3D coords, full LineString stats,
    an interest point, and an access point carrying opening_hours/
    wikidata/search_names) must render end to end without raising.
    resolve_wiki=False avoids any live network call, per this project's
    "no live network access in the automated suite" convention."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [
                    [37.0, 55.0, 100.0], [37.001, 55.001, 110.0], [37.002, 55.002, 105.0],
                ]},
                "properties": {
                    "name": "Тестовый маршрут", "mode": "walk", "style": "leisure",
                    "distance_km": 8.4, "elevation_gain_m": 220.0, "elevation_loss_m": 210.0,
                    "duration_estimate_hours": 3.2, "curated_routes_count": 2,
                    "duration_warning": "может не влезть в световой день",
                    "skipped_interest_points": ["Дальняя точка"], "is_loop": False,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005, 105.0]},
                "properties": {
                    "name": "Родник", "type": "spring", "tier": "tag-backed",
                    "note": "рядом брод", "source": "OSM", "osm_id": "node/1",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.0, 55.0, 100.0]},
                "properties": {
                    "name": "Станция Бажуково", "type": "access", "role": "start",
                    "opening_hours": "Mo-Su 06:00-23:00", "access_notes": "Билеты у кондуктора.",
                    "wikidata": "Q3070795", "search_names": {"en": "Bazhukovo Station"},
                },
            },
        ],
    }
    geojson_path = tmp_path / "route.geojson"
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    html = build_map_html(geojson_path, notes_path=None, title="Test",
                           user_lang="ru", local_lang=None, resolve_wiki=False)

    assert isinstance(html, str) and html.strip()


def test_build_map_html_renders_2d_legacy_archive_without_crashing(tmp_path):
    """spec §7 render-level smoke test: a minimal pre-this-round archive
    (2D coordinates only, a LineString with only `name`, a Point with only
    `name`/`type`) must render without raising, same as the 3D/full-schema
    case above."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
                "properties": {"name": "Старый маршрут"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005]},
                "properties": {"name": "Точка", "type": "waypoint"},
            },
        ],
    }
    geojson_path = tmp_path / "route.geojson"
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    html = build_map_html(geojson_path, notes_path=None, title="Test",
                           user_lang="ru", local_lang=None, resolve_wiki=False)

    assert isinstance(html, str) and html.strip()


from render_map import _tile_coverage_points


def _geojson_with_access_and_interest_points():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
             "properties": {"name": "Route"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.0, 55.0]},
             "properties": {"type": "access", "name": "Start"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.001, 55.001]},
             "properties": {"type": "access", "name": "End"}},
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [37.0005, 55.0005]},
             "properties": {"type": "interest", "name": "Spring"}},
        ],
    }


def test_tile_coverage_points_prefers_access_points():
    points = _tile_coverage_points(_geojson_with_access_and_interest_points())
    assert set(points) == {(55.0, 37.0), (55.001, 37.001)}


def test_tile_coverage_points_falls_back_to_interest_points_when_no_access():
    geojson = _geojson_with_access_and_interest_points()
    for f in geojson["features"]:
        if f["geometry"]["type"] == "Point" and f["properties"]["type"] == "access":
            f["properties"]["type"] = "waypoint"  # neither access nor interest

    points = _tile_coverage_points(geojson)

    assert points == [(55.0005, 37.0005)]


def test_tile_coverage_points_empty_when_no_access_or_interest_points():
    """Review Focus: a legacy LineString-only archive must not crash —
    empty result means 'skip probing', handled by TileProviderService."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
             "properties": {"name": "Old route"}},
        ],
    }

    assert _tile_coverage_points(geojson) == []
