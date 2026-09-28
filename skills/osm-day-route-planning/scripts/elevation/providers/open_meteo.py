import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenMeteoProvider(ElevationProvider):
    provider_id = "open_meteo"
    max_batch = 100
    rate_limit_per_sec = 5.0
    dataset = "copernicus_glo90"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        lats = ",".join(str(lat) for lat, _ in locations)
        lons = ",".join(str(lon) for _, lon in locations)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            result = list(data.get("elevation", [None] * len(locations)))
            if len(result) != len(locations):
                return [None] * len(locations)
            return result
        except (urllib.error.URLError, OSError, ValueError, AttributeError, TypeError, KeyError, IndexError):
            return [None] * len(locations)
