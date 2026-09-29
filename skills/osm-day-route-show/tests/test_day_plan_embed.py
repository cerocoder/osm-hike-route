import json
import re

from render_map import build_map_html

GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-3.75, 40.42, 600.0], [-3.74, 40.43, 640.0]]},
        "properties": {"name": "Casa de Campo", "mode": "walk", "distance_km": 3.0,
                       "elevation_gain_m": 40, "elevation_loss_m": 0, "duration_estimate_hours": 1.0},
    }],
}


def _route(tmp_path, plans=None):
    (tmp_path / "route.geojson").write_text(json.dumps(GEOJSON), encoding="utf-8")
    (tmp_path / "notes.md").write_text("## Access\n\n- Metro\n\n## Points of interest\n\n- Lake\n", encoding="utf-8")
    for date, text in (plans or {}).items():
        (tmp_path / f"day-plan-{date}.md").write_text(text, encoding="utf-8")
    return tmp_path


def _plan(date, storm="storm"):
    return (f"# Casa de Campo — {date}\n<!-- day-plan fetched_at: {date}T06:00:00Z -->\n*Meta*\n\n"
            f"## Summary\n\n- **Danger:** {storm}\n\n## Weather by hour\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")


def _build(route_dir, lang="en"):
    return build_map_html(route_dir / "route.geojson", route_dir / "notes.md", title="Casa de Campo",
                          user_lang=lang, resolve_wiki=False, tile_timeout=0.1)


def test_map_without_plans_shows_placeholder_block_between_poi_and_export(tmp_path):
    html = _build(_route(tmp_path))
    assert "No day plan yet" in html
    assert "const DAY_PLANS = [];" in html
    assert html.index("<h3>Points of interest</h3>") < html.index("<h3>Day plan</h3>") \
        < html.index("<h3>Export & open elsewhere</h3>")


def test_map_embeds_every_plan_so_the_file_can_be_forwarded(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21", "storm A"),
                              "2026-06-28": _plan("2026-06-28", "storm B")})
    html = _build(route)
    assert html.count('<option value=') == 2
    assert "storm A" in html and "storm B" in html
    # embedded raw markdown for download, and rendered HTML for the panel
    assert "## Weather by hour" in html
    assert "<table>" in html


def test_map_has_download_print_and_print_css(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}))
    assert 'id="dp-download"' in html and 'id="dp-print"' in html
    assert "data:text/markdown" in html
    assert "@media print" in html and "#dp-overlay" in html
    assert "Casa de Campo" in html  # download filename base


def test_download_filename_base_strips_path_characters(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21")})
    html = build_map_html(route / "route.geojson", route / "notes.md", title='A/B: "C"',
                          resolve_wiki=False, tile_timeout=0.1)
    assert 'const DP_FILE_BASE = "A_B_ _C_";' in html


def test_map_is_localized(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}), lang="ru")
    assert "План дня" in html and "Открыть полный план" in html


def test_plan_with_script_tag_does_not_break_the_page(tmp_path):
    route = _route(tmp_path, {"2026-06-21": _plan("2026-06-21", "</script><script>alert(1)</script>")})
    html = _build(route)
    assert "<script>alert(1)</script>" not in html


def test_existing_sections_are_untouched_when_plans_exist(tmp_path):
    html = _build(_route(tmp_path, {"2026-06-21": _plan("2026-06-21")}))
    assert "Getting there" in html and "Points of interest" in html and "Metro" in html
