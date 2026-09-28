"""OpenTripMap plugin (spec §5): the richest single-call payload of the
four (aggregates OSM+Wikidata+Wikipedia), but needs a free API key —
missing/rejected key degrades to no result, never an exception."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import PlaceInfoProvider, PlaceInfoResult

_USER_AGENT = "osm-day-route-show/1.0 (place_info opentripmap plugin)"


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OpenTripMapProvider(PlaceInfoProvider):
    provider_id = "opentripmap"

    def __init__(self, api_key: str | None, radius_m: int = 300, timeout: float = 5.0):
        self.api_key = api_key
        self.radius_m = radius_m
        self.timeout = timeout

    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        if not self.api_key:
            return None
        radius_params = {
            "radius": self.radius_m, "lon": lon, "lat": lat, "limit": 1, "apikey": self.api_key,
        }
        radius_url = "https://api.opentripmap.com/0.1/en/places/radius?" + urllib.parse.urlencode(radius_params)
        try:
            radius_data = _http_get_json(radius_url, self.timeout)
            features = radius_data.get("features", [])
            if not features:
                return None
            xid = features[0]["properties"]["xid"]
            detail_url = (
                f"https://api.opentripmap.com/0.1/en/places/xid/{xid}?"
                + urllib.parse.urlencode({"apikey": self.api_key})
            )
            detail = _http_get_json(detail_url, self.timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError, KeyError):
            return None
        summary = detail.get("wikipedia_extracts", {}).get("text")
        url = detail.get("url")
        if not summary and not url:
            return None
        return PlaceInfoResult(provider_id=self.provider_id, summary=summary, url=url)
