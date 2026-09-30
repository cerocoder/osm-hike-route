from types import SimpleNamespace

import pytest

from day_plan.passability import (
    Conditions, Leg, build_legs, classify_segment, judge_leg, judge_run, profile_for, surface_summary,
)

STEP_KM = 0.1112          # one vertex every 0.001 degrees of latitude


def line(n=5, ele=None):
    return [(37.0, 55.0 + i * 0.001, None if ele is None else ele + 10.0 * i) for i in range(n)]


def point(name, index, role=None, dlat=0.0, dlon=0.0):
    return SimpleNamespace(name=name, role=role, lat=55.0 + index * 0.001 + dlat, lon=37.0 + dlon)


def surface(**tags):
    return classify_segment({"highway": "track", **tags})


@pytest.mark.parametrize("mode, style, expected", [
    ("walk", None, "walk"), ("walk", "sport", "walk"), ("bike", "sport", "bike_sport"),
    ("bike", "leisure", "bike_leisure"), ("bike", None, "bike_leisure"), ("ski", None, None), ("boat", "x", None),
])
def test_profile_for(mode, style, expected):
    assert profile_for(mode, style) == expected


# ---- the road a run is on ---------------------------------------------------------------------------------------------------
def test_a_cleared_hard_street():
    s = classify_segment({"highway": "residential", "surface": "asphalt"})
    assert (s.cleared, s.base, s.assumed, s.no_data, s.label) == (True, "hard", False, False, "asphalt")


@pytest.mark.parametrize("tags, cleared, base, assumed", [
    ({"highway": "track"}, False, "compacted", True),
    ({"highway": "track", "tracktype": "grade1"}, False, "hard", True),
    ({"highway": "track", "tracktype": "grade5"}, False, "soft", True),
    ({"highway": "path"}, False, "soft", True),
    ({"highway": "footway"}, False, "soft", True),
    ({"highway": "service"}, False, "compacted", True),
    ({"highway": "tertiary_link"}, True, "hard", True),
    ({"highway": "unclassified"}, True, "compacted", True),
    ({"highway": "track", "surface": "gravel"}, False, "compacted", False),
    ({"highway": "path", "surface": "asphalt"}, False, "hard", False),
    ({"highway": "residential", "surface": "dirt"}, True, "soft", False),
    ({"highway": "track", "winter_service": "yes"}, True, "compacted", True),
    ({"highway": "track", "snowplowing": "yes"}, True, "compacted", True),
    ({"highway": "residential", "winter_service": "no"}, False, "hard", True),
    ({"highway": "residential", "winter_service": "YES"}, True, "hard", True),
    ({"highway": "path", "surface": "weird"}, False, "soft", True),
])
def test_classification_by_class_surface_and_explicit_tags(tags, cleared, base, assumed):
    s = classify_segment(tags)
    assert (s.cleared, s.base, s.assumed) == (cleared, base, assumed)


def test_a_segment_without_road_data_is_an_uncleared_soft_path():
    s = classify_segment({"way_id": 7})
    assert (s.cleared, s.base, s.assumed, s.no_data) == (False, "soft", True, True)


def test_technical_grades_and_labels():
    s = classify_segment({"highway": "path", "sac_scale": "demanding_mountain_hiking", "mtb:scale": "2+"})
    assert (s.sac, s.mtb) == (3, 2)
    assert classify_segment({"highway": "path", "sac_scale": "nonsense", "mtb:scale": "x"}).sac == 0
    assert classify_segment({"highway": "path"}).label == "path"
    assert classify_segment({"highway": "path", "surface": "sand"}).label == "sand"


# ---- legs -------------------------------------------------------------------------------------------------------------------
TRACK_THEN_STREET = [{"from": 0, "to": 2, "highway": "track", "surface": "gravel"},
                     {"from": 2, "to": 4, "highway": "residential", "surface": "asphalt"}]


