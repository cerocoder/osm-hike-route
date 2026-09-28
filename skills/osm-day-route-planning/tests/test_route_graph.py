from route_graph import build_graph


def _two_node_way(node_a=1, node_b=2, tags=None):
    return [{
        "nodes": [node_a, node_b],
        "geometry": [{"lat": 55.0, "lon": 37.0}, {"lat": 55.001, "lon": 37.0}],
        "tags": tags or {},
    }]


def test_two_way_segment_is_traversable_in_both_directions_by_default():
    graph, _ = build_graph(_two_node_way())

    neighbors_of_1 = [edge[0] for edge in graph[1]]
    neighbors_of_2 = [edge[0] for edge in graph[2]]

    assert 2 in neighbors_of_1
    assert 1 in neighbors_of_2


def test_oneway_segment_is_forward_only_when_respect_oneway_true():
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 not in [edge[0] for edge in graph.get(2, [])]


def test_oneway_ignored_when_respect_oneway_false():
    """walk mode: oneway restrictions never apply, even if the tag is present."""
    way = _two_node_way(tags={"oneway": "yes"})

    graph, _ = build_graph(way, respect_oneway=False)

    assert 1 in [edge[0] for edge in graph.get(2, [])]


def test_oneway_bicycle_no_reopens_reverse_direction():
    way = _two_node_way(tags={"oneway": "yes", "oneway:bicycle": "no"})

    graph, _ = build_graph(way, respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 in [edge[0] for edge in graph.get(2, [])]


def test_two_way_segment_is_traversable_in_both_directions_for_bike_mode():
    """Review Focus #5, bike-mode half: an untagged segment must stay
    bidirectional under respect_oneway=True too — only an explicit
    oneway=yes tag should restrict direction."""
    graph, _ = build_graph(_two_node_way(), respect_oneway=True)

    assert 2 in [edge[0] for edge in graph.get(1, [])]
    assert 1 in [edge[0] for edge in graph.get(2, [])]
