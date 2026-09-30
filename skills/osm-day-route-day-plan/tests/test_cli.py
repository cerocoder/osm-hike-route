import pytest
import datetime

import build_day_plan



def _text(url):
    """GWIS answers for the CLI tests: a calm fire-weather index, no active fires."""
    if "ecmwf.query" in url:
        return "<table id='main'><tr><td>Fire Weather Index (FWI)</td><td>9.5</td></tr></table>"
    return ""


def test_cli_writes_plan_file_and_reports_path(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "en", "--departure", "Waterloo",
                                "--start", "09:00"], http=lambda url: weather_response(), http_text=_text, now=fixed_now)
    assert code == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "From: Waterloo" in text
    assert "estimated finish 14:00" in text
    assert "wrote" in capsys.readouterr().out


def test_cli_overwrites_the_same_date_and_keeps_other_dates(make_route, weather_response, fixed_now):
    route_dir = make_route()
    http = lambda url: weather_response()  # noqa: E731
    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-22"], http=lambda url: weather_response(date="2026-06-22"),
                        http_text=_text, now=fixed_now)
    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=http, http_text=_text, now=fixed_now)
    assert (route_dir / "day-plan-2026-06-22.md").exists()
    assert "Главное на день" in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")


def test_cli_drops_departure_that_looks_like_a_street_address(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21", "--departure", "Baker Street 221B"],
                        http=lambda url: weather_response(), http_text=_text, now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "Baker" not in text and "From:" not in text
    assert "street address" in capsys.readouterr().err


def test_coarse_departure_keeps_plain_city_or_station():
    assert build_day_plan.coarse_departure("  Madrid, Atocha ") == ("Madrid, Atocha", False)
    assert build_day_plan.coarse_departure(None) == (None, False)


def test_cli_rejects_bad_date_and_missing_route(make_route, tmp_path, capsys):
    assert build_day_plan.main([str(make_route()), "21-06-2026"]) == 1
    assert build_day_plan.main([str(tmp_path / "nope"), "2026-06-21"]) == 1
    assert "not found" in capsys.readouterr().err


def test_plan_written_by_cli_is_found_by_glob_used_in_show(make_route, weather_response, fixed_now):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21"], http=lambda url: weather_response(), http_text=_text, now=fixed_now)
    assert [p.name for p in route_dir.glob("day-plan-????-??-??.md")] == ["day-plan-2026-06-21.md"]


# ---- plan 2: transit and points-of-interest sections, web-fact hints ------------------------------

def _web(weather_response, date="2026-06-21"):
    def http(url):
        if "nominatim" in url:
            return {"address": {"country_code": "es"}}
        if "date.nager.at" in url:
            return []
        if "overpass" in url:
            return {"elements": [{"tags": {"route": "bus", "ref": "41", "from": "Atocha", "to": "Colonia"}}]}
        return weather_response(date=date)
    return http


def _route_with_points(make_route_with_points):
    return make_route_with_points([
        ("Lago", "access", -3.7275, 40.4247, {"role": "start", "opening_hours": "Mo-Su 06:00-23:00"}),
        ("Museo", "sight", -3.74, 40.43, {"opening_hours": "Tu-Su 10:00-18:00"}),
    ])


def test_default_plan_has_getting_there_and_points_of_interest(make_route_with_points, weather_response, fixed_now):
    route_dir = _route_with_points(make_route_with_points)
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Summary", "## Daylight", "## Weather by hour", "## Getting there", "## Points of interest",
                        "## Hazards", "## Mobile coverage"]
    subheadings = [line for line in text.splitlines() if line.startswith("### ")]
    assert subheadings == ["### Radiation", "### Mountain hazards", "### Fire danger", "### Ticks and biting insects",
                           "### Air: pollen and pollution"]
    assert "| Lago | start |" in text and "| Museo | sight | 10:00–18:00 |" in text and "| Lago | 41 | bus |" in text
    assert ("<!-- plugins: weather 1, light 1, osm_features 1, radiation 1, snow_history 1, trail_passability 1, transit 1, poi_hours 1, mountain 1, fire 1, "
            "bio_hazards 1, air 1, people_hazards 1, cell_coverage 1 -->") in text


