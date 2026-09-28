"""Public entry point for tile-provider coverage (design spec
2026-09-28-osm-day-route-show-tile-providers-design.md). Determines
which tile providers are usable for a given route's coverage points and
returns them, in the given plugin-list order, with per-plugin fault
isolation identical to place_info.PlaceInfoService.fetch_all."""
from pathlib import Path

from .cache import cache_key, load_cache, save_entry
from .providers.base import TileProviderPlugin


class TileProviderService:
    def __init__(self, providers: list[TileProviderPlugin], cache_path: Path):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._cache = load_cache(self._cache_path)

    def available_providers(self, points: list[tuple[float, float]],
                             timeout: float = 5.0) -> list[TileProviderPlugin]:
        available = []
        for provider in self._providers:
            if provider.always_available:
                available.append(provider)
                continue
            # Skip probing entirely if there are no points to check
            if not points:
                continue
            key = cache_key(provider.provider_id, points, provider.tile_url_template)
            if key in self._cache:
                if self._cache[key]:
                    available.append(provider)
                continue
            try:
                covers = provider.covers(points, timeout)
            except Exception:
                # A single broken plugin must not take down the others or
                # the render — same discipline as PlaceInfoService.fetch_all.
                # Treat an unexpected raise the same as an inconclusive
                # probe result: not offered THIS render, not cached.
                covers = None
            if covers is None:
                # Inconclusive (network/DNS/timeout/HTTP error, or an
                # unexpected raise) — not offered this render, and NOT
                # cached, so the next render retries instead of staying
                # stuck on a transient failure that got recorded as a
                # confirmed "no coverage".
                continue
            save_entry(self._cache_path, self._cache, key, covers)
            if covers:
                available.append(provider)
        return available
