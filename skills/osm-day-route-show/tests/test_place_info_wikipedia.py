# skills/osm-day-route-show/tests/test_place_info_wikipedia.py
import json
from unittest.mock import patch, MagicMock

from place_info.providers.wikipedia import WikipediaProvider
from place_info.providers.base import PlaceInfoResult


def _mock_response(payload):
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode("utf-8")
    return mock


def test_provider_id_is_wikipedia():
    assert WikipediaProvider(user_lang="ru").provider_id == "wikipedia"


def test_fetch_returns_result_with_url_when_qid_resolves():
    sitelinks_payload = {
        "entities": {"Q123": {"sitelinks": {"ruwiki": {"title": "Бажуково"}}}}
    }
    provider = WikipediaProvider(user_lang="ru")

    with patch("place_info.providers.wikipedia._http_get_with_retry",
               return_value=json.dumps(sitelinks_payload).encode("utf-8")):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid="Q123")

    assert isinstance(result, PlaceInfoResult)
    assert result.provider_id == "wikipedia"
    assert result.url == "https://ru.wikipedia.org/wiki/%D0%91%D0%B0%D0%B6%D1%83%D0%BA%D0%BE%D0%B2%D0%BE"


def test_fetch_returns_none_when_qid_has_no_matching_sitelink():
    """Review Focus #4: a QID that resolves to something, but not to any
    usable sitelink, must degrade to None, not raise."""
    sitelinks_payload = {"entities": {"Q999": {"sitelinks": {}}}}
    provider = WikipediaProvider(user_lang="ru")

    with patch("place_info.providers.wikipedia._http_get_with_retry",
               return_value=json.dumps(sitelinks_payload).encode("utf-8")):
        result = provider.fetch({"ru": "Пустая точка"}, 56.85, 59.5, wikidata_qid="Q999")

    assert result is None


def test_fetch_returns_none_without_qid_and_without_verified_search_match():
    search_payload = {"query": {"search": []}}
    geosearch_payload = {"query": {"geosearch": []}}
    provider = WikipediaProvider(user_lang="ru")

    def fake_get(url, timeout):
        payload = search_payload if "list=search" in url else geosearch_payload
        return json.dumps(payload).encode("utf-8")

    with patch("place_info.providers.wikipedia._http_get_with_retry", side_effect=fake_get):
        result = provider.fetch({"ru": "Неизвестное место"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
