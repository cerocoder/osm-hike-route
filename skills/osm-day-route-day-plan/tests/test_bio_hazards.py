import datetime
import json

import pytest

from day_plan.context import build_context
from day_plan.osm_features import OsmFeature
from day_plan.plugins.bio_hazards import (
    BioHazardsPlugin, blackfly_band, horsefly_band, hour_ranges, in_season, mosquito_band, tick_band,
)

JULY = datetime.date(2026, 7, 4)
JANUARY = datetime.date(2026, 1, 15)
APRIL = datetime.date(2026, 4, 10)
ROUTE = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))
SUNRISE, SUNSET = 4 * 60 + 30, 22 * 60 + 30        # a northern summer day


def rows(hours=range(5, 22), **over):
    base = {"temp": 20.0, "wind": 1.0, "rh": 60, "cloud": 20}
    return [{"hour": h, **base, **over} for h in hours]


def water(kind="water", dlat=0.001, detail=""):
    return OsmFeature(kind, 56.84 + dlat, 60.60, "", detail)


def run(make_route, fixed_now, weather_rows, mean=18.0, features=None, error=None, date=JULY, lang="en", facts=None,
        coords=ROUTE, light=True, with_osm=True, folder="route"):
    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=lambda u: {}, now=fixed_now)
    shared = {"weather": {"daytime_rows": weather_rows, "rows": weather_rows, "daily_mean_temp": mean}}
    if light:
        shared["light"] = {"sunrise_local_min": SUNRISE, "sunset_local_min": SUNSET}
    if with_osm:
        shared["osm_features"] = {"features": features or [], "samples": [(c[1], c[0]) for c in ctx.coords], "error": error}
    return BioHazardsPlugin().run(ctx, shared)


# ---- pure helpers ------------------------------------------------------------------------------
@pytest.mark.parametrize("mean,band", [(-5, 0), (4.9, 0), (5.0, 1), (6.9, 1), (7.0, 2), (18.0, 2), (25.0, 2), (26.0, 1)])
def test_tick_bands(mean, band):
    assert tick_band(mean) == band


def test_mosquito_bands():
    assert mosquito_band({"temp": 9.0, "wind": 0.5}, False) == 0
    assert mosquito_band({"temp": 20.0, "wind": 4.0}, False) == 0                  # wind suppresses
    assert mosquito_band({"temp": 12.0, "wind": 1.0}, False) == 1
    assert mosquito_band({"temp": 20.0, "wind": 1.0}, False) == 2
    assert mosquito_band({"temp": 12.0, "wind": 1.0}, True) == 2                   # dawn or dusk
    assert mosquito_band({"temp": 12.0, "wind": 1.0, "rh": 80}, False) == 2       # humid air
    assert mosquito_band({"temp": 30.0, "wind": 1.0}, False) == 1                  # too hot
    assert mosquito_band({"temp": None, "wind": 1.0}, False) == 0


def test_blackfly_and_horsefly_bands():
    assert blackfly_band({"temp": 20.0, "wind": 1.0}, True) == 2
    assert blackfly_band({"temp": 10.0, "wind": 1.0}, True) == 1
    assert blackfly_band({"temp": 20.0, "wind": 3.0}, True) == 0
    assert blackfly_band({"temp": 20.0, "wind": 1.0}, False) == 0                   # not in daytime
    assert horsefly_band({"hour": 13, "temp": 25.0, "wind": 1.0, "cloud": 10}) == 2
    assert horsefly_band({"hour": 13, "temp": 21.0, "wind": 1.0, "cloud": 10}) == 1
    assert horsefly_band({"hour": 8, "temp": 25.0, "wind": 1.0, "cloud": 10}) == 0    # too early
    assert horsefly_band({"hour": 13, "temp": 25.0, "wind": 1.0, "cloud": 90}) == 0   # overcast
    assert horsefly_band({"hour": 13, "temp": 18.0, "wind": 1.0, "cloud": 10}) == 0


def test_hour_ranges_and_seasons():
    assert hour_ranges([5, 6, 7, 19, 20]) == "05:00–08:00, 19:00–21:00" and hour_ranges([]) == ""
    assert hour_ranges([23]) == "23:00–24:00"
    assert in_season(7, (6, 7, 8), 56.0) and not in_season(7, (6, 7, 8), -34.0) and in_season(1, (6, 7, 8), -34.0)


# ---- the plugin --------------------------------------------------------------------------------
def test_ticks_in_season_with_advice_and_warning(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(), mean=14.0, date=APRIL)
    assert "Ticks: **high** (daily mean temperature 14 °C" in section.markdown and "Long sleeves" in section.markdown
    assert [w.severity for w in section.warnings if "tick" in w.text.lower()] == ["caution"]


def test_no_tick_line_in_winter_and_the_section_disappears_when_nothing_is_in_season(make_route, fixed_now):
    winter = run(make_route, fixed_now, rows(temp=-8.0), mean=-8.0, date=JANUARY)
    assert winter.omit is True and winter.markdown == ""


def test_summer_mosquitoes_with_still_water_and_dusk_peaks(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(wind=1.0), features=[water("water")])
    md = section.markdown
    assert "Mosquitoes: **high** — 05:00–22:00" in md
    assert any(w.severity == "caution" and "mosquitoes" in w.text.lower() for w in section.warnings)
    assert "Repellent and long light clothing" in md and "not a measurement" in md


