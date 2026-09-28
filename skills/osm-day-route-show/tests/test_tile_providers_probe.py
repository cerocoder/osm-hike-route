from unittest.mock import patch

from tile_providers.probe import latlon_to_tile, probe_tile


def test_latlon_to_tile_zoom_zero_is_always_the_single_tile():
    assert latlon_to_tile(0.0, 0.0, 0) == (0, 0)


def test_latlon_to_tile_known_reference_point():
    # Madrid, ~40.4168 N, -3.7038 E at zoom 10 — standard slippy-map formula.
    x, y = latlon_to_tile(40.4168, -3.7038, 10)
    assert (x, y) == (501, 386)


def test_probe_tile_true_on_200_image_response():
    with patch("tile_providers.probe._fetch", return_value=(200, "image/png", b"x" * 1000)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is True


def test_probe_tile_false_on_tiny_body():
    """A 200 response with a placeholder-sized body must not count as coverage —
    Review Focus: a provider with no real data for a point (e.g. IGN outside Spain)
    must resolve to False, not a false positive."""
    with patch("tile_providers.probe._fetch", return_value=(200, "image/png", b"x" * 10)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is False


def test_probe_tile_false_on_non_image_content_type():
    with patch("tile_providers.probe._fetch", return_value=(200, "text/html", b"x" * 1000)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is False


def test_probe_tile_none_on_network_error_never_raises():
    """Review Focus: a timeout/DNS/HTTP error must degrade to None
    (inconclusive — never cached as confirmed 'no coverage'), never
    propagate as an exception."""
    import urllib.error

    with patch("tile_providers.probe._fetch", side_effect=urllib.error.URLError("boom")):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is None


def test_probe_tile_none_on_incomplete_read_never_raises():
    """Review Focus: truncated tile downloads (http.client.IncompleteRead from flaky
    connections) must degrade to None (inconclusive), never propagate."""
    import http.client

    with patch("tile_providers.probe._fetch", side_effect=http.client.IncompleteRead(b"x" * 100, 1000)):
        assert probe_tile("https://example.org/{z}/{x}/{y}.png", 40.0, -3.0, 15, 5.0) is None


def test_probe_tile_formats_url_with_z_x_y():
    captured = {}

    def fake_fetch(url, timeout):
        captured["url"] = url
        return 200, "image/png", b"x" * 1000

    with patch("tile_providers.probe._fetch", side_effect=fake_fetch):
        probe_tile("https://example.org/{z}/{x}/{y}.png", 40.4168, -3.7038, 10, 5.0)

    assert captured["url"] == "https://example.org/10/501/386.png"
