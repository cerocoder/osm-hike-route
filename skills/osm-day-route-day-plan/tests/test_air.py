import datetime
import json
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import OsmFeature
from day_plan.plugins.air import AirPlugin, angle_difference, aqi_class, bearing_deg, pollen_level

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"air_{name}.json").read_text(encoding="utf-8"))


MADRID, KAZAN, MOSCOW = fixture("madrid"), fixture("kazan"), fixture("moscow")
DATE = datetime.date(2026, 6, 22)                     # after fixed_now (2026-06-20)
ROUTE = ((60.60, 56.84, 260.0), (60.62, 56.86, 270.0))
DAY_ROWS = [{"hour": h, "wind": 3.0, "wdir": 270} for h in range(8, 20)]


def hourly(**series):
    """A synthetic 24-hour air answer; each series is a scalar, or {hour: value}."""
    out = {"time": [f"2026-06-22T{h:02d}:00" for h in range(24)]}
    for key in ("alder_pollen", "birch_pollen", "olive_pollen", "grass_pollen", "mugwort_pollen", "ragweed_pollen",
                "pm2_5", "pm10", "ozone", "nitrogen_dioxide", "sulphur_dioxide", "dust", "european_aqi"):
        spec = series.get(key, 0.0)
        out[key] = [spec.get(h, 0.0) if isinstance(spec, dict) else spec for h in range(24)]
    return out


