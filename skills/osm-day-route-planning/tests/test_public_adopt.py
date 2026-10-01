import pytest

import public_adopt as pa
from public_adopt import AdoptionError, NodeIndex, adopt, curated_source

STEP = 0.001                       # 111 m between nodes along the equator


def line_graph(n=12, extra=None):
    """Nodes 0..n-1 along the equator, two-way edges of 111 m; `extra` {node: (lat, lon, neighbour)} adds a spur."""
    coords = {i: (0.0, i * STEP) for i in range(n)}
    graph = {i: [] for i in range(n)}
    for i in range(n - 1):
        graph[i].append([i + 1, 111.0, {}])
        graph[i + 1].append([i, 111.0, {}])
    for node, (lat, lon, neighbour) in (extra or {}).items():
        coords[node] = (lat, lon)
        graph[node] = [[neighbour, 80.0, {}]]
        graph[neighbour].append([node, 80.0, {}])
    return graph, coords


def candidate(n=12, **over):
    track = [(0.0, i * STEP) for i in range(n)]
    return {"id": 42, "tags": {"name": "Test", "ref": "T1", "operator": "Club", "website": "https://club.example/t1"},
            "network": "lwn", "track": track, "gaps": False, "length_source": "computed", **over}


def test_the_node_index_finds_the_nearest_node_within_the_radius_only():
    coords = {1: (0.0, 0.0), 2: (0.0, 0.0004), 3: (0.01, 0.01)}
    index = NodeIndex(coords)
    assert index.nearest(0.0, 0.0003) == 2 and index.nearest(0.0, -0.0002) == 1
    assert index.nearest(0.0, 0.0012, 60.0) is None and index.nearest(0.0, 0.0012, 90.0) == 2
    assert NodeIndex({}).nearest(0.0, 0.0) is None


def test_a_route_that_lies_on_the_graph_is_followed_exactly():
    graph, coords = line_graph()
    result = adopt(candidate(), graph, coords, {})
    assert result["path"] == list(range(12)) and result["fidelity"] == 1.0
    assert result["deviates"] is False and result["dropped_samples"] == 0 and result["inserted"] == []


def test_a_sample_with_no_road_near_is_dropped_and_the_rest_still_routes():
    graph, coords = line_graph(12)
    track = [(0.0, i * STEP) for i in range(5)] + [(0.01, 0.005)] + [(0.0, i * STEP) for i in range(6, 12)]
    result = adopt(candidate(track=track), graph, coords, {})
    assert result["path"][0] == 0 and result["path"][-1] == 11 and result["dropped_samples"] >= 1


def test_a_waypoint_that_cannot_be_reached_is_skipped_not_fatal():
    graph, coords = line_graph(12)
    graph[5] = [e for e in graph[5] if e[0] != 6]              # cut the line between nodes 5 and 6
    graph[6] = [e for e in graph[6] if e[0] != 5]
    result = adopt(candidate(), graph, coords, {})
    assert result["dropped_samples"] >= 1 and result["path"][0] == 0 and result["path"][-1] == 5
    assert result["precision"] == 1.0 and result["coverage"] < 0.6          # half of the route was left out ...
    assert result["fidelity"] == result["coverage"] and result["deviates"] is True    # ... and that is reported, not hidden


def test_a_path_that_leaves_the_public_track_is_measured_and_reported():
    graph, coords = line_graph(6)
    coords[200] = (0.003, 2.5 * STEP)                          # a node 333 m off the line, reached by a cheap detour
    graph[200] = [[2, 10.0, {}], [3, 10.0, {}]]
    graph[2] = [e for e in graph[2] if e[0] != 3] + [[200, 10.0, {}]]
    graph[3] = [e for e in graph[3] if e[0] != 2] + [[200, 10.0, {}]]
    graph[2].append([3, 5000.0, {}])                           # the line itself is expensive between 2 and 3
    graph[3].append([2, 5000.0, {}])
    result = adopt(candidate(6), graph, coords, {})
    assert result["path"] == [0, 1, 2, 200, 3, 4, 5]
    assert result["fidelity"] == round(6 / 7, 3) and result["deviates"] is True


def test_gaps_and_an_empty_graph_are_refused_with_a_reason():
    graph, coords = line_graph()
    with pytest.raises(AdoptionError, match="gaps"):
        adopt(candidate(gaps=True), graph, coords, {})
    far = candidate(track=[(5.0, 5.0), (5.0, 5.001)])
    with pytest.raises(AdoptionError, match="not on the graph"):
        adopt(far, graph, coords, {})


def test_an_extra_point_is_inserted_at_the_cheapest_place():
    graph, coords = line_graph(12, extra={50: (0.0007, 6 * STEP, 6)})
    result = adopt(candidate(), graph, coords, {}, extra_nodes=[50])
    path = result["path"]
    assert result["inserted"] == [50] and 50 in path
    i = path.index(50)
    assert path[i - 1] == 6 and path[i + 1] == 6              # a there-and-back off node 6, not a detour elsewhere
    assert path[0] == 0 and path[-1] == 11


def test_an_unreachable_extra_point_is_refused():
    graph, coords = line_graph(12)
    graph[99], coords[99] = [], (0.0, 0.0055)
    with pytest.raises(AdoptionError, match="added point"):
        adopt(candidate(), graph, coords, {}, extra_nodes=[99])


def test_progress_ticks_once_per_leg():
    graph, coords = line_graph(6)

    class Recorder:
        def __init__(self):
            self.ticks = []

        def tick(self, done, total, key="tag_progress", **params):
            self.ticks.append((done, total, key))

    recorder = Recorder()
    adopt(candidate(6), graph, coords, {}, progress=recorder)
    assert recorder.ticks and recorder.ticks[0][2] == "route_leg" and recorder.ticks[-1][0] == recorder.ticks[-1][1]


def test_the_curated_source_property_keeps_only_a_web_link_and_rounds_the_fidelity():
    assert curated_source(candidate(), 0.895)["fidelity"] == 0.89           # rounded down: never looks better than it is
    source = curated_source(candidate(), 0.93456)
    assert source == {"relation_id": 42, "name": "Test", "ref": "T1", "network": "lwn", "operator": "Club",
                      "website": "https://club.example/t1", "length_source": "computed", "fidelity": 0.93}
    unsafe = curated_source({**candidate(), "tags": {"website": "javascript:alert(1)"}}, 1.0)
    assert unsafe["website"] is None and unsafe["name"] is None and unsafe["ref"] is None


def test_a_route_cut_off_at_its_start_is_refused_not_reported_as_faithful():
    graph, coords = line_graph(12)
    graph[0] = []                                                    # node 0 is isolated
    graph[1] = [e for e in graph[1] if e[0] != 0]
    with pytest.raises(AdoptionError, match="cut off"):
        adopt(candidate(), graph, coords, {})


def test_an_extra_point_that_could_not_be_used_is_not_listed_as_inserted():
    graph, coords = line_graph(12, extra={50: (0.0007, 6 * STEP, 6)})
    result = adopt(candidate(), graph, coords, {}, extra_nodes=[50])
    assert result["inserted"] == [50] and result["precision"] > 0.9 and result["coverage"] == 1.0


def test_the_node_index_cells_stay_wide_enough_near_the_pole():
    coords = {1: (85.0, 0.0), 2: (85.0, 0.0006)}                     # about 58 m apart at 85 degrees
    assert NodeIndex(coords).nearest(85.0, 0.0, 60.0) in (1, 2)
    assert NodeIndex(coords).nearest(85.0, 0.00055, 10.0) == 2
