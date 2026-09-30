import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.plugins.trail_passability import TrailPassabilityPlugin

DATE = datetime.date(2026, 12, 20)
TODAY_NOW = datetime.datetime(2026, 12, 18, 12, 0, tzinfo=datetime.timezone.utc)
SEGMENTS = [{"from": 0, "to": 2, "way_id": 1, "highway": "track", "surface": "gravel"},
            {"from": 2, "to": 4, "way_id": 2, "highway": "residential", "surface": "asphalt"}]
COORDS = [[60.6, 56.84 + i * 0.001, 250.0 + 2 * i] for i in range(5)]


def archive(tmp_path, mode="walk", style=None, segments=SEGMENTS, points=(), folder="route", facts=None, coords=None):
    route_dir = tmp_path / folder
    route_dir.mkdir()
    line = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords or COORDS},
            "properties": {"name": "T", "mode": mode, "style": style,
                           **({"segments": segments} if segments is not None else {})}}
    features = [line] + [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [60.6, 56.84 + i * 0.001]},
                          "properties": {"name": name, "type": kind, **({"role": role} if role else {})}}
                         for name, kind, i, role in points]
    (route_dir / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                                             encoding="utf-8")
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return route_dir


def hist_rows(days=15, **columns):
    base = {"temp": -8.0, "dew": -10.0, "precip": 0.0, "rain": 0.0, "snowfall": 0.0, "snow_cm": 30.0, "cloud": 80,
            "code": 3}
    rows = []
    for i in range(days * 24):
        row = {"hour": i % 24, "date": f"d{i // 24}"}
        for key, default in base.items():
            spec = columns.get(key, default)
            row[key] = spec(i) if callable(spec) else spec
        rows.append(row)
    return rows


def shared_of(rows, source="forecast", error=None, elevation=250.0, weather_rows=None, sun=(480, 960)):
    n = len(rows)
    return {
        "weather": {"source": source, "daytime_rows": weather_rows if weather_rows is not None
                    else [{"hour": h} for h in range(8, 17)]},
        "light": {"sunrise_local_min": sun[0], "sunset_local_min": sun[1]},
        "snow_history": {"rows": rows, "day_start": n - 24 if n else None, "day_end": n - 1 if n else None,
                         "elevation_m": elevation, "error": error, "source": source, "skipped": False},
    }


def run(tmp_path, shared, lang="en", **archive_args):
    ctx = build_context(archive(tmp_path, **archive_args), DATE, lang=lang, http=lambda url: {}, now=TODAY_NOW)
    return TrailPassabilityPlugin().run(ctx, shared)


def test_deep_snow_makes_the_uncleared_leg_not_recommended_and_the_street_leg_passable(tmp_path):
    points = [("Station", "access", 0, "start"), ("Lake", "viewpoint", 2, None), ("Bus stop", "access", 4, "end")]
    section = run(tmp_path, shared_of(hist_rows()), points=points)
    md = section.markdown
    assert "Assessed for: **on foot**." in md and "Studded" not in md
    assert "| Leg | km | Surfaces | Snow, cm | Ice | Verdict |" in md
    assert "| Station → Lake | 0.2 | gravel 100 % | 30 | none | not recommended |" in md
    assert "| Lake → Bus stop | 0.2 | asphalt 100 % | 30 | none | passable |" in md
    assert "Snow at the route's level: up to **30 cm** (the model's own value: 30 cm)." in md
    assert "Snowshoes or skis where the snow is 20 cm or deeper" in md
    assert [(w.severity) for w in section.warnings] == ["danger"]
    assert "Station → Lake" in section.warnings[0].text and "Lake → Bus stop" not in section.warnings[0].text
    assert section.confidence == "derived" and section.shared == {"trail_applies": True}
    assert section.sources == ["https://open-meteo.com/"]


def test_a_bicycle_is_assessed_with_studded_tires_and_its_own_profile(tmp_path):
    section = run(tmp_path, shared_of(hist_rows()), mode="bike", style="sport")
    md = section.markdown
    assert "Assessed for: **cycling (sport)**. Studded tires are assumed" in md
    assert "Studded tires do not help in deep snow" in md and "Snowshoes" not in md
    assert section.warnings[0].severity == "danger" and "cycling (sport)" in section.warnings[0].text
    assert "on foot" not in md


def test_shallow_snow_is_difficult_not_forbidden_and_counts_the_difficult_legs(tmp_path):
    rows = hist_rows(snow_cm=10.0)
    section = run(tmp_path, shared_of(rows), points=[("A", "access", 0, "start"), ("B", "viewpoint", 2, None)])
    assert [w.severity for w in section.warnings] == ["caution"]
    assert "Difficult going on 1 of 2 legs: A → B." in section.warnings[0].text
    assert "| A → B | 0.2 | gravel 100 % | 10 | none | difficult |" in section.markdown


