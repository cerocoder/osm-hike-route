import pytest

import public_filter as pf
from public_filter import (
    Criteria, add_elevation, apply_final, assign_key_points, classify, criteria_from_number, find_key_points,
    find_start_places, interest_match, passes_tag_length, prefilter, rank,
)


def cand(cid=1, km=10.0, loop=None, network="lwn", start=(40.0, -4.0), track=None, tags=None, **extra):
    tags = {"name": f"R{cid}", **(tags or {})}
    return {"id": cid, "tags": tags, "network": network, "length_m": km * 1000, "is_loop": loop, "start": start,
            "track": track or [start, (start[0], start[1] + 0.01)], **extra}


class FakeOverpass:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, ql, **options):
        self.calls.append((ql, options))
        return self.outcomes.pop(0)


# ---- criteria and the cheap filters ----------------------------------------------------------------------------------------

def test_a_single_number_becomes_a_range_of_plus_minus_a_quarter():
    km = criteria_from_number(15, "km", loop=True)
    assert (km.min_km, km.max_km, km.loop) == (11.25, 18.75, True) and km.min_h is None
    h = criteria_from_number(4, "h")
    assert (h.min_h, h.max_h, h.min_km) == (3.0, 5.0, None)
    with pytest.raises(ValueError):
        criteria_from_number(1, "mi")


def test_the_tag_length_drops_a_clearly_wrong_route_before_the_geometry_is_loaded():
    criteria = Criteria(min_km=10, max_km=20)
    assert passes_tag_length({"tags": {"distance": "15"}}, criteria)
    assert passes_tag_length({"tags": {}}, criteria)                                   # no tag: load it
    assert not passes_tag_length({"tags": {"distance": "207"}}, criteria)
    assert not passes_tag_length({"tags": {"distance": "3"}}, criteria)
    assert passes_tag_length({"tags": {"distance": "22"}}, criteria)                   # inside the 15 % margin
    assert passes_tag_length({"tags": {"distance": "9"}}, criteria)


def test_prefilter_by_length_time_lower_bound_and_loop():
    criteria = Criteria(min_km=8, max_km=14, max_h=2.5, loop=True)
    assert prefilter(cand(km=10, loop=True), criteria, pace_kmh=4.5)
    assert not prefilter(cand(km=7.9, loop=True), criteria, 4.5)                       # too short
    assert not prefilter(cand(km=14.1, loop=True), criteria, 4.5)                      # too long
    assert not prefilter(cand(km=12, loop=True), criteria, 4.5)                        # 12 km / 4.5 = 2.67 h > 2.5 h even flat
    assert not prefilter(cand(km=10, loop=False), criteria, 4.5)                       # a linear route when loops are wanted
    assert prefilter(cand(km=10, loop=None), criteria, 4.5)                            # unknown loop-ness is kept
    assert not prefilter(cand(km=10, loop=True) | {"length_m": 0, "tags": {}}, criteria, 4.5)    # no length at all
    assert prefilter(cand(km=10, loop=False), Criteria(loop=False), 4.5)
    assert not prefilter(cand(km=10, loop=True), Criteria(loop=False), 4.5)


def test_the_distance_tag_is_the_length_when_plausible():
    assert prefilter(cand(km=14.4, tags={"distance": "13.1"}), Criteria(max_km=13.5), 4.5)


# ---- elevation, time ------------------------------------------------------------------------------------------------

class FakeService:
    def __init__(self, series):
        self.series, self.calls = list(series), []

    def get_elevations(self, points, progress=None):
        self.calls.append((list(points), progress))
        return [self.series.pop(0) if self.series else None for _ in points]


def line(n_points_km):
    """A track along the equator of about n_points_km kilometres (0.009 degrees is 1 km)."""
    return [(0.0, i * 0.009) for i in range(int(n_points_km) + 1)]


def test_elevations_of_all_candidates_go_in_one_call_and_give_ascent_and_descent():
    service = FakeService([100, 150, 120, 160, 200, 190])            # candidate 1: 4 samples, candidate 2: 2 samples
    a, b = cand(1, track=line(3)), cand(2, track=[(0.0, 0.0), (0.0, 0.0001)])
    marker = object()
    add_elevation([a, b], service, progress=marker, interval_m=1100.0)
    assert len(service.calls) == 1 and service.calls[0][1] is marker and len(service.calls[0][0]) == 6
    assert (a["ascent_m"], a["descent_m"]) == (90.0, 30.0)
    assert (b["ascent_m"], b["descent_m"]) == (0.0, 10.0)


def test_too_few_resolved_samples_leave_the_ascent_unknown():
    service = FakeService([100, None, None, 130])
    c = cand(1, track=line(3))
    add_elevation([c], service, interval_m=1000.0)
    assert c["ascent_m"] is None and c["descent_m"] is None


