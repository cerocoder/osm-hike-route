import json
from unittest.mock import patch

from place_info.providers.wikidata import WikidataProvider


def test_provider_id_is_wikidata():
    assert WikidataProvider(user_lang="ru").provider_id == "wikidata"


def test_fetch_by_qid_returns_description_and_url():
    payload = {"entities": {"Q123": {
        "labels": {"ru": {"value": "Бажуково"}},
        "descriptions": {"ru": {"value": "деревня в Свердловской области"}},
        "sitelinks": {"ruwiki": {"title": "Бажуково"}},
    }}}
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value=payload):
        result = provider.fetch({"ru": "Бажуково"}, 56.85, 59.5, wikidata_qid="Q123")

    assert result.provider_id == "wikidata"
    assert result.summary == "деревня в Свердловской области"
    assert result.url == "https://www.wikidata.org/wiki/Q123"


def test_fetch_by_qid_returns_none_when_entity_missing_from_response():
    """Review Focus #4: a QID whose entity data doesn't come back at all."""
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value={"entities": {}}):
        result = provider.fetch({"ru": "Точка"}, 56.85, 59.5, wikidata_qid="Q999")

    assert result is None


def test_fetch_without_qid_uses_nearby_sparql_search():
    sparql_payload = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q456"},
         "itemLabel": {"value": "Родник"}},
    ]}}
    entity_payload = {"entities": {"Q456": {
        "labels": {"ru": {"value": "Родник"}},
        "descriptions": {"ru": {"value": "источник питьевой воды"}},
        "sitelinks": {},
    }}}
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", side_effect=[sparql_payload, entity_payload]):
        result = provider.fetch({"ru": "Родник"}, 56.85, 59.5, wikidata_qid=None)

    assert result.summary == "источник питьевой воды"
    assert result.url == "https://www.wikidata.org/wiki/Q456"


def test_fetch_without_qid_returns_none_when_nothing_nearby():
    provider = WikidataProvider(user_lang="ru")

    with patch("place_info.providers.wikidata._http_get_json", return_value={"results": {"bindings": []}}):
        result = provider.fetch({"ru": "Точка в поле"}, 56.85, 59.5, wikidata_qid=None)

    assert result is None