def test_points_split_the_track_into_legs_with_their_runs():
    coords = line(5, ele=100.0)
    legs = build_legs(coords, [point("Station", 0, "start"), point("Lake", 2), point("Bus stop", 4, "end")],
                      TRACK_THEN_STREET, "start", "finish", "whole route")

    assert [l.name for l in legs] == ["Station → Lake", "Lake → Bus stop"]
    assert [(l.start, l.end) for l in legs] == [(0, 2), (2, 4)]
    assert legs[0].length_km == pytest.approx(2 * STEP_KM, rel=0.01)
    assert [(s.label, round(m)) for s, m in legs[0].runs] == [("gravel", round(2 * STEP_KM * 1000))]
    assert [s.label for s, _ in legs[1].runs] == ["asphalt"]
    assert (legs[0].min_ele, legs[0].max_ele, legs[0].mean_ele) == (100.0, 120.0, 110.0)
    assert legs[0].gradient_pct == pytest.approx(9.0, abs=0.2)


def test_without_points_the_whole_route_is_one_leg_and_the_ends_get_default_names():
    legs = build_legs(line(5), [], TRACK_THEN_STREET, "start", "finish", "whole route")
    assert [l.name for l in legs] == ["whole route"] and (legs[0].start, legs[0].end) == (0, 4)
    assert len(legs[0].runs) == 2

    legs = build_legs(line(5), [point("Lake", 2)], TRACK_THEN_STREET, "start", "finish", "whole route")
    assert [l.name for l in legs] == ["start → Lake", "Lake → finish"]


def test_points_far_from_the_track_do_not_split_it_and_points_at_one_vertex_merge():
    far = point("Museum", 2, dlon=0.01)                      # about 640 m to the side
    legs = build_legs(line(5), [far], TRACK_THEN_STREET, "start", "finish", "whole route")
    assert [l.name for l in legs] == ["whole route"]

    twins = [point("Cafe", 2), point("Kiosk", 2), point("Viewpoint", 3)]
    legs = build_legs(line(5), twins, TRACK_THEN_STREET, "start", "finish", "whole route")
    assert [l.name for l in legs] == ["start → Cafe", "Cafe → Viewpoint", "Viewpoint → finish"]


def test_a_run_that_crosses_a_boundary_is_split_between_the_legs():
    whole = [{"from": 0, "to": 4, "highway": "track", "surface": "gravel"}]
    legs = build_legs(line(5), [point("Lake", 2)], whole, "start", "finish", "whole route")
    assert [round(m) for _, m in (legs[0].runs[0], legs[1].runs[0])] == [round(2 * STEP_KM * 1000)] * 2


def test_points_at_the_ends_of_the_track_name_the_ends_and_short_tracks_have_no_legs():
    legs = build_legs(line(3), [point("A", 0), point("B", 2)], [{"from": 0, "to": 2, "highway": "path"}],
                      "start", "finish", "whole route")
    assert [l.name for l in legs] == ["whole route"]        # the ends are boundaries already, no inner point
    assert build_legs([(37.0, 55.0, None)], [], [], "s", "f", "w") == []


def test_a_route_without_elevations_has_no_elevation_figures():
    leg = build_legs(line(3), [], [{"from": 0, "to": 2, "highway": "path"}], "s", "f", "w")[0]
    assert (leg.min_ele, leg.max_ele, leg.mean_ele, leg.gradient_pct) == (None, None, None, 0.0)


def test_surface_summary_sorts_truncates_and_merges_the_rest():
    runs = [(surface(surface="gravel"), 800.0), (surface(), 100.0), (classify_segment({"highway": "path"}), 60.0),
            (classify_segment({"highway": "footway"}), 40.0)]
    assert surface_summary(runs) == [("gravel", 80), ("track", 10), ("path", 6), ("other", 4)]
    assert surface_summary(runs, top=1) == [("gravel", 80), ("other", 20)]
    assert surface_summary([]) == []


# ---- verdicts ---------------------------------------------------------------------------------------------------------------
def cond(snow=0.0, ice="none", slush=False):
    return Conditions(snow_cm=snow, ice=ice, slush=slush)


