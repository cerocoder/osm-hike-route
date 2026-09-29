"""Hourly weather from Open-Meteo (free, no key). Source depends on the
date relative to today:

  today-7d .. today+15d   forecast API (the last week is model data)
  older than today-7d     historical archive (recorded weather)
  beyond today+15d        climatology: average of the same date over the
                          last CLIMATE_YEARS years from the archive, labelled
                          as NOT a forecast (spec)

Confidence is always `derived` (model output). Wind direction is reported as
the direction the wind blows FROM. Open-Meteo applies no elevation
correction to wind, so mountain gusts are likely underestimated."""
import datetime
import math
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..base import PlanWarning, Section, SectionPlugin
from ..http import HttpError
from ..i18n import compass, tr
from ..sun import sun_times

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15
FORECAST_PAST_DAYS = 7  # the forecast API keeps about a week of past days
CLIMATE_YEARS = 5
FORECAST_TTL_S = 3 * 3600

FORECAST_VARS = (
    "temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
    "cloud_cover", "visibility", "weather_code", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "snow_depth",
)
ARCHIVE_VARS = tuple(v for v in FORECAST_VARS if v not in ("precipitation_probability", "visibility"))

# Row keys <- Open-Meteo hourly variable names
_ROW_KEYS = {
    "temperature_2m": "temp", "apparent_temperature": "feels", "precipitation": "precip",
    "precipitation_probability": "prob", "cloud_cover": "cloud", "visibility": "vis_m",
    "weather_code": "code", "wind_speed_10m": "wind", "wind_direction_10m": "wdir",
    "wind_gusts_10m": "gust", "snow_depth": "snow_m",
}

THRESHOLDS = {
    "gust_caution": 10.0, "gust_danger": 17.0,   # m/s
    "cold_caution": -10.0, "cold_danger": -25.0,  # feels-like, °C
    "heat_caution": 32.0, "heat_danger": 38.0,
    "rain_caution": 2.0,                          # mm/h
    "snow_cm": 5.0,
    "fog_visibility_m": 1000.0,
}
_THUNDER_CODES = (95, 96, 99)
_FOG_CODES = (45, 48)
# Hours shown when there is no normal sunrise/sunset.
_POLAR_DAY_HOURS = (6, 22)
_POLAR_NIGHT_HOURS = (9, 15)


def choose_source(date: datetime.date, today: datetime.date) -> str:
    delta = (date - today).days
    if delta > FORECAST_HORIZON_DAYS:
        return "climate"
    if delta >= -FORECAST_PAST_DAYS:
        return "forecast"
    return "archive"


def _url(base: str, variables, lat: float, lon: float, date: datetime.date) -> str:
    d = date.isoformat()
    return (f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&hourly={','.join(variables)}"
            f"&wind_speed_unit=ms&timezone=auto&start_date={d}&end_date={d}")


def parse_hourly(response: dict) -> list[dict]:
    """Open-Meteo response -> list of 24 row dicts (missing variables are
    None). Row keys: hour (int), temp, feels, precip, prob, cloud, vis_m,
    code, wind, wdir, gust, snow_m."""
    hourly = response["hourly"]
    times = hourly["time"]
    rows = []
    for i, stamp in enumerate(times):
        row = {"hour": int(stamp[11:13])}
        for api_key, row_key in _ROW_KEYS.items():
            series = hourly.get(api_key)
            row[row_key] = series[i] if series is not None and i < len(series) else None
        rows.append(row)
    return rows


def _vector_mean_direction(directions: list[float]) -> float | None:
    if not directions:
        return None
    x = sum(math.sin(math.radians(d)) for d in directions)
    y = sum(math.cos(math.radians(d)) for d in directions)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(x, y)) % 360


def average_rows(per_year_rows: list[list[dict]]) -> list[dict]:
    """Hour-by-hour climatology over several years' rows."""
    out = []
    for hour in range(24):
        samples = [r for rows in per_year_rows for r in rows if r["hour"] == hour]
        row = {"hour": hour}
        for key in ("temp", "feels", "precip", "cloud", "wind", "gust", "snow_m", "vis_m", "prob"):
            values = [s[key] for s in samples if s.get(key) is not None]
            row[key] = sum(values) / len(values) if values else None
        codes = [s["code"] for s in samples if s.get("code") is not None]
        row["code"] = Counter(codes).most_common(1)[0][0] if codes else None
        row["wdir"] = _vector_mean_direction([s["wdir"] for s in samples if s.get("wdir") is not None])
        out.append(row)
    return out