def run(make_route, fixed_now, answer, shared_extra=None, lang="en", facts=None, folder="route", coords=ROUTE, day_rows=DAY_ROWS):
    calls = []
    if isinstance(answer, dict) and "time" in answer:        # a bare hourly block from hourly()
        answer = {"hourly": answer}

    def http(url):
        calls.append(url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    route_dir = make_route(coords=coords, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    ctx = build_context(route_dir, DATE, lang=lang, http=http, now=fixed_now)
    shared = {"weather": {"daytime_rows": day_rows}}
    shared.update(shared_extra or {})
    section = AirPlugin().run(ctx, shared)
    section.calls = calls
    return section


# ---- helpers -----------------------------------------------------------------------------------
@pytest.mark.parametrize("var,value,level", [("birch_pollen", 14, "low"), ("birch_pollen", 15, "moderate"), ("birch_pollen", 90, "high"),
                                             ("birch_pollen", 1500, "very_high"), ("grass_pollen", 4, "low"), ("grass_pollen", 5, "moderate"),
                                             ("grass_pollen", 20, "high"), ("grass_pollen", 200, "very_high"), ("ragweed_pollen", 9, "low"),
                                             ("mugwort_pollen", 10, "moderate"), ("ragweed_pollen", 50, "high"), ("ragweed_pollen", 500, "very_high")])
def test_pollen_levels_follow_the_nab_scale(var, value, level):
    assert pollen_level(var, value) == level


@pytest.mark.parametrize("aqi,cls", [(0, 0), (19.9, 0), (20, 1), (39, 1), (40, 2), (59, 2), (60, 3), (79, 3), (80, 4), (99, 4), (100, 5), (200, 5)])
def test_european_aqi_classes(aqi, cls):
    assert aqi_class(aqi) == cls


def test_bearing_and_angle_difference():
    assert bearing_deg(50.0, 10.0, 51.0, 10.0) == pytest.approx(0.0, abs=0.01)
    assert bearing_deg(50.0, 10.0, 50.0, 11.0) == pytest.approx(90.0, abs=0.5)
    assert angle_difference(350, 10) == 20 and angle_difference(90, 270) == 180


# ---- real answers ------------------------------------------------------------------------------
def test_real_madrid_answer_has_real_low_pollen_and_a_fair_air_quality(make_route, fixed_now):
    section = run(make_route, fixed_now, MADRID)
    md = section.markdown
    assert "Pollen (daytime maximum, grains/m³): mugwort 0.3 (low), grass 0.2 (low)" in md
    assert "US National Allergy Bureau" in md
    assert "European AQI **46** — moderate" in md and "PM10 29 µg/m³" in md
    assert section.warnings == [] and section.confidence == "derived"


def test_real_kazan_answer_has_null_pollen_reported_as_no_data_not_zero(make_route, fixed_now):
    section = run(make_route, fixed_now, KAZAN)
    assert "Pollen: no data for this location" in section.markdown and "https://yandex.ru/pogoda/" in section.markdown
    assert "none or negligible" not in section.markdown
    assert "European AQI **22** — fair" in section.markdown


def test_real_moscow_answer_has_poor_air_and_zero_pollen(make_route, fixed_now):
    section = run(make_route, fixed_now, MOSCOW)
    assert "Pollen: none or negligible in the model for this date." in section.markdown
    assert "European AQI **68** — poor" in section.markdown
    assert [w.severity for w in section.warnings] == ["caution"] and "Poor air quality" in section.warnings[0].text


# ---- synthetic behaviour -----------------------------------------------------------------------
def test_high_pollen_warns_with_the_worst_kind(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(birch_pollen={12: 250.0}, grass_pollen={12: 6.0}))
    assert "birch 250 (high), grass 6.0 (moderate)" in section.markdown
    assert any("High pollen (birch: 250 grains/m³)" in w.text for w in section.warnings)


def test_only_daytime_hours_count(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(birch_pollen={3: 5000.0}, european_aqi={3: 150}))
    assert "none or negligible" in section.markdown and "AQI **0** — good" in section.markdown
    assert section.warnings == []


def test_very_poor_air_is_a_danger(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(european_aqi={12: 105}))
    assert [w.severity for w in section.warnings] == ["danger"]


def test_all_null_pollution_after_the_model_horizon_is_no_data(make_route, fixed_now):
    nulls = {k: [None] * 24 for k in hourly()}
    nulls["time"] = hourly()["time"]
    section = run(make_route, fixed_now, nulls)
    assert "the air-quality model reaches only about four days ahead" in section.markdown
    assert "Pollen: no data" in section.markdown and section.confidence == "no-data"


def test_a_service_error_or_a_400_is_a_note_not_a_crash(make_route, fixed_now):
    down = run(make_route, fixed_now, HttpError("HTTP Error 503: Service Unavailable"))
    assert "could not be reached (HTTP Error 503: Service Unavailable)" in down.markdown and down.confidence == "no-data"
    odd = run(make_route, fixed_now, {"error": True, "reason": "out of allowed range"}, folder="odd")
    assert "out of allowed range" in odd.markdown


def test_the_answer_is_cached_for_three_hours(make_route, fixed_now):
    calls = []
    route_dir = make_route()
    ctx = build_context(route_dir, DATE, http=lambda u: calls.append(u) or MADRID, now=fixed_now)
    AirPlugin().run(ctx, {})
    AirPlugin().run(ctx, {})
    assert len(calls) == 1 and "hourly=alder_pollen" in calls[0] and "start_date=2026-06-22" in calls[0]


def factory(dlat, dlon):
    return OsmFeature("industrial", 56.84 + dlat, 60.60 + dlon, "", "")


def osm(*features, error=None):
    return {"osm_features": {"features": list(features), "samples": [(56.84, 60.60), (56.86, 60.62)], "error": error}}


def test_industry_upwind_of_the_route_is_reported_with_the_hours(make_route, fixed_now):
    west = factory(0.0, -0.03)           # about 1.8 km west of the route; the wind from the west carries it eastwards
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(west))
    assert "Industrial sites within 5 km of the route (OpenStreetMap): 1. The wind carries emissions from 1 of them toward the route around 08:00–20:00." in section.markdown
    assert any(w.severity == "info" and "Industrial emissions" in w.text for w in section.warnings)


def test_industry_downwind_of_the_route_is_not_a_problem(make_route, fixed_now):
    east = factory(0.0, 0.10)            # east of the route: a westerly wind carries its smoke away
    close_east = factory(0.0, 0.05)
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(close_east), folder="east")
    assert "the wind does not carry their emissions toward the route" in section.markdown
    assert not any("Industrial" in w.text for w in section.warnings)
    assert east.lat > 0


