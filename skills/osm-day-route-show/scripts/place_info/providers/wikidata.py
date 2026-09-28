"""Wikidata plugin (spec §5): a known QID (copied from the OSM `wikidata`
tag) is a fast, curated lookup; without one, a SPARQL 'nearby' search
finds a candidate entity by coordinates. Either way, only a description
in a language this run cares about is returned — never a raw fallback
in an unrelated language."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info wikidata plugin)"
_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
_SPARQL_URL = "https://query.wikidata.org/sparql"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _describe_entity(qid: str, user_lang: str, timeout: float) -> PlaceInfoResult | None:
    try:
        data = _http_get_json(_ENTITY_URL.format(qid=qid), timeout)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    entity = data.get("entities", {}).get(qid)
    if not entity:
        return None
    description = entity.get("descriptions", {}).get(user_lang, {}).get("value") \
        or entity.get("descriptions", {}).get("en", {}).get("value")
    if not description:
        return None
    return PlaceInfoResult(
        provider_id="wikidata", summary=description,
        url=f"https://www.wikidata.org/wiki/{qid}",
    )


class WikidataProvider(PlaceInfoProvider):
    provider_id = "wikidata"

    def __init__(self, user_lang: str, timeout: float = 5.0):
        self.user_lang = user_lang
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        if wikidata_qid:
            return _describe_entity(wikidata_qid, self.user_lang, self.timeout)

        query = (
            "SELECT ?item ?itemLabel WHERE { "
            f"SERVICE wikibase:around {{ ?item wdt:P625 ?location . "
            f'bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral . '
            'bd:serviceParam wikibase:radius "0.3" . '
            'bd:serviceParam wikibase:distance ?dist . } '
            f'SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{self.user_lang},en" . }} '
            "} ORDER BY ?dist LIMIT 1"
        )
        url = _SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
        try:
            data = _http_get_json(url, self.timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None
        item_uri = bindings[0]["item"]["value"]
        qid = item_uri.rsplit("/", 1)[-1]
        return _describe_entity(qid, self.user_lang, self.timeout)
