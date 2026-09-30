"""Data only: the hourly weather of the 14 days before the plan date and the
date itself, with the variables the snow and ice estimate needs (snowfall,
rain, snow depth, dew point, cloud cover, weather code). Shares the parsed rows
(`shared["snow_history"]`) and adds nothing to the plan (`omit=True`).

It asks Open-Meteo only when snow or ice is plausible at all: in the cold
season, or when the weather of the date itself shows snow or frost. Beyond the
forecast horizon there is nothing to fetch (the consumer decides what to say)."""
import datetime

from ..base import Section, SectionPlugin
from ..http import HttpError
from ..snowmodel import in_cold_season
from .weather import ARCHIVE_URL, FORECAST_TTL_S, FORECAST_URL, choose_source

HISTORY_DAYS = 14
VARIABLES = ("temperature_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "snow_depth", "cloud_cover",
             "weather_code")
_ROW_KEYS = {"temperature_2m": "temp", "dew_point_2m": "dew", "precipitation": "precip", "rain": "rain",
             "snowfall": "snowfall", "snow_depth": "snow_cm", "cloud_cover": "cloud", "weather_code": "code"}
FROST_WATCH_C = 3.0            # the date's own weather shows frost if its minimum is at or below this


def history_url(base: str, lat: float, lon: float, date: datetime.date) -> str:
    start = date - datetime.timedelta(days=HISTORY_DAYS)
    return (f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&hourly={','.join(VARIABLES)}&timezone=auto"
            f"&start_date={start.isoformat()}&end_date={date.isoformat()}")


def parse_history(response: dict) -> list:
    """Open-Meteo hourly answer -> rows with hour (0-23), date (ISO), temp, dew, precip, rain, snowfall (cm), snow_cm
    (Open-Meteo gives `snow_depth` in metres; converted here once) , cloud, code. A missing variable is None."""
    hourly = response["hourly"]
    rows = []
    for i, stamp in enumerate(hourly["time"]):
        row = {"date": stamp[:10], "hour": int(stamp[11:13])}
        for api_key, key in _ROW_KEYS.items():
            series = hourly.get(api_key)
            value = series[i] if series is not None and i < len(series) else None
            row[key] = value * 100.0 if key == "snow_cm" and value is not None else value
        rows.append(row)
    return rows


def day_range(rows: list, date: datetime.date):
    """(first, last) row indices of the plan date, or None when the rows do not contain it."""
    indices = [i for i, r in enumerate(rows) if r["date"] == date.isoformat()]
    return (indices[0], indices[-1]) if indices else None


class SnowHistoryPlugin(SectionPlugin):
    plugin_id = "snow_history"
    section_id = "hazards"
    depends_on = ("weather",)

    def run(self, ctx, shared: dict) -> Section:
        weather = shared.get("weather") or {}
        source = weather.get("source") or choose_source(ctx.date, ctx.today)
        data = {"rows": [], "source": source, "elevation_m": None, "error": None, "skipped": False,
                "day_start": None, "day_end": None}
        lat, lon = ctx.centroid
        if source == "climate":
            return self._section(data)
        top = max((c[2] for c in ctx.coords if c[2] is not None), default=None)
        day_rows = weather.get("rows") or []
        watching = (in_cold_season(ctx.date.month, lat, top)
                    or any((r.get("snow_m") or 0.0) > 0.0 for r in day_rows)
                    or any(r.get("temp") is not None and r["temp"] <= FROST_WATCH_C for r in day_rows))
        if not watching:
            data["skipped"] = True
            return self._section(data)
        key = f"snow_history|{source}|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
        cached = ctx.cache.get_entry(key, FORECAST_TTL_S if source == "forecast" else None)
        if cached is not None:
            data.update(cached[0])
            return self._section(data)
        try:
            response = ctx.http(history_url(FORECAST_URL if source == "forecast" else ARCHIVE_URL, lat, lon, ctx.date))
            rows = parse_history(response)
            span = day_range(rows, ctx.date)
            if span is None:
                raise KeyError("the answer does not contain the plan date")
        except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
            data["error"] = str(e) or type(e).__name__
            return self._section(data)
        data.update({"rows": rows, "elevation_m": response.get("elevation"), "day_start": span[0], "day_end": span[1]})
        ctx.cache.put(key, {k: data[k] for k in ("rows", "elevation_m", "day_start", "day_end")})
        return self._section(data)

    @staticmethod
    def _section(data: dict) -> Section:
        return Section("hazards", "", "derived" if data["rows"] else "no-data", omit=True, shared=data)
