import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.i18n import LANGS, STRINGS, activity_label
from day_plan.service import assemble_markdown  # noqa: F401  (the header is asserted through build_plan in test_service)

DATE = datetime.date(2026, 12, 20)


def _archive(tmp_path, props=None, coords=None, folder="route"):
    route_dir = tmp_path / folder
    route_dir.mkdir()
    coords = coords or [[37.0, 55.0, 100.0], [37.001, 55.001, 110.0], [37.002, 55.002, 120.0]]
    line = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"name": "T", "mode": "walk", **(props or {})}}
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [line]}),
                                             encoding="utf-8")
    return route_dir


@pytest.mark.parametrize("mode, style, lang, expected", [
    ("walk", None, "en", "on foot"), ("walk", None, "ru", "пешком"),
    ("bike", "sport", "en", "cycling (sport)"), ("bike", "leisure", "en", "cycling (leisure)"),
    ("bike", "sport", "ru", "вело (спорт)"), ("bike", "leisure", "ru", "вело (прогулка)"),
    ("bike", None, "ru", "вело"), ("ski", None, "ru", "лыжи"), ("ski", None, "en", "skiing"),
    ("bike", "gravel", "en", "cycling (gravel)"), ("boat", None, "en", "boat"), ("walk", None, "xx", "on foot"),
])
def test_activity_label(mode, style, lang, expected):
    assert activity_label(mode, style, lang) == expected


def test_every_language_has_every_activity_string():
    for lang in LANGS:
        for key in ("mode_walk", "mode_bike", "mode_bike_sport", "mode_bike_leisure", "mode_ski"):
            assert key in STRINGS[lang], (lang, key)


def test_the_context_exposes_the_style_and_the_segments(tmp_path, fixed_now):
    segments = [{"from": 0, "to": 1, "way_id": 1, "highway": "track"}, {"from": 1, "to": 2, "way_id": 2}]
    ctx = build_context(_archive(tmp_path, {"mode": "bike", "style": "sport", "segments": segments}), DATE,
                        now=fixed_now)
    assert ctx.mode == "bike" and ctx.style == "sport" and ctx.segments == segments


def test_an_older_archive_has_no_style_and_no_segments(tmp_path, fixed_now):
    ctx = build_context(_archive(tmp_path), DATE, now=fixed_now)
    assert ctx.style is None and ctx.segments is None


@pytest.mark.parametrize("segments", [
    [], "track", [{"from": 0, "to": 1}], [{"from": 1, "to": 2}], [{"from": 0, "to": 0}, {"from": 0, "to": 2}],
    [{"from": 0, "to": "1"}, {"from": 1, "to": 2}], [{"from": True, "to": 2}], [3], [{"from": 0, "to": 5}],
])
def test_malformed_segments_read_as_no_road_data(tmp_path, fixed_now, segments):
    ctx = build_context(_archive(tmp_path, {"segments": segments}), DATE, now=fixed_now)
    assert ctx.segments is None