UNCLEARED_PATH = classify_segment({"highway": "path", "surface": "ground"})
UNCLEARED_TRACK = classify_segment({"highway": "track", "surface": "gravel"})
CLEARED_STREET = classify_segment({"highway": "residential", "surface": "asphalt"})


@pytest.mark.parametrize("snow, expected", [(0.0, "passable"), (7.9, "passable"), (8.0, "caution"),
                                            (19.9, "caution"), (20.0, "danger"), (60.0, "danger")])
def test_walking_snow_thresholds_on_an_uncleared_run(snow, expected):
    assert judge_run("walk", UNCLEARED_PATH, cond(snow), 2.0) == expected


def test_a_cleared_street_is_not_blocked_by_snow_for_anyone():
    for profile in ("walk", "bike_leisure", "bike_sport"):
        assert judge_run(profile, CLEARED_STREET, cond(40.0), 2.0) == "passable"


@pytest.mark.parametrize("gradient, expected", [(2.0, "caution"), (9.9, "caution"), (10.0, "danger")])
def test_walking_on_high_ice_is_difficult_and_not_recommended_when_steep(gradient, expected):
    assert judge_run("walk", CLEARED_STREET, cond(0.0, "high"), gradient) == expected


def test_moderate_ice_does_not_stop_a_walker_and_technical_trails_with_snow_do():
    assert judge_run("walk", CLEARED_STREET, cond(0.0, "moderate"), 2.0) == "passable"
    technical = classify_segment({"highway": "path", "surface": "ground", "sac_scale": "demanding_mountain_hiking"})
    assert judge_run("walk", technical, cond(1.0), 2.0) == "danger"
    assert judge_run("walk", technical, cond(0.5), 2.0) == "passable"
    easy = classify_segment({"highway": "path", "surface": "ground", "sac_scale": "mountain_hiking"})
    assert judge_run("walk", easy, cond(1.0), 2.0) == "passable"


@pytest.mark.parametrize("profile, run, snow, expected", [
    ("bike_leisure", UNCLEARED_TRACK, 2.9, "passable"), ("bike_leisure", UNCLEARED_TRACK, 3.0, "caution"),
    ("bike_leisure", UNCLEARED_TRACK, 7.9, "caution"), ("bike_leisure", UNCLEARED_TRACK, 8.0, "danger"),
    ("bike_leisure", UNCLEARED_PATH, 1.9, "passable"), ("bike_leisure", UNCLEARED_PATH, 2.0, "caution"),
    ("bike_leisure", UNCLEARED_PATH, 6.0, "danger"),
    ("bike_sport", UNCLEARED_TRACK, 9.9, "caution"), ("bike_sport", UNCLEARED_TRACK, 10.0, "danger"),
    ("bike_sport", UNCLEARED_PATH, 7.9, "caution"), ("bike_sport", UNCLEARED_PATH, 8.0, "danger"),
])
def test_bicycle_snow_thresholds_by_profile_and_base(profile, run, snow, expected):
    assert judge_run(profile, run, cond(snow), 2.0) == expected


def test_studded_tires_make_ice_alone_harmless_but_crust_slush_and_technical_trails_difficult():
    assert judge_run("bike_leisure", CLEARED_STREET, cond(0.0, "high"), 2.0) == "passable"
    assert judge_run("bike_sport", UNCLEARED_TRACK, cond(0.0, "high"), 2.0) == "passable"
    assert judge_run("bike_leisure", UNCLEARED_TRACK, cond(1.0, "moderate"), 2.0) == "caution"      # icy crust
    assert judge_run("bike_leisure", UNCLEARED_TRACK, cond(1.0, "none", slush=True), 2.0) == "caution"
    assert judge_run("bike_leisure", CLEARED_STREET, cond(1.0, "none", slush=True), 2.0) == "passable"
    mtb = classify_segment({"highway": "path", "surface": "ground", "mtb:scale": "2"})
    assert judge_run("bike_sport", mtb, cond(1.0), 2.0) == "caution"
    assert judge_run("bike_sport", mtb, cond(0.0), 2.0) == "passable"


