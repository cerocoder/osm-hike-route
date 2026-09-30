import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.fire import FirePlugin, prevailing_wind

FIXTURES = Path(__file__).parent / "fixtures"
FWI_HTML = (FIXTURES / "gwis_fwi_ekb_2026-09-28.html").read_text(encoding="utf-8")
HOTSPOT_HTML = (FIXTURES / "gwis_hotspots_biscay.html").read_text(encoding="utf-8")
TODAY = datetime.date(2026, 6, 20)          # the fixed_now fixture
BISCAY = ((-2.78, 43.21, 200.0), (-2.75, 43.25, 250.0))
EKB = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))


def fwi_html(value):
    return FWI_HTML.replace("9.5045595", str(value))


class World:
    """Answers the text (GWIS) and JSON (Nominatim, Open-Meteo) calls of the fire plugin."""
    def __init__(self, fwi=9.5, hotspots=HOTSPOT_HTML, country="es", history=None, fwi_error=None, hotspot_error=None):
        self.fwi, self.hotspots, self.country, self.history = fwi, hotspots, country, history
        self.fwi_error, self.hotspot_error = fwi_error, hotspot_error
        self.text_calls, self.json_calls = [], []

    def text(self, url):
        self.text_calls.append(url)
        if "ecmwf.query" in url:
            if self.fwi_error:
                raise self.fwi_error
            return "" if self.fwi is None else fwi_html(self.fwi)
        if "viirs.hs.query" in url:
            if self.hotspot_error:
                raise self.hotspot_error
            return self.hotspots
        raise AssertionError(url)

    def json(self, url):
        self.json_calls.append(url)
        if "nominatim" in url:
            return {"address": {"country_code": self.country}}
        if "open-meteo" in url:
            if isinstance(self.history, Exception):
                raise self.history
            return self.history
        raise AssertionError(url)


def history(days, t=25.0, dew=10.0, rain=None, end=TODAY + datetime.timedelta(days=3)):
    """`days` days ending at the plan date (the plugin asks Open-Meteo for date-30 .. date)."""
    times, temp, dp, pr = [], [], [], []
    for i in range(days):
        d = (end - datetime.timedelta(days=days - 1 - i)).isoformat()
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            temp.append(t)
            dp.append(dew)
            pr.append((rain or {}).get(d, 0.0) / 24)
    return {"hourly": {"time": times, "temperature_2m": temp, "dew_point_2m": dp, "precipitation": pr}}


def run(make_route, fixed_now, world, coords=BISCAY, date=TODAY + datetime.timedelta(days=2), lang="en", shared=None,
        facts=None, folder="route"):
    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=world.json, http_text=world.text, now=fixed_now)
    return FirePlugin().run(ctx, shared or {})


def test_the_official_fwi_and_its_components_are_shown_with_the_class(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=3))
    md = section.markdown
    assert "**9.5** — low" in md and "ISI 4.7" in md and "DC 147.0" in md
    assert "Model output" in md and section.confidence == "derived" and section.warnings == []


@pytest.mark.parametrize("fwi,severity", [(22.0, "caution"), (40.0, "danger"), (60.0, "danger")])
def test_high_and_worse_fire_weather_warns(make_route, fixed_now, fwi, severity):
    section = run(make_route, fixed_now, World(fwi=fwi), date=TODAY + datetime.timedelta(days=3))
    assert [w.severity for w in section.warnings] == [severity]
    assert "no open fire" in section.warnings[0].text


def test_beyond_the_eight_day_horizon_there_is_no_query_and_no_data(make_route, fixed_now):
    world = World()
    section = run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=9))
    assert "covers about 8 days" in section.markdown and section.confidence == "no-data"
    assert world.text_calls == []


def test_a_service_failure_or_an_empty_value_degrades_to_a_note(make_route, fixed_now):
    down = run(make_route, fixed_now, World(fwi_error=HttpError("503")), date=TODAY + datetime.timedelta(days=3))
    assert "could not be reached (503)" in down.markdown and down.confidence == "no-data" and down.warnings == []
    empty = run(make_route, fixed_now, World(fwi=None), date=TODAY + datetime.timedelta(days=3), folder="empty")
    assert "no value for this point and date" in empty.markdown


def test_active_fires_near_the_route_warn_and_show_the_detection(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=1))
    md = section.markdown
    assert "Satellite-detected active fires within 15 km" in md and "2026-09-29 02:17:00 UTC" in md
    assert "NOAA-21/VIIRS, confidence High, FRP 0.5 MW" in md
    assert section.warnings[0].severity == "danger" and "active fire was detected" in section.warnings[0].text
    assert section.confidence == "web-sourced"


def test_far_away_detections_are_not_reported_and_none_is_said_plainly(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=9.5), coords=((10.0, 50.0, 100.0), (10.02, 50.02, 110.0)),
                  date=TODAY + datetime.timedelta(days=1))
    assert "No satellite-detected active fires within 15 km" in section.markdown and section.warnings == []