def test_a_warm_bare_autumn_day_leaves_the_section_out(tmp_path):
    rows = hist_rows(temp=10.0, dew=5.0, snow_cm=0.0)
    section = run(tmp_path, shared_of(rows))
    assert section.omit is True and section.markdown == "" and section.warnings == []


def test_frost_without_snow_shows_the_section_with_its_ice_and_no_penalty_for_the_walker(tmp_path):
    rows = hist_rows(temp=lambda i: -1.0 if i % 24 < 7 else 3.0, dew=lambda i: -1.5 if i % 24 < 7 else 1.0,
                     snow_cm=0.0, cloud=10)
    section = run(tmp_path, shared_of(rows))
    assert section.omit is False and "| passable |" in section.markdown and section.warnings == []
    assert "Ice on cleared roads: **none**, on uncleared paths: **none**" in section.markdown       # dark hours are outside
    early = run(tmp_path, shared_of(rows, weather_rows=[{"hour": h} for h in range(3, 10)]), folder="early")
    assert "Ice on cleared roads: **moderate**, on uncleared paths: **none**" in early.markdown      # a start before dawn
    assert early.warnings == [] and "| passable |" in early.markdown


def test_freezing_rain_makes_a_steep_walk_not_recommended(tmp_path):
    rows = hist_rows(temp=-2.0, snow_cm=0.0, code=lambda i: 66 if i >= 15 * 24 - 12 else 3)
    steep = [[60.6, 56.84 + i * 0.001, 250.0 + 25.0 * i] for i in range(5)]          # about 22 % grade
    section = run(tmp_path, shared_of(rows), coords=steep)
    assert "Ice on cleared roads: **high**" in section.markdown and section.warnings[0].severity == "danger"
    assert section.warnings[0].text == "Not recommended (on foot): Whole route — ice: high."
    assert "Micro-spikes for the icy parts" in section.markdown
    flat = run(tmp_path, shared_of(rows), folder="flat")
    assert [(w.severity, w.text) for w in flat.warnings] == [("caution", "Difficult going on 1 of 1 legs: Whole route.")]


def test_a_bicycle_on_studs_shrugs_off_ice_alone(tmp_path):
    rows = hist_rows(temp=-2.0, snow_cm=0.0, code=lambda i: 66 if i >= 15 * 24 - 12 else 3)
    section = run(tmp_path, shared_of(rows), mode="bike", style="leisure")
    assert section.warnings == [] and "| passable |" in section.markdown


def test_the_snow_is_corrected_for_the_elevation_of_the_legs(tmp_path):
    rows = hist_rows(temp=1.5, snowfall=0.3, snow_cm=0.0)           # the model level melts, 1 000 m up snow sticks
    low = run(tmp_path, shared_of(rows, elevation=250.0), folder="same")
    assert low.omit is True or "up to **0 cm**" in low.markdown
    high_coords = [[60.6, 56.84 + i * 0.001, 1250.0] for i in range(5)]
    high = run(tmp_path, shared_of(rows, elevation=250.0), folder="high", coords=high_coords)
    assert high.omit is False and "up to **" in high.markdown and "up to **0 cm**" not in high.markdown


def test_an_old_archive_without_road_data_says_so_when_snow_makes_it_relevant(tmp_path):
    section = run(tmp_path, shared_of(hist_rows()), segments=None)
    assert section.confidence == "no-data" and "has no road data" in section.markdown and "Re-plan the route" in section.markdown
    assert section.shared == {"trail_applies": True} and section.warnings == []
    quiet = run(tmp_path, shared_of(hist_rows(temp=10.0, dew=5.0, snow_cm=0.0)), segments=None, folder="quiet")
    assert quiet.omit is True


def test_parts_of_the_route_without_road_data_are_reported_and_judged_as_uncleared_soft_paths(tmp_path):
    bare = [{"from": 0, "to": 4, "way_id": 9}]
    section = run(tmp_path, shared_of(hist_rows(snow_cm=10.0)), segments=bare)
    assert "For 100 % of the route the archive has no road data" in section.markdown
    assert section.warnings[0].severity == "caution" and "| difficult |" in section.markdown


def test_untagged_surfaces_are_reported_when_most_of_the_route_is_assumed(tmp_path):
    untagged = [{"from": 0, "to": 4, "way_id": 9, "highway": "track"}]
    section = run(tmp_path, shared_of(hist_rows(snow_cm=10.0)), segments=untagged)
    assert "The surface is not tagged on 100 % of the route" in section.markdown


