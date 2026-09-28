"""Public entry point for elevation lookups — the only thing the rest of
the skill imports from this package (spec §3.8). Orchestrates cache,
batching, per-provider rate limiting, and failover across providers."""
import time
from pathlib import Path

from .cache import cache_key, load_cache, save_entry

DEFAULT_DATASET = "srtm90m"


class ElevationService:
    def __init__(self, providers: list, cache_path: Path, dataset: str = DEFAULT_DATASET):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._dataset = dataset
        self._cache = load_cache(self._cache_path)
        self._last_call_time: dict[str, float] = {}

    def get_elevations(self, locations: list[tuple[float, float]]) -> list[float | None]:
        results: list[float | None] = [None] * len(locations)
        pending_indices = []
        for i, (lat, lon) in enumerate(locations):
            key = cache_key(lat, lon, self._dataset)
            if key in self._cache:
                results[i] = self._cache[key]["elevation"]
            else:
                pending_indices.append(i)

        for provider in self._providers:
            if not pending_indices:
                break
            still_pending = []
            for batch_indices in self._chunk(pending_indices, provider.max_batch):
                batch_locations = [locations[i] for i in batch_indices]
                self._respect_rate_limit(provider)
                batch_results = provider.fetch(batch_locations)
                for idx, elevation in zip(batch_indices, batch_results):
                    if elevation is None:
                        still_pending.append(idx)
                        continue
                    results[idx] = elevation
                    lat, lon = locations[idx]
                    key = cache_key(lat, lon, self._dataset)
                    save_entry(self._cache_path, self._cache, key, lat, lon, elevation,
                               provider.provider_id, self._dataset)
            pending_indices = still_pending

        return results

    def _respect_rate_limit(self, provider) -> None:
        min_interval = 1.0 / provider.rate_limit_per_sec
        last = self._last_call_time.get(provider.provider_id, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time[provider.provider_id] = time.monotonic()

    @staticmethod
    def _chunk(indices: list[int], size: int):
        for i in range(0, len(indices), size):
            yield indices[i:i + size]
