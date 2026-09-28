"""Common interface every elevation plugin implements — one source, one
file, see spec §3.8. ElevationService (Task 13) only talks to this
interface, never to a provider's own HTTP details."""
from abc import ABC, abstractmethod


class ElevationProvider(ABC):
    provider_id: str
    max_batch: int
    rate_limit_per_sec: float

    @abstractmethod
    def fetch(self, locations: list[tuple[float, float]]) -> list[float | None]:
        """Returns one elevation (meters) per input (lat, lon), same order.
        A point this provider couldn't resolve is None, not a raised
        error — a raised error means the whole batch failed (see callers)."""
        raise NotImplementedError
