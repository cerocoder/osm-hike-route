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
import hashlib
import math
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..base import PlanWarning, Section, SectionPlugin
from ..http import HttpError
from ..i18n import compass, tr
from ..sun import sun_times
from .common import finish_minute

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15
FORECAST_PAST_DAYS = 7  # the forecast API keeps about a week of past days
CLIMATE_YEARS = 5
FORECAST_TTL_S = 3 * 3600
AFTER_FINISH_MIN = 240

FORECAST_VARS = (
    "temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
    "cloud_cover", "visibility", "weather_code", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "snow_depth", "relative_humidity_2m", "dew_point_2m", "freezing_level_height", "cape",
)
# The archive has no probability, visibility, freezing level or CAPE.
ARCHIVE_VARS = tuple(v for v in FORECAST_VARS if v not in (
    "precipitation_probability", "visibility", "freezing_level_height", "cape"))

# Row keys <- Open-Meteo hourly variable names
_ROW_KEYS = {
    "temperature_2m": "temp", "apparent_temperature": "feels", "precipitation": "precip",
    "precipitation_probability": "prob", "cloud_cover": "cloud", "visibility": "vis_m",
    "weather_code": "code", "wind_speed_10m": "wind", "wind_direction_10m": "wdir",
    "wind_gusts_10m": "gust", "snow_depth": "snow_m", "relative_humidity_2m": "rh", "dew_point_2m": "dew",
    "freezing_level_height": "fzl", "cape": "cape",
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
    code, wind, wdir, gust, snow_m, rh, dew, fzl (freezing level, m), cape."""
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
        for key in ("temp", "feels", "precip", "cloud", "wind", "gust", "snow_m", "vis_m", "prob",
                    "rh", "dew", "fzl", "cape"):
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


def _vars_id(variables) -> str:
    """Short id of a variable set: part of the cache key, so adding a variable
    never reuses an entry that was cached without it."""
    return hashlib.sha1(",".join(variables).encode("utf-8")).hexdigest()[:8]


def _fetch(ctx, source: str, lat: float, lon: float, date: datetime.date | None = None):
    """Returns (rows, utc_offset_seconds, fetched_at_epoch, model_elevation_m) for `date` (default: the plan's date)."""
    date = date or ctx.date
    variables = FORECAST_VARS if source == "forecast" else ARCHIVE_VARS
    key = f"weather|{source}|{_vars_id(variables)}|{lat:.3f}|{lon:.3f}|{date.isoformat()}"
    max_age = FORECAST_TTL_S if source == "forecast" else None
    cached = ctx.cache.get_entry(key, max_age)
    if cached is not None:
        value, stored_at = cached
        return value["rows"], value["utc_offset_seconds"], stored_at, value.get("elevation")

    if source == "forecast":
        response = ctx.http(_url(FORECAST_URL, FORECAST_VARS, lat, lon, date))
        rows, offset = parse_hourly(response), utc_offset_for(response, date)
        elevation = response.get("elevation")
    elif source == "archive":
        response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, date))
        rows, offset = parse_hourly(response), utc_offset_for(response, date)
        elevation = response.get("elevation")
    else:
        per_year, offset, elevation = [], None, None
        for back in range(1, CLIMATE_YEARS + 1):
            past = _same_day_in_year(date, ctx.today.year - back)
            response = ctx.http(_url(ARCHIVE_URL, ARCHIVE_VARS, lat, lon, past))
            per_year.append(parse_hourly(response))
            offset = offset if offset is not None else utc_offset_for(response, date)
            elevation = elevation if elevation is not None else response.get("elevation")
        rows = average_rows(per_year)
    stored_at = ctx.cache.put(key, {"rows": rows, "utc_offset_seconds": offset, "elevation": elevation})
    return rows, offset, stored_at, elevation


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


def needs_next_day(finish_min) -> bool:
    return finish_min is not None and (finish_min + AFTER_FINISH_MIN) // 60 >= 24


def window_rows(day_rows: list, next_rows, finish_min) -> list:
    """The 24 rows of the date plus, when the finish + 4 h passes midnight, the rows of the next day up to that moment.
    Every row is a copy with `day` (0 | 1) and `after` (the hour starts at or after the finish)."""
    out = []
    for row in day_rows:
        out.append({**row, "day": 0, "after": finish_min is not None and row["hour"] * 60 >= finish_min})
    if finish_min is not None and next_rows:
        last_abs = (finish_min + AFTER_FINISH_MIN) // 60
        for row in next_rows:
            if 24 + row["hour"] <= last_abs:
                out.append({**row, "day": 1, "after": (24 + row["hour"]) * 60 >= finish_min})
    return out


def trip_rows(window: list, day_rows: list, start_min, finish_min) -> tuple:
    """(rows walked, rows after the finish). Without a start and a finish the daylight rows stand for the trip."""
    if start_min is None or finish_min is None:
        return day_rows, []
    trip = [r for r in window if not r.get("after") and (24 * r.get("day", 0) + r["hour"]) * 60 + 59 >= start_min]
    post = [r for r in window if r.get("after")]
    return trip or day_rows, post


def mark_daylight(rows: list[dict], date: datetime.date, lat: float, lon: float,
                  utc_offset_seconds: float | None) -> list[dict]:
    """Copies of the rows with `night` (the middle of the hour is before sunrise or after sunset)."""
    offset_min = (utc_offset_seconds if utc_offset_seconds is not None else round(lon / 15.0 * 2) / 2 * 3600) / 60.0
    out = []
    for row in rows:
        sun = sun_times(date + datetime.timedelta(days=row.get("day", 0)), lat, lon)
        if sun.kind == "normal":
            middle = row["hour"] * 60 + 30
            night = not (sun.sunrise_utc_min + offset_min <= middle <= sun.sunset_utc_min + offset_min)
        else:
            night = sun.kind == "polar_night"
        out.append({**row, "night": night})
    return out


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


