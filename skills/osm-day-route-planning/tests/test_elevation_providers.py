import json
from unittest.mock import patch, MagicMock

from elevation.providers.open_topo_data import OpenTopoDataProvider


def _mock_response(payload: dict):
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_provider_id_and_batch_size():
    provider = OpenTopoDataProvider()
    assert provider.provider_id == "open_topo_data"
    assert provider.max_batch == 100


def test_fetch_returns_elevations_in_request_order():
    payload = {
        "status": "OK",
        "results": [
            {"elevation": 100.0, "location": {"lat": 55.0, "lng": 37.0}},
            {"elevation": 120.5, "location": {"lat": 55.1, "lng": 37.1}},
        ],
    }
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [100.0, 120.5]


def test_fetch_returns_none_per_point_on_http_error():
    import urllib.error
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [None, None]


def test_fetch_returns_none_per_point_on_missing_results():
    """Valid JSON response but no/incomplete results list should return [None] * len(locations)."""
    # Test with missing "results" key
    payload = {"status": "OK"}
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [None, None]


def test_fetch_returns_none_per_point_on_incomplete_results():
    """Valid JSON response with fewer results than locations should return [None] * len(locations)."""
    # Test with "results" shorter than input
    payload = {
        "status": "OK",
        "results": [
            {"elevation": 100.0, "location": {"lat": 55.0, "lng": 37.0}},
        ],
    }
    provider = OpenTopoDataProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [None, None]
