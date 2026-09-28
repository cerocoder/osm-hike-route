from unittest.mock import patch

from tile_providers.providers.esri_street import EsriStreetProvider
from tile_providers.providers.esri_satellite import EsriSatelliteProvider
from tile_providers.providers.cyclosm import CyclOsmProvider
from tile_providers.providers.ign_es_mtn import IgnEsMtnProvider


def test_esri_street_is_always_available_and_never_probes():
    provider = EsriStreetProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([(40.0, -3.0)], timeout=5.0) is True
    mock_probe.assert_not_called()


def test_esri_satellite_is_always_available_and_never_probes():
    provider = EsriSatelliteProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([], timeout=5.0) is True
    mock_probe.assert_not_called()


def test_esri_street_url_template_uses_z_y_x_order():
    provider = EsriStreetProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/10/383/503"


def test_esri_satellite_url_template_uses_z_y_x_order():
    provider = EsriSatelliteProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/10/383/503"


def test_cyclosm_url_template_uses_z_x_y_order():
    """Review Focus / Global Constraint: CyclOSM's template order is
    {z}/{x}/{y}, the opposite of the two Esri templates above — getting
    this backwards silently loads the wrong tiles."""
    provider = CyclOsmProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert url == "https://tile-cyclosm.openstreetmap.fr/cyclosm/10/503/383.png"
    assert provider.always_available is False


def test_ign_es_mtn_url_template_has_matrix_row_col_params():
    provider = IgnEsMtnProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert "TileMatrix=10" in url
    assert "TileRow=383" in url
    assert "TileCol=503" in url
    assert provider.always_available is False


def test_all_four_providers_have_distinct_provider_ids():
    ids = {
        EsriStreetProvider().provider_id,
        EsriSatelliteProvider().provider_id,
        CyclOsmProvider().provider_id,
        IgnEsMtnProvider().provider_id,
    }
    assert ids == {"esri_street", "esri_satellite", "cyclosm", "ign_es_mtn"}
