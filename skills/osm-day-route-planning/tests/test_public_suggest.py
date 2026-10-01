import io
import json
import re
from pathlib import Path

import pytest

import public_filter as pf
import public_routes as pr
from progress import Progress
from public_filter import Criteria, criteria_from_number
from public_suggest import suggest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"public_{name}.json").read_text(encoding="utf-8"))["elements"][0]


def synthetic(rid, km, name, network="lwn", **tags):
    """A straight one-way relation of about `km` kilometres along the equator (0.009 degrees is 1 km)."""
    n = int(km) + 1
    points = [{"lat": 0.0, "lon": rid * 0.0001 + i * 0.009} for i in range(n)]
    member = {"type": "way", "ref": rid * 10, "role": "", "geometry": points}
    return {"type": "relation", "id": rid, "tags": {"name": name, "network": network, **tags}, "members": [member]}


class World:
    """Stands in for query_overpass: answers each kind of query from a table of relations."""

    def __init__(self, relations, key_points=(), places=(), fail=None):
        self.relations = {r["id"]: r for r in relations}
        self.key_points, self.places, self.fail = list(key_points), list(places), fail
        self.queries = []

    def __call__(self, ql, **options):
        self.queries.append(ql)
        if self.fail and self.fail in ql:
            raise RuntimeError("HTTP 504")
        if "out tags center;" in ql and '"route"' in ql:
            return {"elements": [{"type": "relation", "id": r["id"], "tags": r["tags"], "center": {"lat": 0, "lon": 0}}
                                 for r in self.relations.values()]}
        if "relation(id:" in ql:
            ids = [int(i) for i in ql.split("relation(id:")[1].split(")")[0].split(",")]
            return {"elements": [self.relations[i] for i in ids]}
        if "peak|saddle" in ql:
            return {"elements": self.key_points}
        if '"place"' in ql:
            return {"elements": self.places}
        raise AssertionError(f"unexpected query {ql[:80]}")


class Service:
    """Elevations that rise `rise` metres every sample: a route of n samples climbs rise * (n - 1) metres."""

    def __init__(self, known=True, rise=20.0):
        self.known, self.rise, self.calls = known, rise, []

    def get_elevations(self, points, progress=None):
        self.calls.append(len(points))
        return [100.0 + self.rise * i for i in range(len(points))] if self.known else [None] * len(points)


@pytest.fixture
def patch_world(monkeypatch):
    def install(world):
        monkeypatch.setattr(pr, "query_overpass", world)
        monkeypatch.setattr(pf, "query_overpass", world)
        return world
    return install


def real_relations():
    return [dict(fixture("boqueron"), members=fixture("boqueron")["members"]),
            dict(fixture("thorlen"), members=fixture("thorlen")["members"]),
            dict(fixture("vyatichi"), members=fixture("vyatichi")["members"])]


def run(world, criteria, **kwargs):
    defaults = dict(lat=40.36, lon=-4.33, mode="walk", pace_kmh=4.5, ascent_minutes_per_100m=12, service=Service(), lang="en")
    defaults.update(kwargs)
    return suggest(criteria=criteria, **defaults)


def test_real_relations_are_filtered_named_ordered_and_listed(patch_world):
    world = patch_world(World(real_relations(), key_points=[
        {"type": "node", "lat": 40.3642, "lon": -4.3308, "tags": {"tourism": "viewpoint", "name": "Mirador del Pantano"}}]))
    result = run(world, criteria_from_number(11, "km"))
    assert [c["id"] for c in result["shown"]] == [67441, 31003]               # 11.1 km before 13.1 km, the 1.7 km one is out
    assert result["matching"] == 2 and result["failed"] is False and result["lost"] == 0
    assert result["rules"] == ["start", "range", "network"]
    lines = result["text"].split("\n")
    assert lines[0] == "Public routes that match your criteria (2 of 2):"
    assert lines[2].startswith("1. Ruta del Boquerón") and "~11.1 km" in lines[2] and "↑" in lines[2]
    assert lines[3].startswith("2. Rund um die Thörlen") and "13.1 km" in lines[3] and "~13.1" not in lines[3]
    assert lines[-2] == "3. Own route"