def test_hint_asks_for_web_facts_until_they_are_recorded(make_route_with_points, weather_response, fixed_now, capsys):
    route_dir = _route_with_points(make_route_with_points)
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit, poi_hours on 2026-06-21" in out and "record_fact.py" in out

    import record_fact
    for plugin in ("transit", "poi_hours"):
        record_fact.record(route_dir, "2026-06-21", plugin, "Found on the web.", ["https://example.org/x"])
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    out2 = capsys.readouterr().out
    assert "hint:" not in out2
    assert "Found on the web." in (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")


def test_hint_mentions_only_what_the_route_needs(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()                        # a route without points of interest
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    assert "recorded for transit on" in capsys.readouterr().out


def test_a_broken_overpass_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now):
    from day_plan.http import HttpError
    route_dir = _route_with_points(make_route_with_points)
    inner = _web(weather_response)

    def http(url):
        if "overpass" in url:
            raise HttpError("504")
        return inner(url)

    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "OSM lists no lines for these access points" in text and "## Points of interest" in text


def test_garbage_facts_json_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
    import json
    route_dir = _route_with_points(make_route_with_points)
    (route_dir / "facts.json").write_text(json.dumps({"2026-06-21": {"transit": {"markdown": "UNSOURCED CLAIM"}, "poi_hours": "not a dict"}, "all": ["x"]}), encoding="utf-8")
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "UNSOURCED CLAIM" not in text
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit, poi_hours on 2026-06-21" in out


def test_facts_json_as_array_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
    route_dir = _route_with_points(make_route_with_points)
    (route_dir / "facts.json").write_text("[]", encoding="utf-8")
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit" in out


def test_facts_json_as_string_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
    route_dir = _route_with_points(make_route_with_points)
    (route_dir / "facts.json").write_text('"just a string"', encoding="utf-8")
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit" in out


def test_facts_json_with_bad_encoding_does_not_break_the_plan(make_route_with_points, weather_response, fixed_now, capsys):
    route_dir = _route_with_points(make_route_with_points)
    (route_dir / "facts.json").write_bytes(b"\xff\xfe\x00")
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now) == 0
    out = capsys.readouterr().out
    assert "hint: no web-sourced facts recorded for transit" in out


def _web_country(weather_response, country):
    def http(url):
        if "nominatim" in url:
            return {"address": {"country_code": country}}
        if "date.nager.at" in url:
            return []
        if "overpass" in url:
            return {"elements": []}
        return weather_response()
    return http


def test_russian_route_hint_asks_for_a_calendar_fact_until_one_is_recorded(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
    out = capsys.readouterr().out
    assert "recorded for transit, calendar on 2026-06-21" in out
    assert ("calendar: check in the official calendar whether the date is a public holiday, a transferred day off "
            "or a working Saturday, and record it with --plugin calendar --day-type ...") in out

    import record_fact
    record_fact.record(route_dir, "2026-06-21", "calendar", "", ["https://example.org/x"], day_type="weekend")
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
    out2 = capsys.readouterr().out
    assert "recorded for transit on" in out2 and "calendar" not in out2


def test_an_all_scope_calendar_fact_does_not_silence_the_russian_hint(make_route, weather_response, fixed_now, capsys):
    import json
    route_dir = make_route()
    (route_dir / "facts.json").write_text(json.dumps({"all": {"calendar": {
        "day_type": "workday", "sources": ["https://example.org/x"]}}}), encoding="utf-8")
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "ru"), http_text=_text, now=fixed_now)
    assert "calendar: check in the official calendar" in capsys.readouterr().out


def test_a_route_outside_russia_never_mentions_the_calendar(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web_country(weather_response, "es"), http_text=_text, now=fixed_now)
    assert "calendar" not in capsys.readouterr().out


# ---- plan 3a: hazards ---------------------------------------------------------------------------

def test_the_hazard_group_is_assembled_and_the_data_plugin_stays_invisible(make_route_with_points, weather_response, fixed_now):
    route_dir = _route_with_points(make_route_with_points)
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "Fire Weather Index (FWI, ECMWF model via the Copernicus GWIS service): **9.5** — low" in text
    assert "Route elevation 600–640 m (relief 40 m)." in text
    assert "## OSM" not in text and "osm_features" not in "\n".join(l for l in text.splitlines() if l.startswith("#"))
    assert text.index("### Mountain hazards") < text.index("### Fire danger") < text.index("### Air: pollen and pollution")