def test_no_candidates_means_no_elevation_request():
    service = FakeService([])
    add_elevation([], service)
    assert service.calls == []


def test_time_comes_from_the_planners_formula_and_the_final_criteria_apply():
    criteria = Criteria(min_h=2.0, max_h=3.0, max_ascent_m=500)
    flat, hilly, steep, short = (cand(1, km=9, ascent_m=300.0), cand(2, km=9, ascent_m=600.0),
                                 cand(3, km=9, ascent_m=0.0), cand(4, km=4, ascent_m=0.0))
    kept = apply_final([flat, hilly, steep, short], criteria, pace_kmh=4.5, ascent_minutes_per_100m=12)
    assert [c["id"] for c in kept] == [1, 3]                 # 2.6 h ok; 600 m ascent too much; 9/4.5 = 2.0 h ok; 0.9 h too short
    assert flat["duration_h"] == pytest.approx(2.0 + 0.6) and flat["length_km"] == 9.0 and flat["length_source"] == "computed"


def test_an_unknown_ascent_keeps_the_route_and_says_which_criteria_were_not_checked():
    criteria = Criteria(max_h=3.0, max_ascent_m=500)
    unknown = cand(1, km=9, ascent_m=None)
    kept = apply_final([unknown], criteria, 4.5, 12)
    assert kept == [unknown] and unknown["duration_h"] is None and unknown["unchecked"] == ["time", "ascent"]
    plain = cand(2, km=9, ascent_m=None)
    apply_final([plain], Criteria(min_km=1), 4.5, 12)
    assert plain["unchecked"] == []


# ---- key points -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tags,kind", [({"natural": "peak"}, "peak"), ({"natural": "saddle"}, "peak"),
                                       ({"tourism": "viewpoint"}, "viewpoint"), ({"historic": "ruins"}, "historic"),
                                       ({"natural": "water"}, "water"), ({"natural": "spring"}, "water"),
                                       ({"waterway": "waterfall"}, "water"), ({"tourism": "alpine_hut"}, "hut"),
                                       ({"tourism": "attraction"}, "sight"), ({"shop": "bakery"}, None), ({}, None)])
def test_classify(tags, kind):
    assert classify(tags) == kind


def test_one_query_for_the_union_of_the_boxes_and_only_named_classified_objects_survive(monkeypatch):
    fake = FakeOverpass({"elements": [
        {"type": "node", "lat": 0.001, "lon": 0.002, "tags": {"natural": "peak", "name": "Cerro", "ele": "819", "name:ru": "Серро"}},
        {"type": "way", "center": {"lat": 0.002, "lon": 0.003}, "tags": {"tourism": "viewpoint", "name": "Mirador"}},
        {"type": "node", "lat": 0.0, "lon": 0.0, "tags": {"tourism": "viewpoint"}},                    # unnamed
        {"type": "node", "lat": 0.0, "lon": 0.0, "tags": {"shop": "bakery", "name": "Pan"}},            # not a key point
        {"type": "node", "tags": {"natural": "peak", "name": "NoPosition"}}]})
    monkeypatch.setattr(pf, "query_overpass", fake)
    points = find_key_points([cand(1, track=[(0.0, 0.0), (0.01, 0.02)]), cand(2, track=[(0.03, 0.03), (0.04, 0.05)])],
                             cache_dir="c", progress="P")
    assert [(p["kind"], p["names"]["name"], p["ele"]) for p in points] == [("peak", "Cerro", "819"), ("viewpoint", "Mirador", None)]
    assert points[0]["names"]["name:ru"] == "Серро"
    ql, options = fake.calls[0]
    assert len(fake.calls) == 1 and "-0.00100,-0.00100,0.04100,0.05100" in ql and options == {"cache_dir": "c", "progress": "P", "timeout": 40, "retries": 1}
    assert find_key_points([]) == []


def test_a_point_is_on_the_route_by_its_distance_to_the_segment_not_to_the_vertices():
    track = [(0.0, 0.0), (0.0, 0.01)]                          # one 1.1 km segment: its vertices are far from the middle
    near = {"kind": "viewpoint", "lat": 0.0006, "lon": 0.005, "ele": None, "names": {"name": "Near"}}          # about 66 m off
    far = {"kind": "viewpoint", "lat": 0.0012, "lon": 0.005, "ele": None, "names": {"name": "Far"}}           # about 133 m off
    beyond = {"kind": "peak", "lat": 0.0, "lon": 0.02, "ele": None, "names": {"name": "Beyond"}}
    c = cand(1, track=track)
    assign_key_points(c, [far, near, beyond])
    assert [k["name"] for k in c["key_points"]] == ["Near"]
    assert 540 <= c["key_points"][0]["position_m"] <= 570


