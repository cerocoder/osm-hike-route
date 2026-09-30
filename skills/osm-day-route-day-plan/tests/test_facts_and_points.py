import datetime
import json

import pytest

from day_plan.context import RoutePoint, build_context
from day_plan.facts import load_facts, lookup, normalize_entry

URL = "https://example.org/timetable"


def _entry(**extra):
    return {"markdown": "Bus 41 every 20 min.", "sources": [URL], **extra}


# ---- facts schema -------------------------------------------------------------------------------

def test_entry_without_sources_is_dropped():
    assert normalize_entry({"markdown": "text"}) is None
    assert normalize_entry({"markdown": "text", "sources": []}) is None
    assert normalize_entry({"markdown": "text", "sources": ["not a url", 5, None]}) is None


def test_only_http_sources_are_kept():
    entry = normalize_entry(_entry(sources=[URL, "ftp://x", "javascript:alert(1)", "https://b.org"]))
    assert entry["sources"] == [URL, "https://b.org"]


def test_markdown_is_required_unless_a_day_type_is_given():
    assert normalize_entry({"sources": [URL]}) is None
    assert normalize_entry({"sources": [URL], "markdown": "   "}) is None
    assert normalize_entry({"sources": [URL], "day_type": "holiday"})["day_type"] == "holiday"


def test_structured_fields_are_validated():
    entry = normalize_entry(_entry(last_departure_local="23:40", first_departure_local="5:10"))
    assert entry["last_departure_local"] == "23:40"
    assert entry["first_departure_local"] == "5:10"
    bad = normalize_entry(_entry(last_departure_local="late", first_departure_local="25:99", day_type="funday"))
    assert "last_departure_local" not in bad and "first_departure_local" not in bad and "day_type" not in bad


def test_warnings_keep_only_valid_items():
    entry = normalize_entry(_entry(warnings=[
        {"severity": "danger", "text": "Last bus 21:10"},
        {"severity": "mystery", "text": "odd"},
        {"severity": "info"},
        "not a dict",
        {"severity": "caution", "text": ""},
    ]))
    assert entry["warnings"] == [{"severity": "danger", "text": "Last bus 21:10"}]


def test_non_dict_entry_is_dropped():
    assert normalize_entry("text") is None
    assert normalize_entry(None) is None
    assert normalize_entry([1]) is None


def test_lookup_returns_normalized_entries_and_prefers_the_date(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({
        "all": {"transit": _entry(markdown="generic")},
        "2026-06-21": {"transit": _entry(markdown="specific")},
        "2026-06-22": {"transit": {"markdown": "no sources here"}},
    }), encoding="utf-8")
    facts = load_facts(tmp_path)
    assert lookup(facts, "2026-06-21", "transit")["markdown"] == "specific"
    assert lookup(facts, "2026-06-23", "transit")["markdown"] == "generic"
    # a dated entry without sources is dropped, and the "all" entry is used instead
    assert lookup(facts, "2026-06-22", "transit")["markdown"] == "generic"
    assert lookup(facts, "2026-06-21", "poi_hours") is None


# ---- route points in the context ----------------------------------------------------------------

def _write_route(tmp_path, features):
    route_dir = tmp_path / "r"
    route_dir.mkdir()
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return route_dir


LINE = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-3.75, 40.42, 600], [-3.74, 40.43, 640]]},
        "properties": {"name": "R", "mode": "walk", "duration_estimate_hours": 3}}


def _point(name, type_, lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "type": type_, **props}}


def test_points_are_split_into_access_and_interest(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, [
        LINE,
        _point("Lago", "access", -3.7275, 40.4247, role="start", opening_hours="05:00-01:00", access_notes="Metro line 10"),
        _point("Fountain", "fountain", -3.74, 40.43, note="Drinking water"),
        _point("Museum", "sight", -3.741, 40.431, opening_hours="Tu-Su 10:00-18:00", osm_id="node/1"),
    ])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert [p.name for p in ctx.access_points] == ["Lago"]
    assert [p.name for p in ctx.interest_points] == ["Fountain", "Museum"]
    lago = ctx.access_points[0]
    assert isinstance(lago, RoutePoint)
    assert (lago.lat, lago.lon, lago.role) == (40.4247, -3.7275, "start")
    assert lago.opening_hours == "05:00-01:00" and lago.access_notes == "Metro line 10"
    museum = ctx.interest_points[1]
    assert museum.osm_id == "node/1" and museum.opening_hours == "Tu-Su 10:00-18:00"
    assert ctx.interest_points[0].note == "Drinking water"


