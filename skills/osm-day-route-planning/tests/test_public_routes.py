import json
from pathlib import Path

import pytest

import public_routes as pr
from public_routes import build_track, dedupe, find_candidates, length_km, load_tracks, parse_distance_km

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"public_{name}.json").read_text(encoding="utf-8"))["elements"][0]


def way(ref, *points, role=""):
    return {"type": "way", "ref": ref, "role": role, "geometry": [{"lat": a, "lon": b} for a, b in points]}


class FakeOverpass:
    """Stands in for public_routes.query_overpass: answers come from a list of payloads or exceptions."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, ql, **options):
        self.calls.append((ql, options))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Recorder:
    def __init__(self):
        self.ticks = []

    def tick(self, done, total, key="tag_progress", **params):
        self.ticks.append((done, total, key))


# ---- candidates -------------------------------------------------------------------------------------------------------

def relation(rid, **tags):
    return {"type": "relation", "id": rid, "tags": tags, "center": {"lat": 1.0, "lon": 2.0}}


def test_candidates_are_filtered_and_long_distance_routes_are_only_counted(monkeypatch):
    fake = FakeOverpass({"elements": [
        relation(1, name="Local loop", network="lwn"),
        relation(2, name="Regional", network="rwn"),
        relation(3, name="Camino", network="nwn"),
        relation(4, name="Euro trail", network="iwn"),
        relation(5, name="Planned", network="lwn", state="proposed"),
        relation(6, name="Gone", network="lwn", state="abandoned"),
        relation(7, name="Private", network="lwn", access="private"),
        relation(1, name="Local loop", network="lwn"),                      # the same relation twice
        {"type": "node", "id": 9, "tags": {}},
        relation(8, name="No network")]})
    monkeypatch.setattr(pr, "query_overpass", fake)
    result = find_candidates(40.0, -4.0, 15000, "walk")
    assert [c["id"] for c in result["candidates"]] == [1, 2, 8] and result["long_nearby"] == 2
    ql, options = fake.calls[0]
    assert 'relation["route"~"^(hiking|foot)$"](around:15000,40.0,-4.0)' in ql and options == {}


def test_include_long_keeps_the_long_networks_and_the_mode_picks_the_route_tags(monkeypatch):
    fake = FakeOverpass({"elements": [relation(3, network="ncn")]})
    monkeypatch.setattr(pr, "query_overpass", fake)
    result = find_candidates(1.0, 2.0, 5000, "bike", cache_dir="cache", progress="P", include_long=True)
    assert [c["id"] for c in result["candidates"]] == [3] and result["long_nearby"] == 0
    assert '"^(bicycle|mtb)$"' in fake.calls[0][0] and fake.calls[0][1] == {"cache_dir": "cache", "progress": "P"}


# ---- tracks from real relations ---------------------------------------------------------------------------------------

def test_a_real_linear_relation_gives_one_track_with_its_length_and_ends():
    track = build_track(pr._member_ways(fixture("vyatichi")))
    assert track["gaps"] is False and track["is_loop"] is False and track["chains"] in (1, 2)
    assert 1.65 <= track["length_m"] / 1000 <= 1.75 and track["coverage"] == 1.0
    assert track["start"] != track["end"] and len(track["track"]) >= 30


def test_a_real_relation_with_gaps_of_a_few_metres_is_still_one_route():
    track = build_track(pr._member_ways(fixture("boqueron")))
    assert track["gaps"] is False and track["coverage"] >= 0.99
    assert 11.0 <= track["length_m"] / 1000 <= 11.3


def test_a_real_loop_is_recognised_and_a_detached_piece_does_not_break_it():
    element = fixture("thorlen")
    track = build_track(pr._member_ways(element))
    assert track["is_loop"] is True and track["gaps"] is False and 0.85 <= track["coverage"] < 1.0
    assert length_km({"tags": element["tags"], "length_m": track["length_m"]}) == (13.1, "tag")


def test_ways_are_stitched_whatever_their_direction_and_order():
    a, b, c = [(0.0, 0.0), (0.0, 0.001)], [(0.0, 0.002), (0.0, 0.001)], [(0.0, 0.002), (0.0, 0.003)]   # b runs backwards
    track = build_track([(3, c), (1, a), (2, b)])
    assert track["gaps"] is False and track["chains"] == 1
    lons = [p[1] for p in track["track"]]
    assert lons == sorted(lons) or lons == sorted(lons, reverse=True)
    assert lons[0] in (0.0, 0.003) and lons[-1] in (0.0, 0.003)


def test_a_way_listed_twice_counts_once_and_a_real_break_is_a_gap():
    a, far = [(0.0, 0.0), (0.0, 0.001)], [(0.0, 0.01), (0.0, 0.011)]
    once = build_track([(1, a)])
    twice = build_track([(1, a), (1, a)])
    assert twice["length_m"] == once["length_m"]
    broken = build_track([(1, a), (2, far)])
    assert broken["gaps"] is True and broken["chains"] == 2 and broken["is_loop"] is None
    assert 0.45 <= broken["coverage"] <= 0.55


def test_a_loop_is_a_track_whose_ends_meet():
    ring = [(0.0, 0.0), (0.0, 0.002), (0.002, 0.002), (0.0, 0.0001)]
    assert build_track([(1, ring)])["is_loop"] is True
    line = build_track([(1, [(0.0, 0.0), (0.0, 0.01)])])
    assert line["is_loop"] is False


def test_an_empty_relation_has_no_track():
    track = build_track([])
    assert track["track"] == [] and track["gaps"] is True and track["start"] is None


def test_member_ways_skip_variants_nodes_and_degenerate_geometry():
    element = {"members": [
        way(1, (0, 0), (0, 1)), way(2, (0, 1), (0, 2), role="alternative"), way(3, (0, 2), (0, 3), role="excursion"),
        {"type": "node", "ref": 5}, {"type": "way", "ref": 6, "geometry": [{"lat": 0, "lon": 0}]},
        {"type": "relation", "ref": 7}, way(4, (0, 1), (0, 2))]}
    assert [w[0] for w in pr._member_ways(element)] == [1, 4]


# ---- geometry loading -------------------------------------------------------------------------------------------------

def relation_geometry(rid, *ways):
    return {"type": "relation", "id": rid, "tags": {}, "members": list(ways)}


def test_geometry_comes_in_batches_with_one_tick_each_and_a_failed_single_relation_is_lost(monkeypatch):
    good = lambda *ids: {"elements": [relation_geometry(i, way(i * 10, (0.0, 0.0), (0.0, 0.001))) for i in ids]}
    fake = FakeOverpass(good(1, 2), RuntimeError("504"))
    monkeypatch.setattr(pr, "query_overpass", fake)
    recorder = Recorder()
    loaded, lost = load_tracks([{"id": i, "tags": {}} for i in (1, 2, 3)], progress=recorder, batch=2)
    assert [c["id"] for c in loaded] == [1, 2] and lost == 1
    assert [call[0].split("relation(id:")[1].split(")")[0] for call in fake.calls] == ["1,2", "3"]
    assert recorder.ticks == [(1, 2, "public_geometry_batch"), (2, 2, "public_geometry_batch")]
    assert all("ways" not in c and c["length_m"] > 0 for c in loaded)
    assert fake.calls[0][1]["timeout"] == 60 and fake.calls[0][1]["retries"] == 1      # a failure is split, not waited out


def test_one_heavy_relation_does_not_take_its_batch_with_it(monkeypatch):
    class Picky:
        """Fails whenever relation 2 is part of the query, like a huge route that makes Overpass time out."""

        def __init__(self):
            self.calls = []

        def __call__(self, ql, **options):
            ids = [int(i) for i in ql.split("relation(id:")[1].split(")")[0].split(",")]
            self.calls.append(ids)
            if 2 in ids:
                raise RuntimeError("504")
            return {"elements": [relation_geometry(i, way(i * 10, (0.0, 0.0), (0.0, 0.001))) for i in ids]}

    picky = Picky()
    monkeypatch.setattr(pr, "query_overpass", picky)
    loaded, lost = load_tracks([{"id": i, "tags": {}} for i in (1, 2, 3, 4)], batch=4)
    assert [c["id"] for c in loaded] == [1, 3, 4] and lost == 1
    assert picky.calls == [[1, 2, 3, 4], [1, 2], [3, 4], [1], [2]]         # halves level by level, then the heavy one alone


def test_a_dead_server_is_given_up_after_three_failures_in_a_row(monkeypatch):
    calls = []

    def dead(ql, **options):
        calls.append(ql)
        raise RuntimeError("down")

    monkeypatch.setattr(pr, "query_overpass", dead)
    loaded, lost = load_tracks([{"id": i, "tags": {}} for i in range(1, 9)], batch=4)
    assert loaded == [] and lost == 8 and len(calls) == 3


def test_a_relation_without_geometry_is_lost_and_the_rest_of_the_batch_is_kept(monkeypatch):
    fake = FakeOverpass({"elements": [relation_geometry(3, way(30, (0.0, 0.0), (0.0, 0.001))), relation_geometry(4)]})
    monkeypatch.setattr(pr, "query_overpass", fake)
    loaded, lost = load_tracks([{"id": 3, "tags": {}}, {"id": 4, "tags": {}}], batch=2)
    assert [c["id"] for c in loaded] == [3] and lost == 1


# ---- length, duplicates -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [("13.1", 13.1), ("13,1", 13.1), (" 13 km ", 13.0), ("13000 m", 13.0),
                                           ("207", 207.0), ("about 13", None), ("", None), (None, None), ("13 miles", None)])
def test_parse_distance_km(text, expected):
    assert parse_distance_km(text) == expected


def test_the_tag_wins_when_plausible_and_the_computed_length_when_not():
    assert length_km({"tags": {"distance": "13.1"}, "length_m": 14440}) == (13.1, "tag")
    assert length_km({"tags": {"distance": "13100"}, "length_m": 14440}) == (14.44, "computed")     # metres as kilometres
    assert length_km({"tags": {}, "length_m": 11120}) == (11.12, "computed")
    assert length_km({"tags": {"distance": "9"}}) == (9.0, "tag")
    assert length_km({"tags": {}}) == (None, None)


def test_duplicates_with_the_same_ref_and_name_keep_the_longest_geometry():
    candidates = [{"id": 1, "tags": {"ref": "811", "name": "Thörlen"}, "length_m": 100},
                  {"id": 2, "tags": {"ref": "811", "name": "THÖRLEN"}, "length_m": 900},
                  {"id": 3, "tags": {"name": "Other"}, "length_m": 50},
                  {"id": 4, "tags": {}, "length_m": 10}, {"id": 5, "tags": {}, "length_m": 20}]
    kept, duplicates = dedupe(candidates)
    assert [c["id"] for c in kept] == [2, 3, 4, 5] and duplicates == 1


@pytest.mark.parametrize("bad_position", [0, 9, 10, 19, 20, 42])
def test_one_heavy_relation_costs_exactly_itself_wherever_it_sits(monkeypatch, bad_position):
    ids = list(range(1, 44))
    bad = ids[bad_position]
    calls = []

    def picky(ql, **options):
        queried = [int(i) for i in ql.split("relation(id:")[1].split(")")[0].split(",")]
        calls.append(queried)
        if bad in queried:
            raise RuntimeError("504")
        return {"elements": [relation_geometry(i, way(i * 10, (0.0, 0.0), (0.0, 0.001))) for i in queried]}

    monkeypatch.setattr(pr, "query_overpass", picky)
    loaded, lost = load_tracks([{"id": i, "tags": {}} for i in ids], batch=20)
    assert lost == 1 and sorted(c["id"] for c in loaded) == [i for i in ids if i != bad]
    assert len(calls) < 43                                                    # far fewer queries than one per relation


def test_a_super_relation_without_ways_is_skipped_not_counted_as_lost(monkeypatch):
    members = [{"type": "relation", "ref": 5, "role": ""}]
    only_variants = [way(9, (0.0, 0.0), (0.0, 0.001), role="alternative")]
    fake = FakeOverpass({"elements": [relation_geometry(1, *members), relation_geometry(2, *only_variants),
                                      relation_geometry(3), relation_geometry(4, way(40, (0.0, 0.0), (0.0, 0.001)))]})
    monkeypatch.setattr(pr, "query_overpass", fake)
    loaded, lost = load_tracks([{"id": i, "tags": {}} for i in (1, 2, 3, 4)], batch=4)
    assert [c["id"] for c in loaded] == [4] and lost == 1                      # only the relation with no members at all


def test_a_server_that_simply_omits_a_relation_does_not_make_it_loaded(monkeypatch):
    monkeypatch.setattr(pr, "query_overpass", FakeOverpass({"elements": [relation_geometry(1, way(10, (0.0, 0.0), (0.0, 0.001)))]}))
    loaded, lost = load_tracks([{"id": 1, "tags": {}}, {"id": 2, "tags": {}}], batch=2)
    assert [c["id"] for c in loaded] == [1]


def test_a_short_spur_listed_at_a_junction_does_not_split_the_route():
    a = [(0.0, 0.0), (0.0, 0.054)]                         # 6 km
    spur = [(0.0, 0.054), (0.0005, 0.054)]                 # 55 m, starts at the junction
    b = [(0.0, 0.054), (0.0, 0.108)]                       # 6 km, also starts at the junction
    in_the_middle = build_track([(1, a), (2, spur), (3, b)])
    at_the_end = build_track([(1, a), (3, b), (2, spur)])
    for track in (in_the_middle, at_the_end):
        assert track["gaps"] is False and track["coverage"] > 0.99 and track["is_loop"] is False
    assert abs(in_the_middle["length_m"] - at_the_end["length_m"]) < 1.0


def test_ends_a_few_metres_apart_are_joined_even_near_the_pole():
    a = [(85.0, 0.0), (85.0, 0.01)]
    near = [(85.0, 0.01 + 0.0002), (85.0, 0.02)]            # 0.0002 degrees of longitude at 85 degrees is about 2 m
    far = [(85.0, 0.0201), (85.0, 0.03)]                    # 0.0101 degrees from the end of `a`: about 98 m, a real gap
    assert build_track([(1, a), (2, near)])["chains"] == 1
    assert build_track([(1, a), (2, far)])["chains"] == 2


def test_the_same_name_without_a_ref_is_one_route_only_at_the_same_place():
    here = {"id": 1, "tags": {"name": "Ruta circular"}, "length_m": 100, "start": (40.001, -4.001)}
    twin = {"id": 2, "tags": {"name": "Ruta circular"}, "length_m": 900, "start": (40.002, -4.002)}
    elsewhere = {"id": 3, "tags": {"name": "Ruta circular"}, "length_m": 500, "start": (41.5, -3.0)}
    kept, duplicates = dedupe([here, twin, elsewhere])
    assert [c["id"] for c in kept] == [2, 3] and duplicates == 1