def test_the_optional_hazard_hint_lists_only_what_applies_and_disappears_when_recorded(
        make_route_with_points, make_route, weather_response, fixed_now, capsys):
    import record_fact
    route_dir = _route_with_points(make_route_with_points)
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    out = capsys.readouterr().out
    assert "hint (optional): regional facts would improve the hazard sections: fire, mountain, bio_hazards, people_hazards" in out
    for plugin in ("fire", "mountain", "bio_hazards", "people_hazards"):
        record_fact.record(route_dir, "2026-06-21", plugin, "Local note.", ["https://example.org/x"])
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    assert "hint (optional)" not in capsys.readouterr().out
    flat = make_route(folder="flat", coords=((-3.75, 40.42, 100.0), (-3.74, 40.43, 120.0)))
    build_day_plan.main([str(flat), "2026-12-15"], http=_web(weather_response, date="2026-12-15"), http_text=_text,
                        now=fixed_now)
    winter = capsys.readouterr().out
    assert "regional facts would improve the hazard sections: fire, people_hazards — " in winter


def test_record_fact_accepts_the_hazard_plugins_and_their_warnings(tmp_path):
    import record_fact
    for plugin in ("fire", "mountain", "bio_hazards", "air"):
        entry = record_fact.record(tmp_path, "all", plugin, "Note.", ["https://example.org/x"], warnings=[
            {"severity": "caution", "text": "Careful."}])
        assert entry["warnings"] == [{"severity": "caution", "text": "Careful."}]
    with pytest.raises(ValueError, match="fire plugin does not use --last-departure"):
        record_fact.record(tmp_path, "all", "fire", "Note.", ["https://example.org/x"], last_departure="21:00")


def test_a_failing_hazard_plugin_never_breaks_the_rest_of_the_plan(make_route_with_points, weather_response, fixed_now,
                                                                     capsys):
    route_dir = _route_with_points(make_route_with_points)

    def broken_text(url):
        raise RuntimeError("GWIS exploded")

    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=broken_text,
                               now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "## Getting there" in text and "### Fire danger" in text and "could not be built" in text
    assert "plugin fire failed" in capsys.readouterr().err


# ---- plan 3b: radiation, people, coverage ----------------------------------------------------------------

BRYANSK_ROUTE = ((31.90, 52.54, 150.0), (31.95, 52.56, 150.0))


def test_a_route_in_a_contaminated_district_shows_radiation_first_and_warns_in_the_summary(
        make_route, weather_response, fixed_now):
    route_dir = make_route(coords=BRYANSK_ROUTE)
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
                               now=fixed_now) == 0
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    subheadings = [line for line in text.splitlines() if line.startswith("### ")]
    assert subheadings[0] == "### Radiation"
    summary = text.split("## Daylight")[0]
    assert "South-western Bryansk region" in summary and "Do not pick mushrooms or berries" in summary
    assert text.rstrip().split("## ")[-1].startswith("Mobile coverage")


def test_a_route_outside_the_registry_area_has_no_radiation_part(make_route, weather_response, fixed_now):
    route_dir = make_route(coords=((151.20, -33.86, 20.0), (151.21, -33.85, 25.0)))
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "### Radiation" not in text and "radiation registry" not in text


def test_record_fact_accepts_people_hazards_and_the_plan_shows_it(make_route, weather_response, fixed_now):
    import record_fact
    route_dir = make_route()
    record_fact.record(route_dir, "all", "people_hazards", "A permit is needed in the border zone.",
                       ["https://example.org/permit"], warnings=[{"severity": "caution", "text": "Border permit needed."}])
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text, now=fixed_now)
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "### People and access" in text and "A permit is needed in the border zone." in text
    assert "Border permit needed." in text.split("## Daylight")[0]
    with pytest.raises(ValueError, match="does not use --last-departure"):
        record_fact.record(route_dir, "all", "people_hazards", "x", ["https://example.org/x"], last_departure="21:00")


def test_a_failing_hint_never_fails_the_written_plan(make_route, weather_response, fixed_now, monkeypatch, capsys):
    def boom(ctx):
        raise RuntimeError("hint exploded")
    monkeypatch.setattr(build_day_plan, "optional_hazard_facts", boom)
    route_dir = make_route()
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
                               now=fixed_now) == 0
    assert (route_dir / "day-plan-2026-06-21.md").exists() and "hint (optional)" not in capsys.readouterr().out


def test_a_failing_missing_facts_check_never_fails_the_written_plan(make_route, weather_response, fixed_now,
                                                                     monkeypatch):
    def boom(ctx):
        raise RuntimeError("missing facts exploded")
    monkeypatch.setattr(build_day_plan, "missing_web_facts", boom)
    route_dir = make_route()
    assert build_day_plan.main([str(route_dir), "2026-06-21"], http=_web(weather_response), http_text=_text,
                               now=fixed_now) == 0
    assert (route_dir / "day-plan-2026-06-21.md").exists()


