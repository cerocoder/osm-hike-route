import datetime
import math

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.plugins.water import (
    WaterPlugin, bathing_status, estimate_inland_temp, tau_days,
)
from day_plan.plugins.water_near import WaterBody

DATE = datetime.date(2026, 6, 21)


def _body(name, size, kind="lake", tags=None, distance=120.0, near_kind="track", near_name=""):
    return WaterBody(kind, name, 40.0, -3.0, (40.0, -3.0, 40.0, -3.0), size, tags or {}, distance, near_kind, near_name)


def _near(bodies=(), sea=None, spots=()):
    return {"bodies": list(bodies), "sea": sea, "swim_spots": list(spots), "error": None}


SEA = {"lat": 43.5, "lon": -3.5, "distance_m": 80.0, "near_kind": "start", "near_name": "Playa"}


def _weather(last_hour=23):
    rows = [{"hour": h, "day": 0} for h in range(24)] + [{"hour": h, "day": 1} for h in range(last_hour - 23)]
    return {"window_rows": rows}


def _marine(sst=21.0):
    level = [round(1.5 * math.sin(2 * math.pi * (h - 3) / 12.42), 3) for h in range(24)]
    return {"hourly": {"time": [f"2026-06-21T{h:02d}:00" for h in range(24)],
                       "sea_surface_temperature": [sst] * 24, "sea_level_height_msl": level}}


def _http(sst=21.0, air=20.0):
    def http(url):
        if "marine-api" in url:
            return _marine(sst)
        if "temperature_2m_mean" in url:
            return {"daily": {"temperature_2m_mean": [air] * 31}}
        raise HttpError("unexpected " + url)
    return http


def _run(make_route, fixed_now, near, http=None, lang="en", facts=None, weather=None, folder="route", date=DATE, now=None):
    import json
    route_dir = make_route(folder=folder)
    if facts:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, date, lang=lang, http=http or _http(), now=now or fixed_now)
    return WaterPlugin().run(ctx, {"water_near": near, "weather": weather or _weather()})


# ---- pure helpers -------------------------------------------------------------------------------
def test_estimate_follows_the_air_with_a_lag():
    assert estimate_inland_temp([20.0] * 30, "lake", 3.0) == pytest.approx(20.0)
    warming = [5.0] * 20 + [25.0] * 10
    pond, big = estimate_inland_temp(warming, "pond", 0.1), estimate_inland_temp(warming, "lake", 40.0)
    assert pond > big > 5.0 and pond < 25.0
    assert estimate_inland_temp([-8.0] * 30, "lake", 3.0) == 0.0          # never below freezing
    assert estimate_inland_temp([20.0, None, 21.0], "lake", 3.0) is None  # too little history


def test_a_river_reacts_faster_than_a_lake():
    assert tau_days("river", 5.0) < tau_days("lake", 5.0) < tau_days("lake", 50.0)


@pytest.mark.parametrize("tags,spot,expected", [
    ({"swimming": "yes"}, False, "allowed"), ({"swimming": "no"}, True, "forbidden"),
    ({"bathing": "yes"}, False, "allowed"), ({}, True, "allowed"), ({"sport": "swimming"}, False, "allowed"),
    ({}, False, "unknown"),
])
def test_bathing_status_from_osm_tags(tags, spot, expected):
    assert bathing_status(tags, spot) == expected


# ---- the section ---------------------------------------------------------------------------------
def test_nothing_nearby_leaves_the_section_out(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near())
    assert section.omit


def test_overpass_failure_is_no_data(make_route, fixed_now):
    near = {"bodies": [], "sea": None, "swim_spots": [], "error": "503"}
    section = _run(make_route, fixed_now, near)
    assert section.confidence == "no-data" and "could not be determined" in section.markdown


def test_sea_is_a_separate_first_row_with_temperature_and_tides(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA))
    lines = section.markdown.splitlines()
    rows = [l for l in lines if l.startswith("| ") and "---" not in l][1:]
    assert rows[0].startswith("| Sea or ocean coast") and "21 °C" in rows[0] and "at the start point" in rows[0]
    assert "Tides" in section.markdown and "high water" in section.markdown and "low water" in section.markdown
    assert section.confidence == "derived" and section.shared["water_applies"] is True
    assert any("Tidal range" in w.text for w in section.warnings)          # 3 m range


def test_two_largest_bodies_get_data_the_rest_are_listed(make_route, fixed_now):
    bodies = [_body("Pond A", 0.2, "pond"), _body("Lago Grande", 9.0), _body("Rio X", 4.0, "river"),
              _body("Stream B", 0.1, "river")]
    section = _run(make_route, fixed_now, _near(bodies))
    text = section.markdown
    assert text.index("Lago Grande") < text.index("Rio X") < text.index("Other water within 500 m")
    table = text.split("Other water within 500 m")[0]
    assert "Pond A" not in table and "Stream B" not in table
    listed = text.split("Other water within 500 m")[1]
    assert "Pond A (pond)" in listed and "Stream B (river)" in listed
    assert "~20 °C" in table or "~19 °C" in table                       # an estimate, marked with "~"


def test_the_list_of_the_rest_is_cut_at_fifteen(make_route, fixed_now):
    bodies = [_body(f"Pond {i}", 0.1 + i / 100, "pond") for i in range(30)]
    text = _run(make_route, fixed_now, _near(bodies)).markdown
    listed = text.split("Other water within 500 m")[1]
    assert listed.count("(pond)") == 15 and "…and 13 more." in listed


