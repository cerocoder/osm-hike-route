import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.osm_features import OsmFeature
from day_plan.plugins.mountain import MountainPlugin, elevation_stats

SUMMER = datetime.date(2026, 7, 4)
WINTER = datetime.date(2026, 1, 15)


def coords(*elevations):
    return tuple((41.70, 43.25 + i * 0.01, e) for i, e in enumerate(elevations))      # (lon, lat, ele)


def rows(**over):
    base = {"hour": 12, "temp": 12.0, "fzl": 4000.0, "cape": 0.0, "gust": 5.0, "precip": 0.0, "snow_m": 0.0, "code": 1}
    return [{**base, **over} for _ in range(3)]


def run(make_route, fixed_now, elevations, weather_rows=None, features=None, osm_error=None, date=SUMMER, lang="en",
        facts=None, elevation_m=None, folder="route", with_osm=True, weather_source=None):
    route_dir = make_route(coords=coords(*elevations), folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=lambda u: {}, now=fixed_now)
    shared = {}
    if weather_rows is not None:
        shared["weather"] = {"daytime_rows": weather_rows, "rows": weather_rows, "elevation_m": elevation_m,
                             **({"source": weather_source} if weather_source else {})}
    if with_osm:
        shared["osm_features"] = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords],
                                  "error": osm_error}
    return MountainPlugin().run(ctx, shared)


def feature(kind, lat_offset=0.0005, detail=""):
    return OsmFeature(kind, 43.25 + lat_offset, 41.70, "", detail)


def test_a_flat_route_is_not_applicable_and_left_out(make_route, fixed_now):
    section = run(make_route, fixed_now, (100.0, 150.0, 120.0))
    assert section.omit is True and section.markdown == ""


def test_a_route_without_elevations_says_so(make_route, fixed_now):
    section = run(make_route, fixed_now, (None, None))
    assert section.confidence == "no-data" and "no elevation data" in section.markdown and not section.omit


@pytest.mark.parametrize("elevations,applicable", [
    ((100.0, 599.0), True),       # top below 600 m, but a relief of 499 m still makes it a mountain route
    ((100.0, 600.0), True), ((300.0, 640.0), True), ((50.0, 349.0), False), ((50.0, 350.0), True),
    ((50.0, 250.0), False), ((400.0, 700.0), True)])
def test_the_activation_rule_is_600_m_high_or_300_m_relief(make_route, fixed_now, elevations, applicable):
    section = run(make_route, fixed_now, elevations, weather_rows=rows(), folder="r")
    assert (not section.omit) is applicable


def test_elevation_stats():
    assert elevation_stats([(0, 0, 100.0), (0, 0, None), (0, 0, 300.5)]) == (100.0, 300.5, 200.5)
    assert elevation_stats([(0, 0, None), (0, 0)]) is None


def test_header_and_tier_lines(make_route, fixed_now):
    mid = run(make_route, fixed_now, (900.0, 1400.0), weather_rows=rows())
    assert "Route elevation 900–1400 m (relief 500 m)." in mid.markdown
    assert "Above 1500 m" not in mid.markdown and "altitude sickness" not in mid.markdown
    high = run(make_route, fixed_now, (1200.0, 1800.0), weather_rows=rows(), folder="high")
    assert "Above 1500 m" in high.markdown and "altitude sickness" not in high.markdown
    ams = run(make_route, fixed_now, (2000.0, 2700.0), weather_rows=rows(), folder="ams")
    assert "altitude sickness" in ams.markdown and "Oxygen shortage is not a factor below this height" in ams.markdown
    assert not any("3500" in w.text for w in ams.warnings)
    very_high = run(make_route, fixed_now, (3000.0, 3800.0), weather_rows=rows(), folder="vh")
    assert any("3500" in w.text and w.severity == "caution" for w in very_high.warnings)


@pytest.mark.parametrize("scale,severity", [("hiking", None), ("mountain_hiking", None), ("demanding_mountain_hiking", "caution"),
                                            ("alpine_hiking", "danger"), ("difficult_alpine_hiking", "danger")])
def test_path_difficulty_from_osm(make_route, fixed_now, scale, severity):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(),
                  features=[feature("sac", detail="hiking"), feature("sac", 0.001, detail=scale)])
    assert "up to **" in section.markdown and "(2 path segment(s) rated)" in section.markdown
    sac_warnings = [w for w in section.warnings if "terrain" in w.text.lower()]
    assert [w.severity for w in sac_warnings] == ([severity] if severity else [])


