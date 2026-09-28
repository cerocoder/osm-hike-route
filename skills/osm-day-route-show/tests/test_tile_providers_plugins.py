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
    assert url == "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/10/503/383.png"
    assert provider.always_available is False


def test_ign_es_mtn_url_template_has_matrix_row_col_params():
    provider = IgnEsMtnProvider()
    url = provider.tile_url_template.format(z=10, x=503, y=383)
    assert "TileMatrix=10" in url
    assert "TileRow=383" in url
    assert "TileCol=503" in url
    assert provider.always_available is False


def test_ign_es_mtn_covers_returns_false_for_moscow_without_probing():
    """Critical 2 regression: IGN's MTN layer serves a blank placeholder
    tile (still HTTP 200, plausible image body) outside Spain. The wide
    Western-Europe bounding-box pre-check in IgnEsMtnProvider.covers()
    must reject a clearly-outside-the-region point BEFORE any network
    probe."""
    provider = IgnEsMtnProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([(55.0, 37.0)], timeout=5.0) is False
    mock_probe.assert_not_called()


def test_ign_es_mtn_covers_returns_false_for_paris_without_probing():
    """Paris (~48.86N) sits above the widened bbox's lat_max of 44.5, so
    it's still rejected pre-probe even though the bbox now deliberately
    includes Portugal and southern France."""
    provider = IgnEsMtnProvider()
    with patch("tile_providers.providers.base.probe_tile") as mock_probe:
        assert provider.covers([(48.8566, 2.3522)], timeout=5.0) is False
    mock_probe.assert_not_called()


def test_ign_es_mtn_covers_reaches_probe_for_madrid():
    """A point inside the Western-Europe bounding box passes the
    geography pre-check and falls through to the normal probe (defense
    in depth)."""
    provider = IgnEsMtnProvider()
    with patch("tile_providers.providers.base.probe_tile", return_value=True) as mock_probe:
        assert provider.covers([(40.4168, -3.7038)], timeout=5.0) is True
    mock_probe.assert_called_once()

    with patch("tile_providers.providers.base.probe_tile", return_value=False) as mock_probe:
        assert provider.covers([(40.4168, -3.7038)], timeout=5.0) is False
    mock_probe.assert_called_once()


def test_ign_es_mtn_min_body_bytes_is_5000():
    """Direct regression pin: this raised threshold (vs. the generic
    256B floor) is what actually distinguishes IGN's ~19KB real tiles
    from its up-to-~2KB "no data" placeholders for points inside the
    now-wider bbox (e.g. Lisbon, Toulouse). A future edit silently
    lowering this back down would reopen the false-positive bug."""
    assert IgnEsMtnProvider.min_body_bytes == 5000
    assert IgnEsMtnProvider().min_body_bytes == 5000


def test_ign_es_mtn_covers_reaches_probe_for_lisbon_and_rejects_placeholder():
    """Lisbon is inside the widened Western-Europe bbox (unlike the old
    Spain-only bbox), so it now reaches the live probe rather than being
    rejected pre-network. Simulates the real-world outcome: IGN's
    placeholder tile for Lisbon (observed 1920B) is below the 5000B
    threshold, so probe_tile itself returns False, and covers() must
    propagate that False rather than falsely reporting coverage."""
    provider = IgnEsMtnProvider()
    with patch("tile_providers.providers.base.probe_tile", return_value=False) as mock_probe:
        assert provider.covers([(38.72, -9.14)], timeout=5.0) is False
    mock_probe.assert_called_once()


def test_ign_es_mtn_covers_threads_min_body_bytes_into_probe_tile():
    """Confirms the raised threshold actually reaches probe_tile as a
    kwarg from covers() (via TileProviderPlugin.covers()), not just set
    on the class and silently ignored."""
    from tile_providers.probe import TILE_PROBE_ZOOM

    provider = IgnEsMtnProvider()
    with patch("tile_providers.providers.base.probe_tile", return_value=True) as mock_probe:
        provider.covers([(40.4168, -3.7038)], timeout=5.0)
    mock_probe.assert_called_once_with(
        provider.tile_url_template, 40.4168, -3.7038, TILE_PROBE_ZOOM, 5.0,
        min_body_bytes=5000,
    )


def test_all_four_providers_have_distinct_provider_ids():
    ids = {
        EsriStreetProvider().provider_id,
        EsriSatelliteProvider().provider_id,
        CyclOsmProvider().provider_id,
        IgnEsMtnProvider().provider_id,
    }
    assert ids == {"esri_street", "esri_satellite", "cyclosm", "ign_es_mtn"}
