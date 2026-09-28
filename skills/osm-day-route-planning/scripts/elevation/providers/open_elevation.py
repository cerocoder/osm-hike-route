import json
import urllib.error
import urllib.request

from .base import ElevationProvider

_USER_AGENT = "osm-day-route-planning/1.0 (elevation lookup)"


class OpenElevationProvider(ElevationProvider):
    """Least reliable of the four (known public-instance outages) — kept
    last in ElevationService's failover order, see spec §3.8."""
    provider_id = "open_elevation"
    max_batch = 100
    rate_limit_per_sec = 1.0
    dataset = "srtm"

    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        body = json.dumps({
            "locations": [{"latitude": lat, "longitude": lon} for lat, lon in locations]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.open-elevation.com/api/v1/lookup",
            data=body,
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if len(results) != len(locations):
                return [None] * len(locations)
            return [r.get("elevation") for r in results]
        except (urllib.error.URLError, OSError, ValueError, AttributeError, TypeError, KeyError, IndexError):
            return [None] * len(locations)
