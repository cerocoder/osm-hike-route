import datetime
import json
from collections import Counter
from pathlib import Path

import pytest

from day_plan.context import build_context
from day_plan.http import HttpError
from day_plan.osm_features import (
    OsmFeature, OsmFeaturesPlugin, classify, features_query, haversine_m, near, parse_features, route_bbox,
    route_samples,
)

FIXTURES = Path(__file__).parent / "fixtures"
DOMBAY = json.loads((FIXTURES / "osm_features_dombay.json").read_text(encoding="utf-8"))
CASA = json.loads((FIXTURES / "osm_features_casa_de_campo.json").read_text(encoding="utf-8"))


def kinds(data):
    return Counter(f.kind for f in parse_features(data))


def test_real_mountain_area_has_glaciers_streams_and_a_demanding_path():
    got = kinds(DOMBAY)
    assert got["glacier"] == 21 and got["waterway"] == 38 and got["water"] == 4
    assert got["bare_rock"] == 1 and got["sac"] == 1 and got["mast"] == 0
    sac = next(f for f in parse_features(DOMBAY) if f.kind == "sac")
    assert sac.detail == "demanding_alpine_hiking"


def test_real_park_has_masts_water_hiking_paths_and_industry():
    got = kinds(CASA)
    assert got["mast"] == 2 and got["water"] == 39 and got["sac"] == 7 and got["industrial"] == 1
    rivers = [f for f in parse_features(CASA) if f.kind == "waterway"]
    assert {f.detail for f in rivers} == {"river", "canal", "stream"}


def test_an_element_can_be_several_things_and_elements_without_coordinates_are_skipped():
    data = {"elements": [
        {"type": "way", "id": 1, "center": {"lat": 1.0, "lon": 2.0}, "tags": {"natural": "water", "waterway": "river", "name": "Lago"}},
        {"type": "node", "id": 2, "lat": 3.0, "lon": 4.0, "tags": {"man_made": "mast", "tower:type": "communication"}},
        {"type": "way", "id": 3, "tags": {"natural": "water"}},                        # no coordinates
        {"type": "node", "id": 4, "lat": "x", "lon": 1.0, "tags": {"natural": "water"}},  # not numbers
        {"type": "node", "id": 5, "lat": 5.0, "lon": 6.0},                              # no tags
    ]}
    features = parse_features(data)
    assert [(f.kind, f.detail, f.name) for f in features] == [("water", "", "Lago"), ("waterway", "river", "Lago"),
                                                              ("mast", "", "")]


@pytest.mark.parametrize("tags,expected", [
    ({"natural": "glacier"}, [("glacier", "")]),
    ({"natural": "peak"}, []),
    ({"waterway": "ditch"}, []),
    ({"communication:mobile_phone": "yes"}, [("mast", "")]),
    ({"man_made": "tower"}, []),                                    # a tower that is not a communication tower
    ({"landuse": "industrial"}, [("industrial", "")]),
    ({"power": "plant"}, [("industrial", "")]),
    ({"sac_scale": "alpine_hiking"}, [("sac", "alpine_hiking")]),
])
def test_classify(tags, expected):
    assert classify(tags) == expected


def test_route_bbox_adds_a_margin_that_grows_in_longitude_at_high_latitudes():
    s, w, n, e = route_bbox([(60.0, 56.0, 0), (60.1, 56.1, 0)], margin_km=5.0)
    assert s == pytest.approx(56.0 - 5 / 111.0) and n == pytest.approx(56.1 + 5 / 111.0)
    assert (60.0 - w) > (5 / 111.0) * 1.5           # 1/cos(56 deg) is about 1.8


def test_features_query_contains_the_bbox_and_every_kind():
    ql = features_query((40.4, -3.8, 40.5, -3.7))
    for text in ("40.40000,-3.80000,40.50000,-3.70000", "communication:mobile_phone", "glacier", "sac_scale",
                 "industrial", "power", "waterway", "out tags center", "[timeout:9]"):
        assert text in ql


def test_route_samples_keep_both_ends_and_cap_the_count():
    coords = [(10.0 + i * 0.001, 50.0, 0) for i in range(1000)]
    samples = route_samples(coords, max_points=50)
    assert len(samples) <= 50 and samples[0] == (50.0, 10.0) and samples[-1] == (50.0, 10.999)
    assert route_samples(coords[:3], max_points=50) == [(50.0, 10.0), (50.0, 10.001), (50.0, 10.002)]


def test_near_returns_the_features_within_the_radius_nearest_first():
    samples = [(50.0, 10.0), (50.0, 10.1)]
    features = [OsmFeature("water", 50.001, 10.0), OsmFeature("water", 50.0, 10.1005),
                OsmFeature("water", 51.0, 10.0), OsmFeature("mast", 50.0005, 10.0)]
    found = near(features, samples, "water", 500)
    assert [round(d) for _, d in found] == [36, 111]                # nearest first
    assert [f.kind for f, _ in near(features, samples, ("water", "mast"), 500)].count("mast") == 1
    assert near(features, samples, "glacier", 1e9) == []
    assert haversine_m(50.0, 10.0, 50.0, 10.0) == 0.0


class Web:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _ctx(make_route, fixed_now, web, folder="route"):
    return build_context(make_route(folder=folder, coords=((41.70, 43.25, 2000.0), (41.72, 43.26, 2400.0))),
                         datetime.date(2026, 7, 4), http=web, now=fixed_now)


def test_the_plugin_shares_features_and_writes_nothing_into_the_plan(make_route, fixed_now):
    section = OsmFeaturesPlugin().run(_ctx(make_route, fixed_now, Web(DOMBAY)), {})
    assert section.omit is True and section.markdown == ""
    assert Counter(f.kind for f in section.shared["features"])["glacier"] == 21
    assert section.shared["error"] is None and section.shared["samples"][0] == (43.25, 41.70)


def test_one_overpass_query_per_route_and_it_is_cached_for_later_runs(make_route, fixed_now):
    web = Web(DOMBAY)
    ctx = _ctx(make_route, fixed_now, web)
    OsmFeaturesPlugin().run(ctx, {})
    OsmFeaturesPlugin().run(ctx, {})
    assert len(web.calls) == 1 and "sac_scale" in web.calls[0]


def test_an_overpass_failure_is_reported_in_shared_not_raised(make_route, fixed_now):
    section = OsmFeaturesPlugin().run(_ctx(make_route, fixed_now, Web(HttpError("504"))), {})
    assert section.omit and section.shared["features"] == [] and "504" in section.shared["error"]
    assert section.confidence == "no-data"


def test_an_empty_answer_is_cached_for_a_day_not_a_week(make_route, fixed_now):
    web = Web({"elements": []})
    ctx = _ctx(make_route, fixed_now, web)
    OsmFeaturesPlugin().run(ctx, {})
    OsmFeaturesPlugin().run(ctx, {})
    assert len(web.calls) == 1
    later = build_context(make_route(folder="later"), ctx.date, http=web,
                          now=fixed_now + datetime.timedelta(days=2))
    later.cache = ctx.cache                                    # same cache file, two days later
    later.coords = ctx.coords
    OsmFeaturesPlugin().run(later, {})
    assert len(web.calls) == 2
