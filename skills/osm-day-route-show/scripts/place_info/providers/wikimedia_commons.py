"""Wikimedia Commons plugin (spec §5): nearby-file geosearch for a photo
of the point — no description, images only. No auth needed."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info commons plugin)"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WikimediaCommonsProvider(PlaceInfoProvider):
    provider_id = "wikimedia_commons"

    def __init__(self, radius_m: int = 500, timeout: float = 5.0):
        self.radius_m = radius_m
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        params = {
            "action": "query", "format": "json", "list": "geosearch",
            "gscoord": f"{lat}|{lon}", "gsradius": self.radius_m,
            "gsnamespace": 6, "gslimit": 1,
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            data = _http_get_json(url, self.timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None
        results = data.get("query", {}).get("geosearch", [])
        if not results:
            return None
        title = results[0]["title"]
        image_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe=":")
        return PlaceInfoResult(provider_id=self.provider_id, image_url=image_url)