def test_bathing_comes_from_osm_tags_and_swim_spots(make_route, fixed_now):
    near = _near([_body("Lago", 5.0, tags={"swimming": "no"}), _body("Embalse", 4.0)],
                 spots=[("Playa fluvial", 40.0, -3.0)])
    text = _run(make_route, fixed_now, near).markdown
    assert "forbidden (OSM)" in text and "allowed (OSM)" in text


def test_cold_water_gets_one_caution(make_route, fixed_now):
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_http(air=8.0))
    cold = [w for w in section.warnings if "Cold water" in w.text]
    assert len(cold) == 1 and cold[0].severity == "caution"


def test_ice_is_possible_in_the_cold(make_route, fixed_now):
    assert "ice is possible" in _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_http(air=-3.0)).markdown


def test_a_forbidden_swim_spot_gets_no_cold_shock_warning(make_route, fixed_now):
    near = _near([_body("Lago", 5.0, tags={"swimming": "no"})])
    assert not [w for w in _run(make_route, fixed_now, near, http=_http(air=8.0)).warnings if "Cold" in w.text]


def test_pollution_and_hazards_come_from_the_water_fact(make_route, fixed_now):
    facts = {"all": {"water": {"markdown": "Bathing water quality: excellent (EEA). Strong rip currents at low tide.",
                               "sources": ["https://example.org/bathing"],
                               "warnings": [{"severity": "caution", "text": "Rip currents at low tide"}]}}}
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), facts=facts)
    assert "Strong rip currents" in section.markdown and section.confidence == "web-sourced"
    assert any(w.text == "Rip currents at low tide" for w in section.warnings)
    plain = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), folder="plain")
    assert "No data on pollution" in plain.markdown and plain.confidence == "derived"


def test_marine_failure_keeps_the_rest(make_route, fixed_now):
    def http(url):
        if "marine-api" in url:
            raise HttpError("500")
        return {"daily": {"temperature_2m_mean": [20.0] * 31}}

    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), http=http)
    assert "Sea or ocean coast" in section.markdown and "–" in section.markdown and "Lago" in section.markdown


def test_air_history_failure_gives_a_dash_for_the_inland_temperature(make_route, fixed_now):
    def http(url):
        raise HttpError("500")

    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=http)
    row = next(l for l in section.markdown.splitlines() if "Lago" in l)
    assert "estimate" not in row and "| – |" in row


def test_tides_over_midnight_use_the_next_day(make_route, fixed_now):
    urls = []
    base = _http()

    def http(url):
        urls.append(url)
        return base(url)

    _run(make_route, fixed_now, _near(sea=SEA), http=http, weather=_weather(last_hour=27))
    assert any("start_date=2026-06-22" in u for u in urls)


def test_russian(make_route, fixed_now):
    text = _run(make_route, fixed_now, _near([_body("Lago", 5.0)], sea=SEA), lang="ru").markdown
    assert "Побережье моря или океана" in text and "Приливы" in text and "у точки старта" in text


def test_truncated_overpass_adds_a_note(make_route, fixed_now):
    near = _near([_body("Lago", 5.0)])
    near["truncated"] = True
    text = _run(make_route, fixed_now, near).markdown
    assert "The map query hit its size limit: the list of water bodies may be incomplete." in text


def test_no_truncation_note_otherwise(make_route, fixed_now):
    text = _run(make_route, fixed_now, _near([_body("Lago", 5.0)])).markdown
    assert "size limit" not in text


def _recording_http(urls):
    base = _http()

    def http(url):
        urls.append(url)
        return base(url)
    return http


def _range(url):
    import re
    return (re.search(r"start_date=([\d-]+)", url).group(1), re.search(r"end_date=([\d-]+)", url).group(1))


def test_january_beyond_the_horizon_keeps_a_valid_climatology_window(make_route, fixed_now):
    urls = []
    section = _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_recording_http(urls),
                   date=datetime.date(2027, 1, 15))
    archive = [_range(u) for u in urls if "archive" in u and "temperature_2m_mean" in u]
    assert len(archive) == 3 and all(a <= b for a, b in archive)
    row = next(l for l in section.markdown.splitlines() if "Lago" in l)
    assert "| – |" not in row and "estimate" in row


def test_a_distant_past_date_reads_the_archive(make_route, fixed_now):
    urls = []
    _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_recording_http(urls), date=datetime.date(2026, 3, 1))
    means = [u for u in urls if "temperature_2m_mean" in u]
    assert len(means) == 1 and "archive" in means[0]
    assert _range(means[0]) == ("2026-01-30", "2026-02-28")


def test_a_near_date_reads_the_forecast_api(make_route, fixed_now):
    urls = []
    _run(make_route, fixed_now, _near([_body("Lago", 5.0)]), http=_recording_http(urls))
    means = [u for u in urls if "temperature_2m_mean" in u]
    assert len(means) == 1 and "archive" not in means[0]
    assert _range(means[0]) == ("2026-05-22", "2026-06-20")


def test_a_swim_spot_far_from_the_sea_does_not_make_the_sea_bathable(make_route, fixed_now):
    near = _near([_body("Lago", 5.0)], sea=SEA, spots=[("Playa fluvial", 40.5, -3.0)])
    row = next(l for l in _run(make_route, fixed_now, near).markdown.splitlines() if l.startswith("| Sea or ocean"))
    assert "not stated" in row and "allowed (OSM)" not in row


def test_a_swim_spot_at_the_sea_point_makes_it_allowed(make_route, fixed_now):
    near = _near([_body("Lago", 5.0)], sea=SEA, spots=[("Playa", 43.5005, -3.5)])
    row = next(l for l in _run(make_route, fixed_now, near).markdown.splitlines() if l.startswith("| Sea or ocean"))
    assert "allowed (OSM)" in row
