import datetime
import json

import pytest

from day_plan.cache import JsonCache
from day_plan.context import build_context
from day_plan.facts import load_facts, lookup
from day_plan.http import HttpError, get_json
from day_plan.i18n import STRINGS, compass, tr


def test_tr_falls_back_to_english_for_missing_key_and_unknown_language():
    assert tr("h_summary", "xx") == "Summary"
    assert tr("w_warn_fog", "de") == tr("w_warn_fog", "en")
    assert tr("h_summary", "ru") == "Главное на день"


def test_tr_formats_placeholders():
    assert "5" in tr("light_warn_tight", "en", buffer=5)


def test_headings_exist_in_all_seven_languages():
    for lang in ("en", "ru", "es", "fr", "de", "pt", "it"):
        for key in ("h_summary", "h_light", "h_weather", "h_transit", "h_pois", "h_hazards", "h_cell_coverage"):
            assert key in STRINGS[lang], (lang, key)


def test_compass_points():
    assert compass(0, "en") == "N"
    assert compass(270, "en") == "W"
    assert compass(359, "en") == "N"
    assert compass(45, "ru") == "СВ"


def test_cache_roundtrip_and_expiry(tmp_path):
    clock = [1000.0]
    cache = JsonCache(tmp_path / "c.json", now=lambda: clock[0])
    assert cache.get_entry("k") is None
    cache.put("k", {"a": 1})
    assert cache.get_entry("k") == ({"a": 1}, 1000.0)
    clock[0] = 1000.0 + 50
    assert cache.get_entry("k", max_age=100) is not None
    assert cache.get_entry("k", max_age=10) is None
    reloaded = JsonCache(tmp_path / "c.json", now=lambda: clock[0])
    assert reloaded.get_entry("k") == ({"a": 1}, 1000.0)


def test_cache_ignores_corrupt_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    assert JsonCache(path).get_entry("k") is None


def test_facts_lookup_prefers_date_over_all(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({
        "all": {"transit": {"markdown": "generic", "sources": ["https://example.org/a"]}},
        "2026-06-21": {"transit": {"markdown": "specific", "sources": ["https://example.org/b"]}},
    }), encoding="utf-8")
    facts = load_facts(tmp_path)
    assert lookup(facts, "2026-06-21", "transit")["markdown"] == "specific"
    assert lookup(facts, "2026-06-22", "transit")["markdown"] == "generic"
    assert lookup(facts, "2026-06-22", "poi") is None


def test_load_facts_missing_or_invalid_is_empty(tmp_path):
    assert load_facts(tmp_path) == {}
    (tmp_path / "facts.json").write_text("[]", encoding="utf-8")
    assert load_facts(tmp_path) == {}


def test_get_json_wraps_transport_errors():
    import urllib.error
    from unittest.mock import patch
    with patch("day_plan.http._open", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(HttpError):
            get_json("https://example.invalid/")


def test_build_context_reads_route(make_route, fixed_now):
    route_dir = make_route(name="Loop", mode="bike", duration_hours=3.5)
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), lang="ru", now=fixed_now)
    assert ctx.route_name == "Loop"
    assert ctx.mode == "bike"
    assert ctx.duration_hours == 3.5
    assert ctx.centroid == pytest.approx((51.5, -0.125))
    assert ctx.coords[0] == (-0.20, 51.45, 30.0)
    assert ctx.today == datetime.date(2026, 6, 20)
    assert ctx.date_iso == "2026-06-21"


def test_build_context_tolerates_2d_coordinates_and_missing_properties(make_route, fixed_now):
    route_dir = make_route(coords=((10.0, 50.0), (10.2, 50.2)))
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.coords[0] == (10.0, 50.0, None)


def test_build_context_rejects_route_without_linestring(tmp_path, fixed_now):
    (tmp_path / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    with pytest.raises(ValueError):
        build_context(tmp_path, datetime.date(2026, 6, 21), now=fixed_now)


def test_centroid_of_a_route_crossing_the_antimeridian_is_near_180(make_route, fixed_now):
    route_dir = make_route(coords=((179.5, 66.0, None), (-179.5, 66.2, None)))
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert abs(abs(ctx.centroid[1]) - 180.0) < 0.6
    assert ctx.centroid[0] == pytest.approx(66.1)