# ---- winter passability, end to end ------------------------------------------------------------------------------------

WINTER = "2026-12-20"
WINTER_NOW = datetime.datetime(2026, 12, 18, 12, 0, tzinfo=datetime.timezone.utc)
ROUTE_SEGMENTS = [{"from": 0, "to": 2, "way_id": 1, "highway": "track", "surface": "gravel"},
                  {"from": 2, "to": 4, "way_id": 2, "highway": "residential", "surface": "asphalt"}]


def _snow_history(date, snow_m=0.30, temp=-8.0):
    start = datetime.date.fromisoformat(date) - datetime.timedelta(days=14)
    times = [f"{start + datetime.timedelta(days=d):%Y-%m-%d}T{h:02d}:00" for d in range(15) for h in range(24)]
    n = len(times)
    return {"elevation": 250.0, "hourly": {
        "time": times, "temperature_2m": [temp] * n, "dew_point_2m": [temp - 2] * n, "precipitation": [0.0] * n,
        "rain": [0.0] * n, "snowfall": [0.0] * n, "snow_depth": [snow_m] * n, "cloud_cover": [80] * n,
        "weather_code": [3] * n}}


def _winter_web(weather_response, date=WINTER, snow_m=0.30, temp=-8.0):
    def http(url):
        if "nominatim" in url:
            return {"address": {"country_code": "ru"}}
        if "date.nager.at" in url:
            return []
        if "overpass" in url:
            return {"elements": []}
        if "snowfall" in url:                       # the 14-day history of the snow estimate
            return _snow_history(date, snow_m, temp)
        return weather_response(date=date, temperature_2m=temp)
    return http


def _hint_list(output: str) -> str:
    """The plugin names the optional hint asks for ('fire, bio_hazards, ...'), without the explanations after it."""
    marker = "regional facts would improve the hazard sections: "
    return output.split(marker)[1].split(" — ")[0] if marker in output else ""


def _winter_route(tmp_path, mode="walk", style=None, folder="winter", segments=ROUTE_SEGMENTS):
    import json
    route_dir = tmp_path / folder
    route_dir.mkdir()
    coords = [[60.6, 56.84 + i * 0.001, 250.0 + 2 * i] for i in range(5)]
    props = {"name": "Зимний", "mode": mode, "style": style, "distance_km": 0.4, "duration_estimate_hours": 1.0}
    if segments is not None:
        props["segments"] = segments
    features = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [60.6, 56.842]},
                 "properties": {"name": "Озеро", "type": "viewpoint"}}]
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                                             encoding="utf-8")
    return route_dir


def test_a_winter_route_gets_the_passability_section_second_after_radiation(tmp_path, weather_response, capsys):
    route_dir = _winter_route(tmp_path)
    assert build_day_plan.main([str(route_dir), WINTER], http=_winter_web(weather_response), http_text=_text,
                               now=WINTER_NOW) == 0
    text = (route_dir / f"day-plan-{WINTER}.md").read_text(encoding="utf-8")
    subheadings = [line for line in text.splitlines() if line.startswith("### ")]
    assert subheadings[:2] == ["### Radiation", "### Trail and road passability"]
    assert "Assessed for: **on foot**." in text and "| Start → Озеро | 0.2 | gravel 100 % |" in text
    assert "| not recommended |" in text and "| passable |" in text
    assert "*Data fetched 2026-12-18 12:00 UTC (" in text and "Mode: on foot" in text
    summary = text.split("## Daylight")[0]
    assert "Not recommended (on foot):" in summary
    assert "trail_conditions" in _hint_list(capsys.readouterr().out)


def test_the_bicycle_route_says_cycling_and_studded_tires(tmp_path, weather_response):
    route_dir = _winter_route(tmp_path, mode="bike", style="leisure", folder="bike")
    build_day_plan.main([str(route_dir), WINTER], http=_winter_web(weather_response), http_text=_text, now=WINTER_NOW)
    text = (route_dir / f"day-plan-{WINTER}.md").read_text(encoding="utf-8")
    assert "Mode: cycling (leisure)" in text and "Assessed for: **cycling (leisure)**. Studded tires are assumed" in text


def test_a_warm_bare_day_has_no_passability_section_and_no_hint(tmp_path, weather_response, capsys):
    route_dir = _winter_route(tmp_path, folder="warm")
    build_day_plan.main([str(route_dir), "2026-06-21"], http=_winter_web(weather_response, date="2026-06-21",
                                                                          snow_m=0.0, temp=18.0),
                        http_text=_text, now=datetime.datetime(2026, 6, 20, 12, 0, tzinfo=datetime.timezone.utc))
    text = (route_dir / "day-plan-2026-06-21.md").read_text(encoding="utf-8")
    assert "### Trail and road passability" not in text and "trail_conditions" not in _hint_list(capsys.readouterr().out)