def test_a_key_point_on_the_track_names_the_route(patch_world):
    member = next(m for m in fixture("boqueron")["members"] if len(m.get("geometry") or []) > 5)
    track_point = member["geometry"][5]
    world = patch_world(World(real_relations()[:1], key_points=[
        {"type": "node", "lat": track_point["lat"], "lon": track_point["lon"], "tags": {"natural": "peak", "name": "Cerro X", "ele": "819"}}]))
    result = run(world, Criteria(min_km=10, max_km=12))
    assert "via Cerro X (819 m)" in result["text"]


def test_time_is_judged_with_the_modes_pace_and_the_ascent_rate(patch_world):
    def rerun(criteria, **kwargs):
        return run(patch_world(World([synthetic(1, 10, "Flat-ish")])), criteria, service=Service(rise=1.0), **kwargs)

    route = rerun(Criteria())["shown"][0]
    assert 60 <= route["ascent_m"] <= 70
    assert route["duration_h"] == pytest.approx(10.0 / 4.5 + route["ascent_m"] / 100.0 * 12 / 60.0, rel=0.02)
    assert rerun(Criteria(max_h=route["duration_h"] - 0.2))["matching"] == 0         # the ascent pushes it over
    assert rerun(Criteria(max_h=route["duration_h"] + 0.2))["matching"] == 1
    assert rerun(Criteria(max_ascent_m=route["ascent_m"] - 5))["matching"] == 0
    assert rerun(Criteria(min_h=route["duration_h"] + 0.2))["matching"] == 0


def test_a_bicycle_uses_its_own_pace(patch_world):
    def rerun(**kwargs):
        world = patch_world(World([synthetic(1, 30, "Ride", network="rcn")]))
        return world, run(world, Criteria(), service=Service(rise=0.1), **kwargs)

    _, walk = rerun(mode="walk")
    world, bike = rerun(mode="bike", pace_kmh=15, ascent_minutes_per_100m=10)
    assert bike["shown"][0]["duration_h"] < walk["shown"][0]["duration_h"] / 2
    assert '"^(bicycle|mtb)$"' in world.queries[0]


def test_long_distance_routes_are_counted_not_listed_and_nothing_matching_leaves_only_the_own_route(patch_world):
    world = patch_world(World([synthetic(1, 5, "Short"), synthetic(2, 40, "Camino", network="nwn")]))
    result = run(world, Criteria(min_km=20, max_km=30), lang="ru")
    assert result["matching"] == 0 and result["long_nearby"] == 1
    assert result["text"].split("\n") == ["Ни один публичный маршрут не подходит под ваши критерии.",
                                          "Дальних многодневных маршрутов рядом (не показаны): 1.", "1. Свой маршрут",
                                          "Выберите номер или «Свой маршрут»."]


def test_at_most_ten_are_shown_and_the_rest_is_counted(patch_world):
    world = patch_world(World([synthetic(i, 8 + i * 0.1, f"Route {i:02d}") for i in range(1, 13)]))
    result = run(world, Criteria(min_km=5, max_km=20))
    assert len(result["shown"]) == 10 and result["matching"] == 12
    assert "More matching routes: 2." in result["text"] and "(10 of 12)" in result["text"]
    assert result["text"].split("\n")[-2] == "11. Own route"


def test_a_failed_lookup_offers_only_the_own_route_and_asks_nothing_more(patch_world):
    world = patch_world(World([synthetic(1, 10, "X")], fail="out tags center"))
    result = run(world, Criteria(), lang="ru")
    assert result["failed"] is True and result["shown"] == [] and len(world.queries) == 1
    lines = result["text"].split("\n")
    assert lines[0].startswith("Публичные маршруты найти не удалось (") and lines[1] == "1. Свой маршрут"


def test_a_geometry_failure_leaves_those_routes_out_and_says_so(patch_world):
    world = patch_world(World([synthetic(1, 10, "A"), synthetic(2, 10, "B")], fail="relation(id:"))
    result = run(world, Criteria())
    assert result["lost"] == 2 and result["matching"] == 0
    assert "Routes that could not be loaded and are left out: 2." in result["text"]