def utc_offset_for(response: dict, date: datetime.date) -> float | None:
    """UTC offset (seconds) valid ON `date`. Open-Meteo's own
    `utc_offset_seconds` reflects the moment of the request, not the requested
    date (checked live: an archive request for a January date returned the
    summer offset), so prefer the IANA zone name it also returns."""
    name = response.get("timezone")
    if name:
        try:
            offset = ZoneInfo(name).utcoffset(datetime.datetime.combine(date, datetime.time(12)))
            if offset is not None:
                return offset.total_seconds()
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return response.get("utc_offset_seconds")


def _same_day_in_year(date: datetime.date, year: int) -> datetime.date:
    try:
        return date.replace(year=year)
    except ValueError:  # 29 February
        return date.replace(year=year, day=28)


def _fetch(ctx, source: str, lat: float, lon: float):
    """Returns (rows, utc_offset_seconds, fetched_at_epoch)."""
    key = f"weather|{source}|{lat:.3f}|{lon:.3f}|{ctx.date_iso}"
    max_age = FORECAST_TTL_S if source == "forecast" else None
    cached = ctx.cache.get_entry(key, max_age)
    if cached is not None:
        value, stored_at = cached
        return value["rows"], value["utc_offset_seconds"], stored_at

    if source == "forecast":
        response = ctx.http(_url(FORECAST_URL, FORECAST_VARS, lat, lon, ctx.date))
        rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
    elif source == "archive":
        response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, ctx.date))
        rows, offset = parse_hourly(response), utc_offset_for(response, ctx.date)
    else:
        per_year, offset = [], None
        for back in range(1, CLIMATE_YEARS + 1):
            past = _same_day_in_year(ctx.date, ctx.today.year - back)
            response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, past))
            per_year.append(parse_hourly(response))
            offset = offset if offset is not None else utc_offset_for(response, ctx.date)
        rows = average_rows(per_year)
    stored_at = ctx.cache.put(key, {"rows": rows, "utc_offset_seconds": offset})
    return rows, offset, stored_at


def daytime_rows(rows: list[dict], date: datetime.date, lat: float, lon: float,
                 utc_offset_seconds: float | None,
                 route_window: tuple[float, float] | None = None) -> list[dict]:
    """Rows for the daylight hours; `route_window` = (start, end) in local
    minutes of the day additionally keeps the hours walked outside daylight
    (not applied on polar days/nights, which use a fixed window)."""
    sun = sun_times(date, lat, lon)
    if sun.kind == "polar_day":
        lo, hi = _POLAR_DAY_HOURS
        return [r for r in rows if lo <= r["hour"] <= hi]
    if sun.kind == "polar_night":
        lo, hi = _POLAR_NIGHT_HOURS
        return [r for r in rows if lo <= r["hour"] <= hi]
    offset_min = (utc_offset_seconds if utc_offset_seconds is not None else round(lon / 15.0 * 2) / 2 * 3600) / 60.0
    sunrise = sun.sunrise_utc_min + offset_min
    sunset = sun.sunset_utc_min + offset_min
    def wanted(r):
        lo, hi = r["hour"] * 60, r["hour"] * 60 + 59
        if hi >= sunrise and lo <= sunset:
            return True
        return route_window is not None and hi >= route_window[0] and lo <= route_window[1]

    return [r for r in rows if wanted(r)]


def _sky_key(code) -> str:
    if code is None:
        return "sky_unknown"
    if code in _THUNDER_CODES:
        return "sky_thunder"
    if code in _FOG_CODES:
        return "sky_fog"
    if code in (51, 53, 55, 56, 57):
        return "sky_drizzle"
    if code in (61, 63, 65, 66, 67):
        return "sky_rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "sky_snow"
    if code in (80, 81, 82):
        return "sky_showers"
    if code in (0, 1):
        return "sky_clear"
    if code == 2:
        return "sky_partly"
    if code == 3:
        return "sky_overcast"
    return "sky_unknown"


def _num(value, digits=0) -> str:
    if value is None:
        return "–"
    text = f"{value:.{digits}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def _wind_cell(row: dict, lang: str) -> str:
    if row["wind"] is None:
        return "–"
    label = compass(row["wdir"], lang) if row["wdir"] is not None else ""
    return f"{row['wind']:.1f} {label} ({row['wdir']:.0f}°)" if label else f"{row['wind']:.1f}"


def _precip_cell(row: dict) -> str:
    if row["precip"] is None:
        return "–"
    text = f"{row['precip']:.1f}"
    return f"{text} ({row['prob']:.0f})" if row.get("prob") is not None else text


