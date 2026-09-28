# skills/osm-day-route-show/scripts/place_info/providers/base.py
"""Common interface every place-info plugin implements — one source, one
file, see spec §5. PlaceInfoService only talks to this interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PlaceInfoResult:
    provider_id: str
    summary: str | None = None
    url: str | None = None
    image_url: str | None = None


class PlaceInfoProvider(ABC):
    provider_id: str

    @abstractmethod
    def fetch(self, names: dict[str, str], lat: float, lon: float,
              wikidata_qid: str | None) -> PlaceInfoResult | None:
        """`names` is {lang: name} — local language, user language, English
        (spec §5, reuses the point's own `search_names`/`name`). Returns
        None when this provider found nothing usable — never raises for an
        ordinary 'no data' outcome; only a genuine transport/programming
        error should propagate."""
        raise NotImplementedError
