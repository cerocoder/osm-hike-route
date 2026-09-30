import json

import pytest
from archive_validate import validate_archive, ArchiveIncompleteError, _validate_geojson

_COMPLETE_LINE_PROPS = {
    "name": "Тестовый маршрут", "mode": "walk", "style": None,
    "distance_km": 5.2, "elevation_gain_m": 40.0, "elevation_loss_m": 40.0,
    "duration_estimate_hours": 1.5, "duration_warning": None,
    "curated_routes_count": 2, "is_loop": True, "skipped_interest_points": [],
}


def _write_complete_archive(route_dir):
    route_dir.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0]]},
            "properties": dict(_COMPLETE_LINE_PROPS),
        }],
    }
    (route_dir / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    (route_dir / "weights.json").write_text(json.dumps({"mode": "walk"}), encoding="utf-8")
    (route_dir / "requests.md").write_text("# Requests\n", encoding="utf-8")
    (route_dir / "notes.md").write_text("# Notes\n", encoding="utf-8")
    return geojson


def test_complete_archive_passes(tmp_path):
    _write_complete_archive(tmp_path)
    validate_archive(tmp_path)  # no exception


def test_missing_files_are_all_reported_together(tmp_path):
    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    message = str(exc_info.value)
    for filename in ("route.geojson", "weights.json", "requests.md", "notes.md"):
        assert filename in message


def test_2d_linestring_coordinates_are_rejected():
    problems = _validate_geojson({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[37.0, 55.0], [37.001, 55.001]]},
            "properties": dict(_COMPLETE_LINE_PROPS),
        }],
    })
    assert any("3D" in p for p in problems)


def test_missing_computed_properties_are_reported(tmp_path):
    geojson = _write_complete_archive(tmp_path)
    line = geojson["features"][0]
    del line["properties"]["elevation_gain_m"]
    del line["properties"]["elevation_loss_m"]
    del line["properties"]["duration_estimate_hours"]
    (tmp_path / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    message = str(exc_info.value)
    assert "elevation_gain_m" in message
    assert "elevation_loss_m" in message
    assert "duration_estimate_hours" in message


def test_real_incident_shape_is_caught(tmp_path):
    """Reproduces the actual cerros-de-la-maranosa-2026-09-28 archive shape:
    2D coordinates, LineString properties with only 'name', no weights.json,
    no requests.md."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-3.558, 40.252], [-3.559, 40.250]]},
            "properties": {"name": "Cerros de La Marañosa"},
        }],
    }
    (tmp_path / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    message = str(exc_info.value)
    assert "weights.json" in message
    assert "requests.md" in message
    assert "3D" in message
    assert "mode" in message


def test_wrong_type_numeric_property_is_reported(tmp_path):
    geojson = _write_complete_archive(tmp_path)
    geojson["features"][0]["properties"]["distance_km"] = "5.2 км"
    (tmp_path / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    assert "distance_km" in str(exc_info.value)


def test_invalid_mode_is_reported(tmp_path):
    geojson = _write_complete_archive(tmp_path)
    geojson["features"][0]["properties"]["mode"] = "drive"
    (tmp_path / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    assert "drive" in str(exc_info.value)


def test_malformed_json_is_reported_not_crashed(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "route.geojson").write_text("{not json", encoding="utf-8")
    (tmp_path / "weights.json").write_text("{}", encoding="utf-8")
    (tmp_path / "requests.md").write_text("x", encoding="utf-8")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    assert "route.geojson" in str(exc_info.value)


def _archive_with_segments(tmp_path, segments):
    geojson = _write_complete_archive(tmp_path)
    geojson["features"][0]["properties"]["segments"] = segments
    (tmp_path / "route.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")


def test_an_archive_without_segments_is_still_valid(tmp_path):
    _write_complete_archive(tmp_path)
    validate_archive(tmp_path)


def test_segments_that_cover_the_vertices_are_valid(tmp_path):
    _archive_with_segments(tmp_path, [{"from": 0, "to": 1, "way_id": 5, "highway": "track"}])
    validate_archive(tmp_path)


@pytest.mark.parametrize("segments, fragment", [
    ([], "непустой список"),
    ("track", "непустой список"),
    ([{"from": 0, "to": "1"}], "целыми числами"),
    ([{"from": True, "to": 1}], "целыми числами"),
    ([{"from": 1, "to": 2}], "не продолжает"),
    ([{"from": 0, "to": 0}], "не продолжает"),
    ([{"from": 0, "to": 1}, {"from": 0, "to": 1}], "не продолжает"),
    ([{"from": 0, "to": 3}], "последний индекс должен быть 1"),
])
def test_broken_segments_are_reported(tmp_path, segments, fragment):
    _archive_with_segments(tmp_path, segments)

    with pytest.raises(ArchiveIncompleteError) as exc_info:
        validate_archive(tmp_path)

    assert fragment in str(exc_info.value)