def test_detections_are_only_looked_up_for_dates_around_today(make_route, fixed_now):
    world = World()
    run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=5))
    assert not any("viirs" in u for u in world.text_calls)
    run(make_route, fixed_now, world, date=TODAY + datetime.timedelta(days=2), folder="near")
    assert any("viirs" in u for u in world.text_calls)


def test_a_failed_detection_query_is_a_note_not_a_crash(make_route, fixed_now):
    section = run(make_route, fixed_now, World(hotspot_error=HttpError("504")), date=TODAY + datetime.timedelta(days=1))
    assert "could not be loaded (504)" in section.markdown and "FWI" in section.markdown


def test_the_wind_that_would_carry_the_fire_is_added_only_when_the_danger_is_elevated(make_route, fixed_now):
    rows = [{"wind": 6.0, "wdir": 270}, {"wind": 8.5, "wdir": 280}, {"wind": 3.0, "wdir": None}]
    calm = run(make_route, fixed_now, World(fwi=9.5), date=TODAY + datetime.timedelta(days=3),
               shared={"weather": {"daytime_rows": rows}})
    assert "Wind from" not in calm.markdown
    windy = run(make_route, fixed_now, World(fwi=30.0), date=TODAY + datetime.timedelta(days=3),
                shared={"weather": {"daytime_rows": rows}}, folder="windy")
    assert "Wind from W (275°) up to 8.5 m/s: a fire and its smoke would move toward E." in windy.markdown


def test_prevailing_wind_handles_missing_data():
    assert prevailing_wind([]) is None and prevailing_wind([{"wind": 3.0, "wdir": None}]) is None
    assert prevailing_wind([{"wind": 5.0, "wdir": 90}, {"wind": 2.0, "wdir": 270}]) is None      # cancels out


def test_russian_routes_get_the_nesterov_index_and_others_do_not(make_route, fixed_now):
    ru = run(make_route, fixed_now, World(country="ru", history=history(31)), coords=EKB,
             date=TODAY + datetime.timedelta(days=3))
    assert "Nesterov index): **11625** — class V (extreme)" in ru.markdown
    es = run(make_route, fixed_now, World(country="es", history=history(31)), date=TODAY + datetime.timedelta(days=3),
             folder="es")
    assert "Nesterov" not in es.markdown


def test_nesterov_classes_and_warnings(make_route, fixed_now):
    # 25 C with dew point 10: 375 per dry day; 31 days -> 11625 -> class V, a "danger"
    extreme = run(make_route, fixed_now, World(country="ru", history=history(31)), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3))
    assert "**11625** — class V (extreme)" in extreme.markdown
    assert any(w.severity == "danger" and "class V" in w.text for w in extreme.warnings)
    # a wet day resets it: only the days after the rain count
    rain_day = (TODAY + datetime.timedelta(days=3 - 5)).isoformat()
    reset = run(make_route, fixed_now, World(country="ru", history=history(31, rain={rain_day: 10.0})), coords=EKB,
                date=TODAY + datetime.timedelta(days=3), folder="reset")
    assert "**1875** — class III (moderate)" in reset.markdown and not any("Nesterov" in w.text for w in reset.warnings)


def test_a_nesterov_failure_is_a_note(make_route, fixed_now):
    section = run(make_route, fixed_now, World(country="ru", history=HttpError("boom")), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3))
    assert "Nesterov index could not be computed (boom)" in section.markdown and "FWI" in section.markdown


def test_no_nesterov_beyond_the_open_meteo_horizon(make_route, fixed_now):
    world = World(country="ru", history=history(31))
    section = run(make_route, fixed_now, world, coords=EKB, date=TODAY + datetime.timedelta(days=16))
    assert "The Nesterov index needs weather data and is not available this far ahead." in section.markdown
    assert not any("open-meteo" in u for u in world.json_calls)


def test_restrictions_from_facts_are_shown_with_sources_and_warnings(make_route, fixed_now):
    fact = {"markdown": "Forest access is banned in the Comunidad de Madrid from 1 June to 15 October.",
            "sources": ["https://www.comunidad.madrid/x"],
            "warnings": [{"severity": "caution", "text": "Forest access ban in force."}]}
    section = run(make_route, fixed_now, World(), date=TODAY + datetime.timedelta(days=3), facts={"all": {"fire": fact}})
    assert "Forest access is banned" in section.markdown and "Sources: [www.comunidad.madrid]" in section.markdown
    assert [w.text for w in section.warnings] == ["Forest access ban in force."] and section.confidence == "web-sourced"


def test_russian_text(make_route, fixed_now):
    section = run(make_route, fixed_now, World(fwi=30.0, country="ru", history=history(31)), coords=EKB,
                  date=TODAY + datetime.timedelta(days=3), lang="ru")
    assert "Индекс пожарной погоды" in section.markdown and "высокая" in section.markdown
    assert "показатель Нестерова" in section.markdown


def test_the_plugin_declares_its_group_title():
    assert FirePlugin.title_key == "hz_fire" and FirePlugin.section_id == "hazards"
    assert FirePlugin.depends_on == ("weather", "osm_features")