def test_loose_ground_and_glaciers_near_the_track(make_route, fixed_now):
    features = [feature("scree"), feature("scree", 0.001), feature("cliff"), feature("bare_rock", 0.5),   # far away
                feature("glacier", 0.005)]
    section = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), features=features)
    assert "scree 2, cliffs 1" in section.markdown and "bare rock" not in section.markdown
    assert "A glacier lies within 5" in section.markdown          # about 550 m
    assert any(w.severity == "caution" and "glacier" in w.text for w in section.warnings)
    far = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), features=[feature("glacier", 0.05)], folder="far")
    assert "glacier" not in far.markdown


def test_osm_problems_are_a_note_and_a_missing_osm_plugin_is_tolerated(make_route, fixed_now):
    down = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(), osm_error="504")
    assert "could not be loaded (504)" in down.markdown
    absent = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(), with_osm=False, folder="absent")
    assert "OpenStreetMap" not in absent.markdown and "Route elevation" in absent.markdown


def test_freezing_level_below_the_top_warns_and_above_does_not(make_route, fixed_now):
    low = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=1800.0))
    assert "Freezing level down to 1800 m (below the highest point, 2400 m)" in low.markdown
    assert any("Freezing level (1800 m)" in w.text and w.severity == "caution" for w in low.warnings)
    marginal = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=2300.0), folder="marginal")
    assert "below the highest point" in marginal.markdown and not any("Freezing level" in w.text for w in marginal.warnings)
    high = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=3500.0), folder="high")
    assert "above the highest point" in high.markdown and not any("Freezing level" in w.text for w in high.warnings)


def test_temperature_at_the_top_uses_the_lapse_rate_from_the_model_elevation(make_route, fixed_now):
    section = run(make_route, fixed_now, (500.0, 2500.0), weather_rows=rows(temp=12.0), elevation_m=500.0)
    assert "About **-1 °C** at the highest point (2500 m)" in section.markdown          # 12 - 6.5 * 2.0
    assert any("Below freezing at the highest point" in w.text for w in section.warnings)
    warm = run(make_route, fixed_now, (500.0, 1500.0), weather_rows=rows(temp=20.0), elevation_m=500.0, folder="warm")
    assert "About **14 °C**" in warm.markdown and not any("Below freezing" in w.text for w in warm.warnings)
    fallback = run(make_route, fixed_now, (500.0, 2500.0), weather_rows=rows(temp=12.0), folder="fb")   # first coordinate elevation
    assert "About **-1 °C**" in fallback.markdown


def test_thunderstorm_risk_by_cape_and_by_forecast(make_route, fixed_now):
    cape = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(cape=1500.0))
    assert "CAPE up to 1500 J/kg" in cape.markdown
    assert [w.severity for w in cape.warnings if "Thunderstorm" in w.text] == ["caution"]
    forecast = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="storm")
    assert "Thunderstorms are forecast" in forecast.markdown
    assert [w.severity for w in forecast.warnings if "Thunderstorm" in w.text] == ["danger"]
    calm = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(cape=900.0), folder="calm")
    assert "Thunderstorm" not in calm.markdown


def test_wind_note_rain_note_and_shade_note(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(gust=14.0, precip=5.0))
    assert "wind will be stronger than the 14 m/s gusts" in section.markdown
    assert "About 15 mm of rain" in section.markdown and any(w.severity == "caution" and "Heavy rain" in w.text for w in section.warnings)
    assert "sun sets behind the ridges" in section.markdown
    gentle = run(make_route, fixed_now, (700.0, 900.0), weather_rows=rows(gust=14.0, precip=0.1), folder="gentle")
    assert "stronger than" not in gentle.markdown and "rain" not in gentle.markdown and "sun sets" not in gentle.markdown


def test_snow_on_steep_ground_points_to_the_avalanche_bulletin(make_route, fixed_now):
    winter = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(snow_m=0.3), date=WINTER)
    assert "avalanche bulletin" in winter.markdown and "https://www.avalanches.org/" in winter.markdown
    assert any(w.severity == "caution" and "avalanche" in w.text for w in winter.warnings)
    summer = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(snow_m=0.0), folder="summer")
    assert "avalanche" not in summer.markdown
    lowland_snow = run(make_route, fixed_now, (300.0, 620.0), weather_rows=rows(snow_m=0.3), date=WINTER, folder="low")
    assert "avalanche" not in lowland_snow.markdown         # top below 1000 m


