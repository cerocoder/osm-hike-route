import json

from day_plan_view import (
    DAY_PLAN_SUMMARY_HEADINGS, DAY_PLAN_UI, build_day_plan_parts, default_plan_index, load_day_plans,
)
from render_map import SECTION_ALIASES, extract_md_section, t

PLAN = (
    "# Route — 2026-06-21\n<!-- day-plan fetched_at: 2026-06-20T12:00:00Z -->\n*Meta*\n\n"
    "## Summary\n\n- **Danger:** storm\n\n## Daylight\n\n- Sunrise **04:43**\n"
)


def _write(route_dir, date, text=PLAN):
    (route_dir / f"day-plan-{date}.md").write_text(text, encoding="utf-8")


def _labels(lang="en"):
    return {key: t(key, lang) for key in DAY_PLAN_UI["en"]}


def _plan_dict(date="2026-06-21", md="# T\n"):
    return {"date": date, "md": md, "html": "<h2>T</h2>", "summary_html": "<ul><li>x</li></ul>",
            "fetched_at": "2026-06-20T12:00:00Z"}


def test_load_returns_plans_sorted_by_date_with_comments_stripped(tmp_path):
    _write(tmp_path, "2026-06-23")
    _write(tmp_path, "2026-06-21")
    plans = load_day_plans(tmp_path)
    assert [p.date for p in plans] == ["2026-06-21", "2026-06-23"]
    assert "<!--" not in plans[0].markdown
    assert plans[0].fetched_at == "2026-06-20T12:00:00Z"


def test_load_skips_impossible_dates_other_files_and_unreadable_files(tmp_path):
    _write(tmp_path, "2026-13-45")
    (tmp_path / "day-plan-notes.md").write_text("x", encoding="utf-8")
    (tmp_path / "day-plan-2026-06-21.facts.json").write_text("{}", encoding="utf-8")
    (tmp_path / "day-plan-2026-06-22.md").write_bytes(b"\xff\xfe\x00bad")
    _write(tmp_path, "2026-06-24")
    assert [p.date for p in load_day_plans(tmp_path)] == ["2026-06-24"]


def test_load_with_no_plans_is_empty(tmp_path):
    assert load_day_plans(tmp_path) == []


def test_default_index_is_nearest_upcoming_else_latest():
    dates = ["2026-06-10", "2026-06-21", "2026-06-30"]
    assert default_plan_index(dates, "2026-06-15") == 1
    assert default_plan_index(dates, "2026-06-21") == 1
    assert default_plan_index(dates, "2026-06-01") == 0
    assert default_plan_index(dates, "2026-07-15") == 2
    assert default_plan_index([], "2026-06-15") == 0


def test_summary_aliases_find_the_section_in_every_language():
    for heading in DAY_PLAN_SUMMARY_HEADINGS:
        md = f"# T\n\n## {heading}\n\n- one\n\n## Other\n\n- two\n"
        assert extract_md_section(md, "day_plan_summary") == "- one", heading


def test_aliases_are_registered_and_ui_strings_exist_in_all_languages():
    assert SECTION_ALIASES["day_plan_summary"] == DAY_PLAN_SUMMARY_HEADINGS
    for lang in ("en", "ru", "es", "fr", "de", "pt", "it"):
        assert t("day_plan_open", lang) == DAY_PLAN_UI[lang]["day_plan_open"]
    assert t("day_plan_title", "xx") == "Day plan"   # English fallback


def test_no_plans_gives_placeholder_and_no_overlay():
    sidebar, overlay, script = build_day_plan_parts([], _labels(), "Route", "2026-06-21")
    assert "No day plan yet" in sidebar
    assert overlay == ""
    assert script == "const DAY_PLANS = [];"


def test_single_plan_shows_date_text_not_a_select():
    sidebar, overlay, script = build_day_plan_parts([_plan_dict()], _labels(), "Route", "2026-06-21")
    assert "<select" not in sidebar
    assert "2026-06-21" in sidebar
    assert 'id="dp-open"' in sidebar
    assert 'id="dp-overlay" hidden' in overlay


def test_several_plans_give_a_date_select_and_all_are_embedded():
    plans = [_plan_dict("2026-06-21"), _plan_dict("2026-06-23", md="# Other\n")]
    sidebar, overlay, script = build_day_plan_parts(plans, _labels(), "Route", "2026-06-22")
    assert sidebar.count("<option") == 2
    assert "let current = 1;" in script          # nearest upcoming date
    payload = json.loads(script.split("const DAY_PLANS = ")[1].split(";\n  const DP_LABELS")[0])
    assert [p["date"] for p in payload] == ["2026-06-21", "2026-06-23"]
    assert payload[1]["md"] == "# Other\n"


def test_toolbar_has_download_print_and_close_and_localized_labels():
    _, overlay, _ = build_day_plan_parts([_plan_dict()], _labels("ru"), "Route", "2026-06-21")
    assert 'id="dp-download"' in overlay and "Скачать .md" in overlay
    assert 'id="dp-print"' in overlay and "Печать / сохранить в PDF" in overlay
    assert 'id="dp-close"' in overlay


def test_plan_text_cannot_break_out_of_the_script_tag():
    md = "# T\n</script><script>alert(1)</script>\n"
    _, _, script = build_day_plan_parts([_plan_dict(md=md)], _labels(), "Route", "2026-06-21")
    assert "</script>" not in script


def test_plan_saved_with_a_bom_and_crlf_line_endings_still_loads_cleanly(tmp_path):
    (tmp_path / "day-plan-2026-06-21.md").write_bytes(("\ufeff" + PLAN.replace("\n", "\r\n")).encode("utf-8"))
    plan = load_day_plans(tmp_path)[0]
    assert plan.markdown.startswith("# Route")
    assert "\r" not in plan.markdown