def test_without_still_water_the_mosquito_band_drops_by_one(make_route, fixed_now):
    with_water = run(make_route, fixed_now, rows(temp=20.0), features=[water("water")])
    no_water = run(make_route, fixed_now, rows(temp=20.0), features=[], folder="dry")
    assert "Mosquitoes: **high**" in with_water.markdown
    assert "Mosquitoes: **moderate**" in no_water.markdown and "Mosquitoes: **high**" not in no_water.markdown


def test_blackflies_need_running_water_and_calm_daylight(make_route, fixed_now):
    river = run(make_route, fixed_now, rows(temp=20.0, wind=1.0), features=[water("waterway", detail="river")])
    assert "Blackflies and midges: **high**" in river.markdown
    lake_only = run(make_route, fixed_now, rows(temp=20.0, wind=1.0), features=[water("water")], folder="lake")
    assert "Blackflies and midges: **moderate**" in lake_only.markdown
    windy = run(make_route, fixed_now, rows(temp=20.0, wind=6.0), features=[water("waterway")], folder="windy")
    assert "Blackflies and midges: **low** (cold, wind or no suitable water nearby)" in windy.markdown


def test_horseflies_peak_in_the_hot_sunny_afternoon(make_route, fixed_now):
    hot = run(make_route, fixed_now, rows(temp=26.0, wind=1.0, cloud=10), features=[water("water")])
    line = next(l for l in hot.markdown.splitlines() if l.startswith("- Horseflies"))
    assert "**high**" in line and "11:00–18:00" in line
    assert not any("horseflies" in w.text.lower() for w in hot.warnings)        # informational only


def test_group_seasons_gate_the_lines(make_route, fixed_now):
    may = run(make_route, fixed_now, rows(), features=[water()], date=datetime.date(2026, 5, 20), folder="may")
    assert "Mosquitoes" in may.markdown and "Horseflies" not in may.markdown         # horseflies are Jun-Aug
    october = run(make_route, fixed_now, rows(temp=8.0), mean=8.0, date=datetime.date(2026, 10, 10), folder="oct")
    assert "Mosquitoes" not in october.markdown and "Ticks" in october.markdown


def test_southern_hemisphere_seasons_are_shifted(make_route, fixed_now):
    south = ((-70.0, -33.0, 100.0), (-70.02, -33.02, 110.0))
    january = run(make_route, fixed_now, rows(), features=[], date=JANUARY, coords=south, mean=20.0, folder="s1")
    assert "Mosquitoes" in january.markdown          # January is midsummer there
    july = run(make_route, fixed_now, rows(), features=[], date=JULY, coords=south, mean=8.0, folder="s2")
    assert "Mosquitoes" not in july.markdown


def test_missing_osm_data_is_said_and_assumes_a_habitat(make_route, fixed_now):
    down = run(make_route, fixed_now, rows(temp=20.0), error="504")
    assert "Water near the route could not be checked" in down.markdown and "Mosquitoes: **high**" in down.markdown
    absent = run(make_route, fixed_now, rows(temp=20.0), with_osm=False, folder="absent")
    assert "could not be checked" in absent.markdown


def test_missing_weather_or_light_do_not_crash(make_route, fixed_now):
    no_rows = run(make_route, fixed_now, [], mean=None, features=[water()])
    assert not no_rows.omit and no_rows.confidence == "no-data"          # July: in season, but no forecast to judge by
    assert "could not be estimated without the weather forecast" in no_rows.markdown
    ru = run(make_route, fixed_now, [], mean=None, features=[water()], folder="ru", lang="ru")
    assert "без прогноза погоды" in ru.markdown
    winter = run(make_route, fixed_now, [], mean=None, date=JANUARY, folder="win")
    assert winter.omit is True                                         # out of season: still not applicable
    fact = {"markdown": "Bears are active.", "sources": ["https://example.org/b"]}
    kept = run(make_route, fixed_now, [], mean=None, date=JANUARY, facts={"all": {"bio_hazards": fact}}, folder="fact")
    assert not kept.omit and "Bears are active" in kept.markdown and "weather forecast" not in kept.markdown
    no_light = run(make_route, fixed_now, rows(temp=20.0), features=[water()], light=False, folder="nl")
    assert "Mosquitoes" in no_light.markdown


def test_regional_facts_keep_a_section_alive_out_of_season(make_route, fixed_now):
    fact = {"markdown": "Bears are active near the river; keep food sealed.", "sources": ["https://example.org/bears"]}
    section = run(make_route, fixed_now, rows(temp=-8.0), mean=-8.0, date=JANUARY, facts={"all": {"bio_hazards": fact}})
    assert not section.omit and "Bears are active" in section.markdown and section.confidence == "web-sourced"
    assert "Sources: [example.org](https://example.org/bears)" in section.markdown


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, rows(temp=20.0), features=[water("water")], lang="ru")
    assert "Комары: **высокая**" in section.markdown and "Репеллент" in section.markdown


def test_group_title_and_dependencies():
    assert BioHazardsPlugin.title_key == "hz_bio"
    assert BioHazardsPlugin.depends_on == ("weather", "light", "osm_features")


MARCH = datetime.date(2026, 3, 20)


def test_no_tick_line_on_a_freezing_day_even_in_a_tick_month(make_route, fixed_now):
    freezing = run(make_route, fixed_now, rows(temp=-3.0), mean=-3.0, date=MARCH)
    assert freezing.omit is True and freezing.markdown == ""
    mild = run(make_route, fixed_now, rows(temp=8.0), mean=8.0, date=MARCH, folder="mild")
    assert "Ticks: **high**" in mild.markdown
    chilly = run(make_route, fixed_now, rows(temp=2.0), mean=2.0, date=MARCH, folder="chilly")
    assert "Ticks: **low**" in chilly.markdown