def leg_with(*runs, gradient=2.0):
    return Leg(name="A → B", start=0, end=4, length_km=sum(m for _, m in runs) / 1000.0, min_ele=None, max_ele=None,
               mean_ele=None, gradient_pct=gradient, runs=list(runs))


def test_a_leg_is_not_recommended_from_twenty_percent_of_not_recommended_runs():
    leg = leg_with((UNCLEARED_PATH, 200.0), (CLEARED_STREET, 800.0))
    assert judge_leg("walk", leg, cond(25.0)).verdict == "danger"
    leg = leg_with((UNCLEARED_PATH, 199.0), (CLEARED_STREET, 801.0))
    assert judge_leg("walk", leg, cond(25.0)).verdict == "caution"        # 19.9 % not recommended: no cliff, difficult
    leg = leg_with((UNCLEARED_PATH, 99.0), (CLEARED_STREET, 901.0))
    assert judge_leg("walk", leg, cond(25.0)).verdict == "passable"       # 9.9 %: still passable
    leg = leg_with((UNCLEARED_PATH, 100.0), (CLEARED_STREET, 900.0))
    assert judge_leg("walk", leg, cond(25.0)).verdict == "caution"        # 10 % is the limit


def test_a_leg_is_difficult_from_thirty_percent_of_difficult_or_worse_runs_and_else_passable():
    leg = leg_with((UNCLEARED_PATH, 300.0), (CLEARED_STREET, 700.0))
    verdict = judge_leg("walk", leg, cond(10.0))
    assert verdict.verdict == "caution" and verdict.caution_share == pytest.approx(0.3) and verdict.danger_share == 0.0
    assert judge_leg("walk", leg_with((UNCLEARED_PATH, 290.0), (CLEARED_STREET, 710.0)), cond(10.0)).verdict == "passable"


def test_a_leg_without_runs_is_judged_as_an_uncleared_soft_path_and_reported_as_no_data():
    leg = leg_with()
    leg.length_km = 0.5
    verdict = judge_leg("walk", leg, cond(10.0))
    assert verdict.verdict == "caution" and verdict.no_data_share == 1.0


def test_no_data_share_counts_only_runs_without_road_data():
    leg = leg_with((classify_segment({"way_id": 1}), 250.0), (CLEARED_STREET, 750.0))
    assert judge_leg("walk", leg, cond(0.0)).no_data_share == pytest.approx(0.25)


def test_ice_is_taken_per_surface_when_cleared_and_uncleared_ice_differ():
    both = Conditions(snow_cm=0.0, ice="none", ice_cleared="high")
    assert judge_run("walk", CLEARED_STREET, both, 2.0) == "caution"        # black ice on the street
    assert judge_run("walk", UNCLEARED_PATH, both, 2.0) == "passable"       # nothing on the path
    crust = Conditions(snow_cm=1.0, ice="moderate", ice_cleared="none")
    assert judge_run("bike_leisure", UNCLEARED_TRACK, crust, 2.0) == "caution"
    assert judge_run("bike_leisure", CLEARED_STREET, crust, 2.0) == "passable"


def test_unknown_elevations_written_as_zero_are_not_sea_level():
    none_at_all = build_legs([(37.0, 55.0 + i * 0.001, 0.0) for i in range(3)], [], [{"from": 0, "to": 2, "highway": "path"}],
                             "s", "f", "w")[0]
    assert (none_at_all.min_ele, none_at_all.mean_ele, none_at_all.gradient_pct) == (None, None, 0.0)
    gap = [(37.0, 55.0, 200.0), (37.0, 55.001, 0.0), (37.0, 55.002, 210.0)]
    leg = build_legs(gap, [], [{"from": 0, "to": 2, "highway": "path"}], "s", "f", "w")[0]
    assert (leg.min_ele, leg.max_ele, leg.mean_ele) == (200.0, 210.0, 205.0) and leg.gradient_pct == 0.0
