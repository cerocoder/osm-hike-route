from unittest.mock import patch

from place_info.providers.wikimedia_commons import WikimediaCommonsProvider
from place_info.providers.opentripmap import OpenTripMapProvider


def test_commons_provider_id():
    assert WikimediaCommonsProvider().provider_id == "wikimedia_commons"


def test_commons_fetch_returns_image_url_for_nearest_file():
    payload = {"query": {"geosearch": [{"title": "File:Bazhukovo view.jpg"}]}}
    provider = WikimediaCommonsProvider()

    with patch("place_info.providers.wikimedia_commons._http_get_json", return_value=payload):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid=None)

    assert result.provider_id == "wikimedia_commons"
    assert result.image_url == "https://commons.wikimedia.org/wiki/File:Bazhukovo_view.jpg"


def test_commons_fetch_returns_none_when_nothing_nearby():
    provider = WikimediaCommonsProvider()

    with patch("place_info.providers.wikimedia_commons._http_get_json", return_value={"query": {"geosearch": []}}):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None


def test_opentripmap_provider_id():
    assert OpenTripMapProvider(api_key="fake-key").provider_id == "opentripmap"


def test_opentripmap_fetch_returns_none_without_configured_key():
    """Review Focus #3: no key configured -> silent skip, no network call."""
    provider = OpenTripMapProvider(api_key=None)

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
    mock_urlopen.assert_not_called()


def test_opentripmap_fetch_returns_summary_and_url_with_valid_key():
    radius_payload = {"features": [{"properties": {"xid": "N123"}}]}
    detail_payload = {
        "name": "Родник", "wikipedia_extracts": {"text": "Источник питьевой воды."},
        "url": "https://example.org/rodnik",
    }
    provider = OpenTripMapProvider(api_key="fake-key")

    with patch("place_info.providers.opentripmap._http_get_json", side_effect=[radius_payload, detail_payload]):
        result = provider.fetch({"ru": "Родник"}, 56.85, 59.5, wikidata_qid=None)

    assert result.summary == "Источник питьевой воды."
    assert result.url == "https://example.org/rodnik"


def test_opentripmap_fetch_returns_none_on_unauthorized_key():
    """Review Focus #3: a key that the API rejects must degrade quietly."""
    import urllib.error
    provider = OpenTripMapProvider(api_key="bad-key")

    with patch("place_info.providers.opentripmap._http_get_json",
               side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