def test_calm_air_or_missing_wind_data_reports_no_downwind_hours(make_route, fixed_now):
    calm = [{"hour": h, "wind": 0.3, "wdir": 270} for h in range(8, 20)]
    section = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.03)), day_rows=calm)
    assert "does not carry" in section.markdown
    unknown = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.03)), day_rows=[{"hour": 12}], folder="nw")
    assert "does not carry" in unknown.markdown


def test_far_industry_and_osm_failures_add_nothing(make_route, fixed_now):
    far = run(make_route, fixed_now, hourly(), shared_extra=osm(factory(0.0, -0.5)))
    assert "Industrial" not in far.markdown
    failed = run(make_route, fixed_now, hourly(), shared_extra=osm(error="504"), folder="f")
    assert "Industrial" not in failed.markdown


def test_regional_advisories_from_facts(make_route, fixed_now):
    fact = {"markdown": "Wildfire smoke from the east is forecast.", "sources": ["https://example.org/smoke"],
            "warnings": [{"severity": "caution", "text": "Smoke advisory."}]}
    section = run(make_route, fixed_now, MADRID, facts={"all": {"air": fact}})
    assert "Wildfire smoke" in section.markdown and section.confidence == "web-sourced"
    assert [w.text for w in section.warnings] == ["Smoke advisory."]


def test_russian_text_and_group_title(make_route, fixed_now):
    section = run(make_route, fixed_now, MOSCOW, lang="ru")
    assert "европейский индекс AQI **68** — плохое" in section.markdown and "Пыльца: по модели" in section.markdown
    assert AirPlugin.title_key == "hz_air" and AirPlugin.depends_on == ("weather", "osm_features")


MADRID_ROUTE = ((-3.70, 40.40, 650.0), (-3.72, 40.42, 660.0))


def _nulls():
    out = {k: [None] * 24 for k in hourly()}
    out["time"] = hourly()["time"]
    return out


def test_beyond_the_model_horizon_says_what_is_missing_and_makes_no_call(make_route, fixed_now):
    section = run(make_route, fixed_now, hourly(), shared_extra={"weather": {"daytime_rows": DAY_ROWS, "source": "climate"}})
    assert section.calls == [] and section.confidence == "no-data"
    assert "the air-quality model reaches only about four days ahead" in section.markdown
    assert "beyond the model horizon" in section.markdown and "could not be reached" not in section.markdown


def test_a_date_more_than_five_days_ahead_makes_no_call(make_route, fixed_now):
    calls = []
    route_dir = make_route(coords=ROUTE, folder="far")
    ctx = build_context(route_dir, fixed_now.date() + datetime.timedelta(days=6), lang="en",
                        http=lambda u: calls.append(u) or {}, now=fixed_now)
    section = AirPlugin().run(ctx, {"weather": {"daytime_rows": DAY_ROWS}})
    assert calls == [] and "beyond the model horizon" in section.markdown


def test_an_http_400_for_a_date_is_no_data_but_other_errors_stay_unreachable(make_route, fixed_now):
    section = run(make_route, fixed_now, HttpError("HTTP Error 400: Bad Request"))
    assert "could not be reached" not in section.markdown and section.confidence == "no-data"
    assert "the air-quality model reaches only about four days ahead" in section.markdown
    assert "beyond the model horizon" in section.markdown


def test_all_null_pollen_inside_the_domain_does_not_point_to_yandex(make_route, fixed_now):
    section = run(make_route, fixed_now, _nulls(), coords=MADRID_ROUTE, folder="mad")
    assert "yandex" not in section.markdown.lower() and "no data for this location" not in section.markdown
    assert "Pollen: no values" in section.markdown
    east = run(make_route, fixed_now, _nulls(), folder="east")
    assert "https://yandex.ru/pogoda/" in east.markdown


def test_a_missing_aqi_prints_a_dash_and_no_class_word(make_route, fixed_now):
    answer = hourly(pm2_5=10.0)
    answer["european_aqi"] = [None] * 24
    section = run(make_route, fixed_now, answer)
    assert "European AQI **–**." in section.markdown and "good" not in section.markdown
