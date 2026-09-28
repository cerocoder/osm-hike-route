import json
import urllib.error
import urllib.parse
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class ElevationApiEuProvider(ElevationProvider):
    provider_id = "elevation_api_eu"
    max_batch = 100  # not documented by the provider — treated conservatively, see spec §3.8
    rate_limit_per_sec = 10.0
    dataset = "copernicus"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        pts = json.dumps([[lat, lon] for lat, lon in locations])
        url = "https://www.elevation-api.eu/v1/elevation?" + urllib.parse.urlencode({"pts": pts})
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return [None] * len(locations)
        result = list(data)
        if len(result) != len(locations):
            return [None] * len(locations)
        return result