def test_an_old_archive_without_road_data_is_told_to_be_re_planned(tmp_path, weather_response):
    route_dir = _winter_route(tmp_path, folder="old", segments=None)
    build_day_plan.main([str(route_dir), WINTER], http=_winter_web(weather_response), http_text=_text, now=WINTER_NOW)
    text = (route_dir / f"day-plan-{WINTER}.md").read_text(encoding="utf-8")
    assert "has no road data" in text and "Re-plan the route" in text
    assert "Sections without data:" in text.split("## Daylight")[0] and "Trail and road passability" in text.split("## Daylight")[0]


def test_record_fact_accepts_trail_conditions_and_the_hint_disappears(tmp_path, weather_response, capsys):
    import record_fact
    route_dir = _winter_route(tmp_path, folder="facts")
    record_fact.record(route_dir, "all", "trail_conditions", "The lake path is groomed on weekends.",
                       ["https://example.org/report"], warnings=[{"severity": "caution", "text": "Ice at the lake."}])
    build_day_plan.main([str(route_dir), WINTER], http=_winter_web(weather_response), http_text=_text, now=WINTER_NOW)
    out = capsys.readouterr().out
    text = (route_dir / f"day-plan-{WINTER}.md").read_text(encoding="utf-8")
    assert "trail_conditions" not in _hint_list(out) and _hint_list(out) != ""
    assert "The lake path is groomed on weekends." in text and "Ice at the lake." in text.split("## Daylight")[0]
    with pytest.raises(ValueError, match="does not use --last-departure"):
        record_fact.record(route_dir, "all", "trail_conditions", "x", ["https://example.org/x"], last_departure="21:00")



# ---- progress lines ------------------------------------------------------------------------------------------------------

def test_the_cli_prints_one_progress_line_per_plugin_in_the_users_language(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "ru"], http=lambda url: weather_response(),
                        http_text=_text, now=fixed_now, progress=build_day_plan.AUTO_PROGRESS)
    lines = capsys.readouterr().err.splitlines()
    starts = [l for l in lines if l.startswith("[")]
    total = len(build_day_plan.default_plugins())
    assert len(starts) == total and starts[0] == f"[1/{total}] Погода …"
    assert any(l.startswith("[") and "Световой день" in l for l in lines)
    assert sum(1 for l in lines if l.lstrip().startswith("✓")) >= total - 2
    assert not any(word in "\n".join(lines) for word in ("Weather", "Daylight", "Mobile coverage"))


def test_quiet_and_the_default_print_no_progress(make_route, weather_response, fixed_now, capsys):
    route_dir = make_route()
    http = lambda url: weather_response()  # noqa: E731
    build_day_plan.main([str(route_dir), "2026-06-21", "--quiet"], http=http, http_text=_text, now=fixed_now,
                        progress=build_day_plan.AUTO_PROGRESS)
    assert "[1/" not in capsys.readouterr().err
    build_day_plan.main([str(route_dir), "2026-06-21"], http=http, http_text=_text, now=fixed_now)
    assert "[1/" not in capsys.readouterr().err


def test_a_failing_plugin_is_a_failed_progress_line_and_the_plan_still_builds(make_route, weather_response, fixed_now,
                                                                                capsys):
    from day_plan.base import SectionPlugin

    class Broken(SectionPlugin):
        plugin_id, section_id = "fire", "hazards"

        def run(self, ctx, shared):
            raise RuntimeError("HTTP 503")

    route_dir = make_route()
    code = build_day_plan.main([str(route_dir), "2026-06-21", "--lang", "es"], http=lambda url: weather_response(),
                               http_text=_text, now=fixed_now, plugins=[Broken()],
                               progress=build_day_plan.AUTO_PROGRESS)
    err = capsys.readouterr().err
    assert code == 0 and "[1/1] Peligro de incendio …" in err and "✗" in err and "RuntimeError: HTTP 503" in err


def test_every_default_plugin_has_a_name_in_every_language():
    from day_plan.i18n import LANGS, STRINGS
    for plugin in build_day_plan.default_plugins():
        for lang in LANGS:
            assert f"pl_{plugin.plugin_id}" in STRINGS[lang], (plugin.plugin_id, lang)