def test_a_weather_history_failure_is_a_no_data_line_in_the_cold_season_and_silent_in_summer(tmp_path):
    shared = shared_of([], error="HTTP Error 503")
    section = run(tmp_path, shared)
    assert section.confidence == "no-data" and "could not be loaded (HTTP Error 503)" in section.markdown
    summer = datetime.date(2026, 7, 10)
    ctx = build_context(archive(tmp_path, folder="summer"), summer, http=lambda url: {}, now=TODAY_NOW)
    assert TrailPassabilityPlugin().run(ctx, shared).omit is True


def test_beyond_the_forecast_horizon_the_cold_season_gets_a_reason_and_summer_nothing(tmp_path):
    shared = shared_of([], source="climate")
    assert "no forecast this far ahead" in run(tmp_path, shared).markdown.lower().replace("there is ", "")
    summer = datetime.date(2027, 7, 10)
    ctx = build_context(archive(tmp_path, folder="summer"), summer, http=lambda url: {}, now=TODAY_NOW)
    assert TrailPassabilityPlugin().run(ctx, shared).omit is True
    skipped = {**shared_of([]), "snow_history": {"rows": [], "source": "forecast", "skipped": True, "error": None}}
    assert run(tmp_path, skipped, folder="skipped").omit is True


def test_a_mode_that_is_not_assessed_is_left_out(tmp_path):
    assert run(tmp_path, shared_of(hist_rows()), mode="ski").omit is True


FACT = {"markdown": "The park path by the lake is groomed by volunteers on weekends.",
        "sources": ["https://example.org/report"],
        "warnings": [{"severity": "caution", "text": "Ice on the lake path per a report of 12 Dec."}]}


def test_a_recorded_fact_is_shown_with_its_sources_and_warnings_and_never_changes_the_verdict(tmp_path):
    plain = run(tmp_path, shared_of(hist_rows()), folder="plain")
    with_fact = run(tmp_path, shared_of(hist_rows()), folder="fact", facts={"all": {"trail_conditions": FACT}})
    assert "groomed by volunteers" in with_fact.markdown and "Reports of the current season" in with_fact.markdown
    assert "Sources: [example.org](https://example.org/report)" in with_fact.markdown
    assert with_fact.confidence == "web-sourced" and "https://example.org/report" in with_fact.sources
    assert [w.text for w in with_fact.warnings][:1] == [plain.warnings[0].text]
    assert with_fact.warnings[-1].text.startswith("Ice on the lake path")
    assert "| not recommended |" in with_fact.markdown


def test_a_fact_keeps_the_section_alive_when_the_computation_says_nothing_applies(tmp_path):
    rows = hist_rows(temp=10.0, dew=5.0, snow_cm=0.0)
    section = run(tmp_path, shared_of(rows), facts={"all": {"trail_conditions": FACT}})
    assert section.omit is False and "groomed by volunteers" in section.markdown and section.confidence == "web-sourced"
    assert "| Leg |" not in section.markdown


def test_a_fact_without_a_source_is_ignored(tmp_path):
    bad = {"markdown": "Looks icy.", "sources": []}
    section = run(tmp_path, shared_of(hist_rows(temp=10.0, dew=5.0, snow_cm=0.0)), facts={"all": {"trail_conditions": bad}})
    assert section.omit is True


def test_russian_text(tmp_path):
    points = [("Станция", "access", 0, "start"), ("Озеро", "viewpoint", 2, None)]
    section = run(tmp_path, shared_of(hist_rows()), lang="ru", points=points)
    md = section.markdown
    assert "Оценка для: **пешком**." in md and "| Участок | км | Покрытия | Снег, см | Лёд | Вердикт |" in md
    assert "| Станция → Озеро | 0.2 | gravel 100 % | 30 | нет | не рекомендуется |" in md
    assert "Снегоступы или лыжи" in md and section.warnings[0].text.startswith("Не рекомендуется (пешком): Станция → Озеро")
    assert "Estimate" not in md and "Leg" not in md


def test_a_route_without_points_is_one_whole_route_leg(tmp_path):
    section = run(tmp_path, shared_of(hist_rows()))
    assert "| Whole route |" in section.markdown


def test_the_planned_window_comes_from_the_weather_plugins_daytime_hours(tmp_path):
    section = run(tmp_path, shared_of(hist_rows(), weather_rows=[{"hour": h} for h in range(10, 14)]))
    assert "(10:00–14:00)" in section.markdown
    default = run(tmp_path, shared_of(hist_rows(), weather_rows=[]), folder="default")
    assert "(06:00–20:00)" in default.markdown
