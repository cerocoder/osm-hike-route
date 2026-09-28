"""Common interface every tile-provider plugin implements — mirrors
place_info/providers/base.py. TileProviderService only talks to this
interface."""
from ..probe import TILE_PROBE_ZOOM, probe_tile


class TileProviderPlugin:
    provider_id: str
    display_name: str
    tile_url_template: str
    attribution: str
    max_zoom: int
    max_native_zoom: int | None
    always_available: bool = False

    def covers(self, points: list[tuple[float, float]], timeout: float = 5.0) -> bool | None:
        """`points` is a list of (lat, lon). True immediately, with no
        network call, when always_available. Otherwise requires every
        point to succeed a live tile probe at TILE_PROBE_ZOOM, and
        returns None (inconclusive) if any point's probe itself failed
        (network/DNS/timeout/HTTP error) rather than confirming True or
        False — callers (TileProviderService) must not cache a None
        result as "no coverage": the next render should retry. An empty
        `points` list means "nothing to probe" and resolves to False —
        callers (TileProviderService) are the ones that decide an empty
        list means "skip this provider, offer only always_available
        ones", not this method."""
        if self.always_available:
            return True
        if not points:
            return False
        results = [
            probe_tile(self.tile_url_template, lat, lon, TILE_PROBE_ZOOM, timeout)
            for lat, lon in points
        ]
        if any(r is None for r in results):
            return None
        return all(results)
