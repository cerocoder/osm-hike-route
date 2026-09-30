"""Public entry point for elevation lookups — the only thing the rest of
the skill imports from this package (spec §3.8). Orchestrates cache,
batching, per-provider rate limiting, and failover across providers."""
import time
from pathlib import Path

from .cache import cache_key, load_cache, update_entry, write_cache

DEFAULT_DATASET = "srtm90m"


class ElevationService:
    def __init__(self, providers: list, cache_path: Path, dataset: str = DEFAULT_DATASET):
        self._providers = providers
        self._cache_path = Path(cache_path)
        self._dataset = dataset
        self._cache = load_cache(self._cache_path)
        self._last_call_time: dict[str, float] = {}
        self.last_request = {"points": 0, "cached": 0}       # of the latest get_elevations call, for a summary line

    def get_elevations(self, locations: list[tuple[float, float]], progress=None) -> list[float | None]:
        """Elevation per location (None where no provider knew it). `progress` (optional, see progress.py) gets a
        tick per provider request: elevation_batch done/total (total counts the first provider's batches and grows
        if a failover needs more)."""
        results: list[float | None] = [None] * len(locations)
        pending_indices = []
        for i, (lat, lon) in enumerate(locations):
            key = cache_key(lat, lon, self._dataset)
            if key in self._cache:
                results[i] = self._cache[key]["elevation"]
            else:
                pending_indices.append(i)
        self.last_request = {"points": len(locations), "cached": len(locations) - len(pending_indices)}
        batches_done = 0
        batches_total = -(-len(pending_indices) // self._providers[0].max_batch) if self._providers else 0

        for provider in self._providers:
            if not pending_indices:
                break
            still_pending = []
            for batch_indices in self._chunk(pending_indices, provider.max_batch):
                batch_locations = [locations[i] for i in batch_indices]
                self._respect_rate_limit(provider)
                batches_done += 1
                batches_total = max(batches_total, batches_done)
                if progress is not None:
                    progress.tick(batches_done, batches_total, "elevation_batch")
                try:
                    batch_results = provider.fetch(batch_locations)
                except Exception:
                    # Provider failed for whole batch — treat as all None
                    still_pending.extend(batch_indices)
                    continue
                resolved_any = False
                for idx, elevation in zip(batch_indices, batch_results):
                    if elevation is None:
                        still_pending.append(idx)
                        continue
                    results[idx] = elevation
                    lat, lon = locations[idx]
                    key = cache_key(lat, lon, self._dataset)
                    update_entry(self._cache, key, lat, lon, elevation,
                                 provider.provider_id, self._dataset)
                    resolved_any = True
                # One whole-file write per successful batch (not per point —
                # that was O(n) rewrites of an ever-growing file), still
                # frequent enough that a killed run keeps finished batches.
                if resolved_any:
                    write_cache(self._cache_path, self._cache)
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