def test_a_key_point_or_place_failure_does_not_remove_the_routes(patch_world):
    world = patch_world(World([synthetic(1, 10, "A")], fail="peak|saddle"))
    result = run(world, Criteria())
    assert result["matching"] == 1 and result["shown"][0]["key_points"] == []
    world = patch_world(World([synthetic(1, 10, "A")], fail='"place"'))
    result = run(world, Criteria())
    assert result["matching"] == 1 and result["shown"][0]["start_place"] is None


def test_without_elevations_the_routes_are_kept_and_the_unchecked_criteria_are_said(patch_world):
    world = patch_world(World([synthetic(1, 10, "A")]))
    result = run(world, Criteria(max_h=3.0, max_ascent_m=100), service=Service(known=False))
    assert result["matching"] == 1 and result["shown"][0]["unchecked"] == ["time", "ascent"]
    assert "↑—" in result["text"] and "no elevation data" in result["text"]


def test_a_duplicate_relation_is_listed_once_with_the_longest_geometry(patch_world):
    world = patch_world(World([synthetic(1, 8, "Twin", ref="7"), synthetic(2, 10, "Twin", ref="7")]))
    result = run(world, Criteria(min_km=5, max_km=20))
    assert [c["id"] for c in result["shown"]] == [2]


def test_the_progress_steps_run_in_order_and_speak_the_users_language(patch_world):
    world = patch_world(World([synthetic(1, 10, "A")]))
    stream = io.StringIO()
    run(world, Criteria(), progress=Progress(total_steps=4, lang="ru", stream=stream), lang="ru")
    starts = [l for l in stream.getvalue().splitlines() if l.startswith("[")]
    assert starts == ["[1/4] Публичные маршруты: поиск …", "[2/4] Публичные маршруты: геометрия …",
                      "[3/4] Публичные маршруты: высоты …", "[4/4] Публичные маршруты: ключевые точки …"]
    assert "найдено 1, дальних (многодневных) пропущено 0" in stream.getvalue() and "подходят 1, показано 1" in stream.getvalue()
    assert not re.search(r"\b(Public|routes|found|match)\b", stream.getvalue())


def test_the_practical_start_rule_uses_the_anchor_and_the_access_points(patch_world):
    def world_of_two():
        near, far = synthetic(1, 10, "Near"), synthetic(2, 10, "Far")
        for point in far["members"][0]["geometry"]:
            point["lon"] += 1.0
        return patch_world(World([far, near]))

    result = run(world_of_two(), Criteria(), lat=0.0, lon=0.0)
    assert [c["tags"]["name"] for c in result["shown"]] == ["Near", "Far"] and result["rules"][0] == "start"
    by_stop = run(world_of_two(), Criteria(), lat=0.0, lon=0.0, location=(5.0, 5.0), access_points=[(0.0, 1.0)])
    assert [c["tags"]["name"] for c in by_stop["shown"]] == ["Far", "Near"]


def test_a_surprise_inside_the_step_never_blocks_the_planning(patch_world, monkeypatch):
    import public_suggest
    world = patch_world(World([synthetic(1, 10, "A")]))

    def boom(*args, **kwargs):
        raise ValueError("unexpected")

    monkeypatch.setattr(public_suggest, "add_elevation", boom)
    result = run(world, Criteria(), lang="ru")
    assert result["failed"] is True and result["shown"] == [] and result["found"] == 1
    lines = result["text"].split("\n")
    assert lines[0].startswith("Публичные маршруты найти не удалось (ValueError: unexpected") and lines[1] == "1. Свой маршрут"


def test_the_result_says_how_many_public_routes_were_found_including_the_long_ones(patch_world):
    world = patch_world(World([synthetic(1, 5, "Short"), synthetic(2, 40, "Camino", network="nwn")]))
    assert run(world, Criteria())["found"] == 2


def test_a_strange_elevation_tag_on_a_key_point_does_not_break_the_list(patch_world):
    member = synthetic(1, 10, "A")["members"][0]["geometry"][3]
    world = patch_world(World([synthetic(1, 10, "A")], key_points=[
        {"type": "node", "lat": member["lat"], "lon": member["lon"], "tags": {"natural": "peak", "name": "Cerro", "ele": "inf"}}]))
    result = run(world, Criteria())
    assert result["failed"] is False and "via Cerro" in result["text"]
