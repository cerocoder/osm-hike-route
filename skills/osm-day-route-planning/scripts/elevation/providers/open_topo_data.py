import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenTopoDataProvider(ElevationProvider):
    provider_id = "open_topo_data"
    max_batch = 100
    rate_limit_per_sec = 1.0
    dataset = "srtm90m"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        locations_param = "|".join(f"{lat},{lon}" for lat, lon in locations)
        url = f"https://api.opentopodata.org/v1/{self.dataset}?locations={locations_param}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if len(results) != len(locations):
                return [None] * len(locations)
            return [r.get("elevation") for r in results]
        except (urllib.error.URLError, OSError, ValueError, AttributeError, TypeError, KeyError, IndexError):
            return [None] * len(locations)
