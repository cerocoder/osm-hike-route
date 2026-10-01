"""The start of the trip: the one the person gave, or the one the plan recommends.

The recommendation is the earliest feasible start, but not earlier than 07:00 (a start before sunrise in summer is
not a sensible advice); when the route would not fit otherwise, the earliest feasible one. The window of a feasible
start is bounded below by sunrise, the opening of the start point and the first public transport that reaches it, and
above by sunset (minus a safety buffer), the last public transport back and the closing of the end point, each minus
the duration of the route. An empty window is reported, never hidden. All times are minutes after local midnight."""
import datetime
from dataclasses import dataclass, field

from .base import PlanWarning
from .calendar_info import resolve_day_type
from .facts import lookup
from .http import HttpError
from .i18n import tr
from .opening_hours import evaluate, latest_close
from .plugins import weather
from .plugins.transit import _return_point
from .sun import sun_times

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


def _clock(minute) -> str:
    return f"{(int(minute) // 60) % 24:02d}:{int(minute) % 60:02d}"


def _fact_minutes(text) -> int | None:
    if not isinstance(text, str) or ":" not in text:
        return None
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _start_point(points: list):
    for point in points:
        if point.role == "start":
            return point
    return points[0] if len(points) == 1 else None


def _utc_offset_seconds(ctx) -> float:
    lat, lon = ctx.centroid
    try:
        _, offset, _, _ = weather._fetch(ctx, weather.choose_source(ctx.date, ctx.today), lat, lon)
    except (HttpError, KeyError, IndexError, ValueError, TypeError):
        offset = None
    return offset if offset is not None else round(lon / 15.0 * 2) / 2 * 3600


def resolve_start(ctx) -> None:
    """Sets ctx.start_time (and start_source, start_info) to the recommended start when the person gave none.
    Nothing is done when --start was given, when the route has no duration, or on a polar night."""
    if ctx.start_source != "none" or not ctx.duration_hours:
        return
    lat, lon = ctx.centroid
    sun = sun_times(ctx.date, lat, lon)
    if sun.kind == "polar_night":
        return
    sunrise = sunset = None
    if sun.kind == "normal":
        offset_min = _utc_offset_seconds(ctx) / 60.0
        sunrise, sunset = sun.sunrise_utc_min + offset_min, sun.sunset_utc_min + offset_min
    sun_map = {"sunrise": int(sunrise), "sunset": int(sunset)} if sunrise is not None else None
    day = resolve_day_type(ctx)
    start_open = end_close = None
    start_point, end_point = _start_point(ctx.access_points), _return_point(ctx.access_points)
    if start_point is not None and start_point.opening_hours:
        result = evaluate(start_point.opening_hours, ctx.date, day.holiday, sun_map)
        if result.status == "open_hours" and result.intervals:
            start_open = min(begin for begin, _ in result.intervals)
    if end_point is not None and end_point.opening_hours:
        result = evaluate(end_point.opening_hours, ctx.date, day.holiday, sun_map)
        if result.status == "open_hours":
            end_close = latest_close(result)
    fact = lookup(ctx.facts, ctx.date_iso, "transit") or {}
    first_arrival = _fact_minutes(fact.get("first_arrival_local"))
    last_departure = _fact_minutes(fact.get("last_departure_local"))
    if last_departure is not None and last_departure < 240:      # a departure at 00:30 belongs to the night after this date
        last_departure += 1440
    rec = recommend_start(round(ctx.duration_hours * 60), sunrise, sunset, start_open, first_arrival,
                          last_departure, end_close)
    rec.missing = [name for name, value in (("first_arrival", first_arrival), ("last_departure", last_departure))
                   if value is None]
    ctx.start_time = datetime.time(rec.start_min // 60, rec.start_min % 60)
    ctx.start_source = "recommended"
    ctx.start_info = rec


def _limit(minute, key, lang) -> str:
    return f"{_clock(minute)} ({tr('st_limits', lang)[key]})" if minute is not None and key else tr("st_no_limit", lang)


def _limit_name(key, lang) -> str:
    return tr("st_limits", lang)[key] if key else tr("st_no_limit", lang)


def start_lines(ctx) -> tuple[list, list]:
    """Plan lines and warnings that explain a recommended start; nothing for a start the person gave."""
    info = getattr(ctx, "start_info", None)
    if getattr(ctx, "start_source", "none") != "recommended" or info is None:
        return [], []
    lang = ctx.lang
    lines, warnings = [], []
    if info.status == "empty_window":
        warnings.append(PlanWarning("danger", tr(
            "st_warn_empty", lang, earliest=_clock(info.earliest), early=_limit_name(info.earliest_limit, lang),
            latest=_clock(info.latest), late=_limit_name(info.latest_limit, lang), start=_clock(info.start_min))))
    else:
        pref = tr("st_pref", lang) if info.start_min == PREFERRED_FROM_MIN and info.earliest < PREFERRED_FROM_MIN else ""
        lines.append("- " + tr("st_recommended", lang, start=_clock(info.start_min),
                               early=_limit(info.earliest, info.earliest_limit, lang),
                               late=_limit(info.latest, info.latest_limit, lang), pref=pref))
    if info.missing and ctx.access_points:
        what = ", ".join(tr("st_missing", lang)[name] for name in info.missing)
        lines.append("- " + tr("st_transport_missing", lang, what=what))
    return lines, warnings
