"""Open-Meteo Marine API: sea surface temperature and sea level (tides included) — free, no key, a grid of about
28 km, a forecast horizon of about 9 days (later dates answer HTTP 400 or null). Beyond the horizon the temperature is
the mean of the same date over previous years, and the tides are not available. Lakes return null here."""
import datetime

from .http import HttpError
from .plugins.weather import _same_day_in_year

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
MARINE_TTL_S = 3 * 3600
MARINE_CLIMATE_YEARS = 3
GRID_STEP_DEG = 0.15
_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))     # the point itself, then its neighbours (a coastal cell can be land)


def _url(lat: float, lon: float, date: datetime.date) -> str:
    d = date.isoformat()
    return (f"{MARINE_URL}?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&hourly=sea_surface_temperature,sea_level_height_msl&start_date={d}&end_date={d}&timezone=auto")


def fetch_marine_day(ctx, lat: float, lon: float, date: datetime.date) -> dict:
    """{"sst": [24 values], "level": [24 values]}; HttpError / KeyError propagate."""
    key = f"marine|{lat:.2f}|{lon:.2f}|{date.isoformat()}"
    cached = ctx.cache.get_entry(key, MARINE_TTL_S)
    if cached is not None:
        return cached[0]
    hourly = ctx.http(_url(lat, lon, date))["hourly"]
    value = {"sst": list(hourly.get("sea_surface_temperature") or []), "level": list(hourly.get("sea_level_height_msl") or [])}
    ctx.cache.put(key, value)
    return value


def mean_sst(day: dict):
    values = [v for v in day.get("sst", []) if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def find_sea_day(ctx, lat: float, lon: float, date: datetime.date):
    """(day, lat, lon) of the first grid point that has a sea temperature; None when none has, or on a service error
    (which is not retried on the neighbours)."""
    for dy, dx in _OFFSETS:
        la, lo = lat + dy * GRID_STEP_DEG, lon + dx * GRID_STEP_DEG
        try:
            day = fetch_marine_day(ctx, la, lo, date)
        except (HttpError, KeyError, TypeError, ValueError):
            return None
        if mean_sst(day) is not None:
            return day, la, lo
    return None


def sea_temperature(ctx, lat: float, lon: float):
    """{"temp", "kind": "model" | "climatology", "point": (lat, lon) | None, "day": marine day | None}, or None."""
    found = find_sea_day(ctx, lat, lon, ctx.date)
    if found:
        return {"temp": mean_sst(found[0]), "kind": "model", "point": (found[1], found[2]), "day": found[0]}
    temps = []
    for back in range(1, MARINE_CLIMATE_YEARS + 1):
        past = find_sea_day(ctx, lat, lon, _same_day_in_year(ctx.date, ctx.today.year - back))
        if past:
            temps.append(mean_sst(past[0]))
    if temps:
        return {"temp": sum(temps) / len(temps), "kind": "climatology", "point": None, "day": None}
    return None


def tide_extrema(levels: list) -> list:
    """[(kind "high" | "low", hours since the midnight of the first day (float), level)] of an hourly series, the time
    refined by a parabola through the three hours around the extreme."""
    out = []
    for i in range(1, len(levels) - 1):
        a, b, c = levels[i - 1], levels[i], levels[i + 1]
        if None in (a, b, c):
            continue
        if b > a and b >= c:
            kind = "high"
        elif b < a and b <= c:
            kind = "low"
        else:
            continue
        denominator = a - 2 * b + c
        shift = 0.5 * (a - c) / denominator if denominator else 0.0
        out.append((kind, i + max(-0.5, min(0.5, shift)), b))
    return out