def test_key_points_are_in_route_order_deduplicated_and_named_in_the_users_language():
    track = [(0.0, 0.0), (0.0, 0.005), (0.0, 0.01)]
    points = [{"kind": "peak", "lat": 0.0, "lon": 0.009, "ele": "700", "names": {"name": "Late", "name:ru": "Поздняя"}},
              {"kind": "water", "lat": 0.0001, "lon": 0.001, "ele": None, "names": {"name": "Early"}},
              {"kind": "water", "lat": 0.0, "lon": 0.0011, "ele": None, "names": {"name": "Early"}}]
    c = cand(1, track=track)
    assign_key_points(c, points, lang="ru")
    assert [(k["kind"], k["name"], k["ele"]) for k in c["key_points"]] == [("water", "Early", None), ("peak", "Поздняя", "700")]
    assert [a["position_m"] < b["position_m"] for a, b in zip(c["key_points"], c["key_points"][1:])] == [True]


def test_the_nearest_settlement_within_three_kilometres_names_the_start(monkeypatch):
    fake = FakeOverpass({"elements": [
        {"type": "node", "lat": 0.001, "lon": 0.001, "tags": {"place": "village", "name": "Near"}},
        {"type": "node", "lat": 0.02, "lon": 0.02, "tags": {"place": "town", "name": "Further"}}]})
    monkeypatch.setattr(pf, "query_overpass", fake)
    a, b = cand(1, start=(0.0, 0.0)), cand(2, start=(0.5, 0.5))
    find_start_places([a, b])
    assert a["start_place"] == {"name": "Near"} and b["start_place"] is None and len(fake.calls) == 1
    find_start_places([])


# ---- order ------------------------------------------------------------------------------------------------------------

def test_interests_come_first_and_count_the_matching_key_points():
    plain = cand(1, key_points=[])
    scenic = cand(2, key_points=[{"kind": "peak"}, {"kind": "viewpoint"}, {"kind": "water"}], start=(41.0, -4.0))
    some = cand(3, key_points=[{"kind": "viewpoint"}], start=(40.5, -4.0))
    ordered, rules = rank([plain, some, scenic], Criteria(interests=("peak", "viewpoint")), location=(40.0, -4.0))
    assert [c["id"] for c in ordered] == [2, 3, 1] and rules == ["interests", "start", "network"]
    assert interest_match(scenic, ("peak", "viewpoint")) == 2 and interest_match(scenic, ()) == 0


def test_without_interests_the_practical_start_decides_and_an_access_point_counts():
    far, near, at_stop = cand(1, start=(41.5, -4.0)), cand(2, start=(40.1, -4.0)), cand(3, start=(40.9, -4.0))
    ordered, rules = rank([far, near, at_stop], Criteria(), location=(40.0, -4.0), access_points=[(40.9, -4.0)])
    assert [c["id"] for c in ordered] == [3, 2, 1] and rules == ["start", "network"]


def test_then_the_closeness_to_the_middle_of_the_range_for_length_and_time():
    criteria = Criteria(min_km=8, max_km=12, min_h=2, max_h=4)
    off, middle, close = cand(1, length_km=11.9, duration_h=3.9), cand(2, length_km=10.0, duration_h=3.0), cand(3, length_km=10.5, duration_h=3.1)
    ordered, rules = rank([off, close, middle], criteria)
    assert [c["id"] for c in ordered] == [2, 3, 1] and rules == ["range", "network"]


def test_then_the_network_level_and_the_completeness_and_finally_the_id():
    local, regional = cand(5, network="lwn"), cand(4, network="rwn")
    assert [c["id"] for c in rank([regional, local], Criteria())[0]] == [5, 4]
    bare = cand(6, tags={"name": None})
    full = cand(7, tags={"website": "https://x.org", "osmc:symbol": "red:white"})
    assert [c["id"] for c in rank([bare, full], Criteria())[0]] == [7, 6]
    twin_a, twin_b = cand(9), cand(8)
    assert [c["id"] for c in rank([twin_a, twin_b], Criteria())[0]] == [8, 9]
    assert rank([], Criteria()) == ([], ["network"])


def test_a_missing_duration_is_not_a_penalty_and_unknown_networks_sit_in_the_middle():
    criteria = Criteria(min_h=2, max_h=4)
    unknown_time = cand(1, duration_h=None, length_km=10)
    ordered, _ = rank([unknown_time, cand(2, network=None), cand(3, network="ncn")], Criteria())
    assert [c["id"] for c in ordered] == [1, 2, 3]
    assert rank([unknown_time], criteria)[0] == [unknown_time]


def test_the_optional_queries_never_wait_as_long_as_the_main_ones(monkeypatch):
    fake = FakeOverpass({"elements": []}, {"elements": []})
    monkeypatch.setattr(pf, "query_overpass", fake)
    find_key_points([cand(1)])
    find_start_places([cand(1)])
    assert [call[1]["timeout"] for call in fake.calls] == [40, 40] and [call[1]["retries"] for call in fake.calls] == [1, 1]