def test_points_default_to_empty_lists_and_tolerate_odd_features(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, [
        LINE,
        {"type": "Feature", "geometry": None, "properties": {"name": "no geometry"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}, "properties": None},
    ])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.access_points == []
    assert [p.name for p in ctx.interest_points] == ["Waypoint"]   # unnamed point, only the well-formed one kept


def test_route_with_only_a_line_has_no_points(tmp_path, fixed_now):
    ctx = build_context(_write_route(tmp_path, [LINE]), datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.access_points == [] and ctx.interest_points == []


# ---- a newline must not create structure -------------------------------------------------------

def test_warning_text_whitespace_is_collapsed_and_headings_in_markdown_are_demoted():
    entry = normalize_entry(_entry(markdown="## Hazards\ntext\n   # Title\n####### seven\n#nospace",
                                   warnings=[{"severity": "caution", "text": "Line\n## Injected\t here"}]))
    assert entry["warnings"] == [{"severity": "caution", "text": "Line ## Injected here"}]
    assert entry["markdown"].splitlines() == ["**Hazards**", "text", "**Title**", "####### seven", "#nospace"]


@pytest.mark.parametrize("bad", ["http://", "https://", "https://exa mple.com", "https://example.com/a b",
                                 "https://example.com/a\nb", "http:///path"])
def test_sources_need_a_host_and_no_whitespace(bad):
    assert normalize_entry(_entry(sources=[bad])) is None
    assert normalize_entry(_entry(sources=[bad, URL]))["sources"] == [URL]


def test_parentheses_stay_allowed_in_a_source():
    url = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert normalize_entry(_entry(sources=[url]))["sources"] == [url]


def test_time_fields_reject_a_trailing_newline_and_check_the_hour_bound():
    assert "last_departure_local" not in normalize_entry(_entry(last_departure_local="23:40\n"))
    assert normalize_entry(_entry(last_departure_local="29:59"))["last_departure_local"] == "29:59"
    assert "last_departure_local" not in normalize_entry(_entry(last_departure_local="30:00"))


# ---- odd features in route.geojson --------------------------------------------------------------

def test_points_skip_features_and_parts_of_the_wrong_type(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, [
        LINE, "a string", 5, None, ["x"],
        {"type": "Feature", "geometry": "Point", "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}, "properties": "props"},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ["1", "2"]}, "properties": {"name": "str"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [True, 2.0]}, "properties": {"name": "bool"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, None]}, "properties": {"name": "none"}},
        _point("Good", "sight", 1.5, 2.5),
    ])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert [p.name for p in ctx.interest_points] == ["Waypoint", "Good"]     # the "props" feature has no name
    assert ctx.access_points == []


def test_a_non_dict_feature_before_the_line_does_not_break_the_context(tmp_path, fixed_now):
    route_dir = _write_route(tmp_path, ["junk", None, {"type": "Feature", "geometry": []}, LINE])
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), now=fixed_now)
    assert ctx.route_name == "R" and ctx.access_points == [] and ctx.interest_points == []


@pytest.mark.parametrize("bad_url", ["http://[::1", "https://[fe80::1%25eth0", "http://[", "https://ex ample.com"])
def test_a_malformed_url_is_dropped_not_a_crash(bad_url):
    assert normalize_entry({"markdown": "x", "sources": [bad_url]}) is None
    kept = normalize_entry({"markdown": "x", "sources": [bad_url, "https://ok.example/a"]})
    assert kept["sources"] == ["https://ok.example/a"]


def test_a_broken_source_url_in_a_hand_edited_facts_file_never_breaks_the_cli(tmp_path, capsys):
    import build_day_plan
    import datetime
    route_dir = tmp_path / "r"
    route_dir.mkdir()
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-3.75, 40.42, 600], [-3.74, 40.43, 640]]},
         "properties": {"name": "R", "mode": "walk", "duration_estimate_hours": 3}}]}))
    (route_dir / "facts.json").write_text(json.dumps({"all": {"transit": {"markdown": "x", "sources": ["http://[::1"]}}}))
    now = datetime.datetime(2026, 6, 20, 12, tzinfo=datetime.timezone.utc)
    code = build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: {"hourly": {"time": []}}, now=now)
    assert code == 0
    assert (route_dir / "day-plan-2026-06-21.md").exists()
    assert "hint: no web-sourced facts recorded for transit" in capsys.readouterr().out
