"""The start of the trip: the one the person gave, or the one the plan recommends.

The recommendation is the earliest feasible start, but not earlier than 07:00 (a start before sunrise in summer is
not a sensible advice); when the route would not fit otherwise, the earliest feasible one. The window of a feasible
start is bounded below by sunrise, the opening of the start point and the first public transport that reaches it, and
above by sunset (minus a safety buffer), the last public transport back and the closing of the end point, each minus
the duration of the route. An empty window is reported, never hidden. All times are minutes after local midnight."""
from dataclasses import dataclass, field

PREFERRED_FROM_MIN = 7 * 60
SUNSET_BUFFER_MIN = 60
LAST_DEPARTURE_BUFFER_MIN = 30


@dataclass
class StartRecommendation:
    status: str                        # "ok" | "empty_window" | "no_duration"
    start_min: int | None = None
    earliest: int | None = None
    earliest_limit: str | None = None  # sunrise | start_open | first_arrival
    latest: int | None = None
    latest_limit: str | None = None    # sunset | last_departure | end_close
    missing: list = field(default_factory=list)   # transport facts that were not recorded


def recommend_start(duration_min, sunrise=None, sunset=None, start_open=None, first_arrival=None,
                    last_departure=None, end_close=None, preferred_from=PREFERRED_FROM_MIN) -> StartRecommendation:
    if not duration_min:
        return StartRecommendation("no_duration")
    lows = {name: value for name, value in (("sunrise", sunrise), ("start_open", start_open),
                                            ("first_arrival", first_arrival)) if value is not None}
    highs = {}
    if sunset is not None:
        highs["sunset"] = sunset - SUNSET_BUFFER_MIN - duration_min
    if last_departure is not None:
        highs["last_departure"] = last_departure - LAST_DEPARTURE_BUFFER_MIN - duration_min
    if end_close is not None:
        highs["end_close"] = end_close - duration_min
    earliest_limit = max(lows, key=lows.get) if lows else None
    earliest = lows[earliest_limit] if lows else 0
    latest_limit = min(highs, key=highs.get) if highs else None
    latest = highs[latest_limit] if highs else None
    rec = StartRecommendation("ok", None, earliest, earliest_limit, latest, latest_limit)
    wanted = max(earliest, preferred_from)
    if latest is None or earliest <= latest:
        start = wanted if latest is None or wanted <= latest else earliest
    else:
        rec.status = "empty_window"
        start = highs.get("sunset", latest)
    rec.start_min = min(1439, max(0, int(start)))
    return rec