def test_a_missing_weather_plugin_still_gives_the_terrain_part(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=None, features=[feature("glacier")])
    assert "Route elevation" in section.markdown and "glacier" in section.markdown and "Freezing level" not in section.markdown


def test_regional_facts_are_added_with_sources(make_route, fixed_now):
    fact = {"markdown": "EAWS danger level 3 (considerable) above 2200 m.", "sources": ["https://lawinen.report/x"],
            "warnings": [{"severity": "danger", "text": "Avalanche danger level 3."}]}
    section = run(make_route, fixed_now, (1500.0, 2600.0), weather_rows=rows(), facts={"all": {"mountain": fact}})
    assert "EAWS danger level 3" in section.markdown and "Sources: [lawinen.report](https://lawinen.report/x)" in section.markdown
    assert section.confidence == "web-sourced" and [w.text for w in section.warnings][-1] == "Avalanche danger level 3."


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, (900.0, 2700.0), weather_rows=rows(), lang="ru")
    assert "Высоты маршрута 900–2700 м" in section.markdown and "высотная болезнь" in section.markdown


def test_the_plugin_declares_its_group_title_and_dependencies():
    assert MountainPlugin.title_key == "hz_mountain" and MountainPlugin.depends_on == ("weather", "osm_features")


def test_freezing_level_above_the_top_never_claims_no_snow_or_ice(make_route, fixed_now):
    warm = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=3500.0, temp=15.0), folder="w")
    assert "the model keeps the air above 0 °C at the highest point" in warm.markdown
    assert "no snow or ice" not in warm.markdown
    cold_top = run(make_route, fixed_now, (500.0, 2500.0), weather_rows=rows(fzl=3500.0, temp=12.0), elevation_m=500.0,
                   folder="c")                                  # lapse rate: about -1 C at the top
    assert "About **-1 °C**" in cold_top.markdown
    assert "ice and snow are still possible" in cold_top.markdown and "keeps the air above" not in cold_top.markdown
    near_top = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=2600.0, temp=15.0), folder="n")
    assert "ice and snow are still possible" in near_top.markdown and "keeps the air above" not in near_top.markdown
    ru = run(make_route, fixed_now, (1000.0, 2400.0), weather_rows=rows(fzl=3500.0, temp=15.0), folder="r", lang="ru")
    assert "снега и льда не ожидается" not in ru.markdown and "выше 0 °C" in ru.markdown


def test_all_zero_elevations_are_unknown_elevation_not_a_flat_route(make_route, fixed_now):
    assert elevation_stats([(0, 0, 0.0), (0, 0, 0.0)]) is None
    section = run(make_route, fixed_now, (0.0, 0.0, 0.0))          # the planning skill writes 0.0 for unknown
    assert section.confidence == "no-data" and "no elevation data" in section.markdown and not section.omit


def test_placeholder_zeros_are_ignored_next_to_real_elevations():
    assert elevation_stats([(0, 0, 0.0), (0, 0, 1500.0), (0, 0, 1200.0)]) == (1200.0, 1500.0, 300.0)
    assert elevation_stats([(0, 0, 0.0), (0, 0, 40.0)]) == (0.0, 40.0, 40.0)         # nothing well above sea level: keep


def test_a_route_with_zero_placeholders_still_gets_its_mountain_section(make_route, fixed_now):
    section = run(make_route, fixed_now, (0.0, 1500.0, 1800.0), weather_rows=rows())
    assert "Route elevation 1500–1800 m (relief 300 m)" in section.markdown


def test_a_regional_fact_is_shown_even_without_elevation_data(make_route, fixed_now):
    fact = {"markdown": "The avalanche bulletin for the Caucasus is published daily.", "sources": ["https://example.org/aval"]}
    section = run(make_route, fixed_now, (None, None), facts={"all": {"mountain": fact}})
    assert "no elevation data" in section.markdown and "avalanche bulletin for the Caucasus" in section.markdown
    assert section.confidence == "web-sourced" and "Sources: [example.org](https://example.org/aval)" in section.markdown


def test_thunder_weather_codes_of_a_climatology_day_are_not_a_forecast(make_route, fixed_now):
    climate = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="climate",
                  weather_source="climate")
    assert "Thunderstorms are forecast" not in climate.markdown and not any("Thunderstorm" in w.text for w in climate.warnings)
    forecast = run(make_route, fixed_now, (900.0, 1700.0), weather_rows=rows(code=95), folder="forecast",
                   weather_source="forecast")
    assert "Thunderstorms are forecast" in forecast.markdown