_SNOW_CODES = (71, 73, 75, 77, 85, 86)
SNOW_TEMP_C = 0.5          # at or below this the precipitation is drawn as snow whatever the (climate-averaged) code says


def _precip_icon(row: dict) -> str:
    """Pictogram of the precipitation: 💧 rain or ❄️ snow, repeated 1-3 times for light / moderate / heavy
    (snow also when the air is at or below SNOW_TEMP_C; rain: under 2.5 and 7.6 mm/h; snow, as water equivalent: under 0.5 and 1.5 mm/h). Empty when dry."""
    precip = row["precip"]
    if not precip or precip < 0.05:
        return ""
    temp = row.get("temp")
    snow = row.get("code") in _SNOW_CODES or (temp is not None and temp <= SNOW_TEMP_C)
    light, heavy = (0.5, 1.5) if snow else (2.5, 7.6)
    level = 1 if precip < light else 2 if precip < heavy else 3
    return ("❄️" if snow else "💧") * level


def _precip_cell(row: dict) -> str:
    if row["precip"] is None:
        return "–"
    text = f"{row['precip']:.1f}"
    if row.get("prob") is not None:
        text += f" ({row['prob']:.0f})"
    icon = _precip_icon(row)
    return f"{icon} {text}" if icon else text


def render_table(rows: list[dict], lang: str) -> str:
    keys = ("w_time", "w_temp", "w_feels", "w_precip", "w_cloud", "w_vis", "w_wind", "w_gust", "w_snow", "w_sky")
    marked = any(r.get("after") for r in rows)
    header = [tr(k, lang) for k in keys] + ([tr("w_after", lang)] if marked else [])
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        vis_km = r["vis_m"] / 1000.0 if r.get("vis_m") is not None else None
        snow_cm = r["snow_m"] * 100.0 if r.get("snow_m") is not None else None
        hour = f"{r['hour']:02d}:00" + (" (+1)" if r.get("day") == 1 else "")
        if "night" in r:
            hour = ("🌙 " if r["night"] else "☀️ ") + hour
        cells = [hour, _num(r["temp"], 0), _num(r["feels"], 0), _precip_cell(r),
                 _num(r["cloud"], 0), _num(vis_km, 1), _wind_cell(r, lang), _num(r["gust"], 1),
                 _num(snow_cm, 0), tr(_sky_key(r["code"]), lang)]
        if marked:
            cells.append("•" if r.get("after") else "")
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
            rows, offset, fetched_at, elevation = _fetch(ctx, source, lat, lon)
        except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
            return Section("weather", tr("w_unavailable", ctx.lang, reason=str(e) or type(e).__name__),
                           "no-data")
        window = None
        if ctx.start_time is not None and ctx.duration_hours:
            start = ctx.start_time.hour * 60 + ctx.start_time.minute
            window = (start, min(start + ctx.duration_hours * 60.0, 23 * 60.0))
        day = daytime_rows(rows, ctx.date, lat, lon, offset, route_window=window) or rows
        start_min = ctx.start_time.hour * 60 + ctx.start_time.minute if ctx.start_time is not None else None
        finish = finish_minute(ctx)
        next_rows = None
        if needs_next_day(finish):
            try:
                next_rows = _fetch(ctx, source, lat, lon, ctx.date + datetime.timedelta(days=1))[0]
            except (HttpError, KeyError, IndexError, ValueError, TypeError):
                next_rows = None           # the 24 hours of the date are still shown
        shown = mark_daylight(window_rows(rows, next_rows, finish), ctx.date, lat, lon, offset)
        trip, post = trip_rows(shown, day, start_min, finish)
        note_key = {"forecast": "w_source_forecast", "archive": "w_source_archive",
                    "climate": "w_source_climate"}[source]
        note = tr(note_key, ctx.lang, years=CLIMATE_YEARS) if source == "climate" else tr(note_key, ctx.lang)
        start_line = ""
        if start_min is not None and finish is not None:
            finish_text = f"{(finish // 60) % 24:02d}:{finish % 60:02d}" + (" (+1)" if finish >= 1440 else "")
            origin = tr("w_start_recommended" if getattr(ctx, "start_source", "none") == "recommended"
                        else "w_start_user", ctx.lang)
            start_line = tr("w_start_line", ctx.lang, start=f"{start_min // 60:02d}:{start_min % 60:02d}",
                            source=origin, finish=finish_text) + "\n\n"
        markdown = start_line + render_table(shown, ctx.lang) + "\n\n*" + note + "*"
        warnings = warnings_for(trip, ctx.lang, source)
        seen = {w.text for w in warnings}
        for w in warnings_for(post, ctx.lang, "forecast"):
            if w.text not in seen:
                warnings.append(PlanWarning(w.severity, f"{tr('w_after_prefix', ctx.lang)} {w.text}"))
        means = [r["temp"] for r in rows if r.get("temp") is not None]
        return Section(
            "weather", markdown, "derived", sources=["https://open-meteo.com/"], warnings=warnings,
            shared={"utc_offset_seconds": offset, "rows": rows, "daytime_rows": day, "window_rows": shown,
                    "source": source, "fetched_at": fetched_at, "elevation_m": elevation,
                    "daily_mean_temp": sum(means) / len(means) if means else None},
        )
