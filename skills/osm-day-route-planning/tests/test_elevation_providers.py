import json
from unittest.mock import patch, MagicMock

from elevation.providers.open_topo_data import OpenTopoDataProvider
from elevation.providers.open_meteo import OpenMeteoProvider
from elevation.providers.elevation_api_eu import ElevationApiEuProvider
from elevation.providers.open_elevation import OpenElevationProvider


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


def test_open_meteo_fetch_returns_elevations_in_order():
    payload = {"elevation": [38.0, 41.5]}
    provider = OpenMeteoProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(52.5, 13.4), (48.85, 2.35)])

    assert result == [38.0, 41.5]
    assert provider.provider_id == "open_meteo"
    assert provider.max_batch == 100


def test_open_meteo_fetch_returns_none_per_point_on_wrong_length():
    """Valid JSON response but wrong-length elevation list should return [None] * len(locations)."""
    payload = {"elevation": [38.0]}  # Only 1 elevation, but 2 locations requested
    provider = OpenMeteoProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(52.5, 13.4), (48.85, 2.35)])

    assert result == [None, None]


def test_elevation_api_eu_fetch_returns_elevations_in_order():
    payload = [120.3, None, 88.0]
    provider = ElevationApiEuProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (0.0, 0.0), (46.5, 6.6)])

    assert result == [120.3, None, 88.0]
    assert provider.provider_id == "elevation_api_eu"
    assert provider.rate_limit_per_sec == 10.0


def test_elevation_api_eu_fetch_returns_none_per_point_on_wrong_length():
    """Valid JSON response but wrong-length array should return [None] * len(locations)."""
    payload = [120.3, None]  # Only 2 elevations, but 3 locations requested
    provider = ElevationApiEuProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (0.0, 0.0), (46.5, 6.6)])

    assert result == [None, None, None]


def test_open_elevation_fetch_returns_elevations_in_order():
    payload = {"results": [{"elevation": 300.0}, {"elevation": 305.5}]}
    provider = OpenElevationProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [300.0, 305.5]
    assert provider.provider_id == "open_elevation"


def test_open_elevation_fetch_returns_none_per_point_on_incomplete_results():
    """Valid JSON response with fewer results than locations should return [None] * len(locations)."""
    payload = {"results": [{"elevation": 300.0}]}  # Only 1 result, but 2 locations requested
    provider = OpenElevationProvider()

    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = provider.fetch([(55.0, 37.0), (55.1, 37.1)])

    assert result == [None, None]
