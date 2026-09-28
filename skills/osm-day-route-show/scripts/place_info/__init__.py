# skills/osm-day-route-show/scripts/place_info/__init__.py
"""Public entry point for point enrichment (spec §5) — queries every
configured plugin and returns EVERY non-empty result, not just the best
one. Used identically for interest points and access points."""
from dataclasses import asdict
from pathlib import Path

from .cache import cache_key, load_cache, save_entry
from .providers.base import PlaceInfoResult


class PlaceInfoService:
    def __init__(self, providers: list, cache_path: Path):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._cache = load_cache(self._cache_path)

    def fetch_all(self, names: dict[str, str], lat: float, lon: float,
                  wikidata_qid: str | None, identity: str) -> list[PlaceInfoResult]:
        results = []
        for provider in self._providers:
            key = cache_key(provider.provider_id, identity, lat, lon)
            if key in self._cache:
                cached = self._cache[key]
                if cached is not None:
                    results.append(PlaceInfoResult(**cached))
                continue
            try:
                result = provider.fetch(names, lat, lon, wikidata_qid)
            except Exception:
                # A single broken plugin must not take down the others or
                # the render — see spec §5 "each plugin works independently".
                result = None
            save_entry(self._cache_path, self._cache, key,
                       asdict(result) if result is not None else None)
            if result is not None:
                results.append(result)
        return results