def render_table(rows: list[dict], lang: str) -> str:
    header = [tr(k, lang) for k in ("w_time", "w_temp", "w_feels", "w_precip", "w_cloud", "w_vis",
                                    "w_wind", "w_gust", "w_snow", "w_sky")]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        vis_km = r["vis_m"] / 1000.0 if r.get("vis_m") is not None else None
        snow_cm = r["snow_m"] * 100.0 if r.get("snow_m") is not None else None
        cells = [f"{r['hour']:02d}:00", _num(r["temp"], 0), _num(r["feels"], 0), _precip_cell(r),
                 _num(r["cloud"], 0), _num(vis_km, 1), _wind_cell(r, lang), _num(r["gust"], 1),
                 _num(snow_cm, 0), tr(_sky_key(r["code"]), lang)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _max(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return max(values) if values else None


def _min(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return min(values) if values else None


def warnings_for(rows: list[dict], lang: str, source: str) -> list[PlanWarning]:
    th = THRESHOLDS
    out = []
    if source == "climate":
        out.append(PlanWarning("info", tr("w_warn_climate", lang)))
    if any(r.get("code") in _THUNDER_CODES for r in rows):
        out.append(PlanWarning("danger", tr("w_warn_thunder", lang)))
    if any(r.get("code") in _FOG_CODES or (r.get("vis_m") is not None and r["vis_m"] < th["fog_visibility_m"])
           for r in rows):
        out.append(PlanWarning("caution", tr("w_warn_fog", lang)))
    gust = _max(rows, "gust")
    if gust is not None and gust >= th["gust_caution"]:
        severity = "danger" if gust >= th["gust_danger"] else "caution"
        name = tr("gust_storm" if severity == "danger" else "gust_strong", lang)
        out.append(PlanWarning(severity, tr("w_warn_gust", lang, value=f"{gust:.0f}", label=name)))
    cold = _min(rows, "feels")
    if cold is not None and cold <= th["cold_caution"]:
        severity = "danger" if cold <= th["cold_danger"] else "caution"
        out.append(PlanWarning(severity, tr("w_warn_cold", lang, value=f"{cold:.0f}")))
    heat = _max(rows, "feels")
    if heat is not None and heat >= th["heat_caution"]:
        severity = "danger" if heat >= th["heat_danger"] else "caution"
        out.append(PlanWarning(severity, tr("w_warn_heat", lang, value=f"{heat:.0f}")))
    rain = _max(rows, "precip")
    if rain is not None and rain >= th["rain_caution"]:
        out.append(PlanWarning("caution", tr("w_warn_rain", lang, value=f"{rain:.1f}")))
    snow = _max(rows, "snow_m")
    if snow is not None and snow * 100.0 >= th["snow_cm"]:
        out.append(PlanWarning("info", tr("w_warn_snow", lang, value=f"{snow * 100.0:.0f}")))
    return out


class WeatherPlugin(SectionPlugin):
    plugin_id = "weather"
    section_id = "weather"

    def run(self, ctx, shared: dict) -> Section:
        lat, lon = ctx.centroid
        source = choose_source(ctx.date, ctx.today)
        try:
            rows, offset, fetched_at = _fetch(ctx, source, lat, lon)
        except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
            return Section("weather", tr("w_unavailable", ctx.lang, reason=str(e) or type(e).__name__),
                           "no-data")
        window = None
        if ctx.start_time is not None and ctx.duration_hours:
            start = ctx.start_time.hour * 60 + ctx.start_time.minute
            window = (start, min(start + ctx.duration_hours * 60.0, 23 * 60.0))
        day = daytime_rows(rows, ctx.date, lat, lon, offset, route_window=window) or rows
        note_key = {"forecast": "w_source_forecast", "archive": "w_source_archive",
                    "climate": "w_source_climate"}[source]
        note = tr(note_key, ctx.lang, years=CLIMATE_YEARS) if source == "climate" else tr(note_key, ctx.lang)
        markdown = render_table(day, ctx.lang) + "\n\n*" + note + "*"
        means = [r["temp"] for r in rows if r.get("temp") is not None]
        return Section(
            "weather", markdown, "derived", sources=["https://open-meteo.com/"],
            warnings=warnings_for(day, ctx.lang, source),
            shared={"utc_offset_seconds": offset, "rows": rows, "daytime_rows": day, "source": source,
                    "fetched_at": fetched_at,
                    "daily_mean_temp": sum(means) / len(means) if means else None},
        )
