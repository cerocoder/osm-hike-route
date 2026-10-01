"""The "Water nearby" section: the sea or ocean coast first (temperature and tides from the Open-Meteo Marine API),
then the two largest other bodies within 500 m of the route (a lake or river temperature is an estimate from the air
temperature of the previous weeks — no free global source of measured values exists), the rest as a list. Bathing
comes from OSM tags; pollution and hazards from a web-sourced `water` fact. Confidence: web-sourced when a fact is
used, else derived."""
import datetime

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..http import HttpError
from ..i18n import tr
from ..marine import fetch_marine_day, sea_temperature, tide_extrema
from .common import cell, sources_line
from .water_near import rect_distance_m
from .weather import ARCHIVE_URL, FORECAST_HORIZON_DAYS, FORECAST_URL, _same_day_in_year

DETAILED = 2
LIST_MAX = 15
AIR_HISTORY_DAYS = 30
AIR_YEARS = 3
AIR_TTL_S = 6 * 3600
COLD_WATER_C = 15.0
ICE_C = 4.0
BIG_TIDE_M = 2.0
SWIM_SPOT_M = 300.0


def tau_days(kind: str, size_km: float) -> float:
    """The lag (days) with which the surface water follows the air temperature."""
    if kind == "canal":
        return 2.0
    if kind == "river":
        return 3.0
    if size_km < 0.5:
        return 4.0
    if size_km < 5.0:
        return 10.0
    if size_km < 30.0:
        return 18.0
    return 28.0


def estimate_inland_temp(air_means: list, kind: str, size_km: float):
    """Exponentially smoothed air temperature (oldest day first); None with fewer than 20 usable days."""
    values = [v for v in air_means if isinstance(v, (int, float))]
    if len(values) < 20:
        return None
    tau = tau_days(kind, size_km)
    water = values[0]
    for value in values[1:]:
        water += (value - water) / tau
    return max(0.0, water)


def _daily_means(ctx, base: str, lat: float, lon: float, start: datetime.date, end: datetime.date) -> list:
    url = (f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&daily=temperature_2m_mean"
           f"&start_date={start.isoformat()}&end_date={end.isoformat()}&timezone=auto")
    return ctx.http(url)["daily"]["temperature_2m_mean"]


def air_history(ctx, lat: float, lon: float):
    """Daily mean air temperatures of the AIR_HISTORY_DAYS before the date (oldest first), or None."""
    key = f"air_history|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, AIR_TTL_S)
    if cached is not None:
        return cached[0]
    start, end = ctx.date - datetime.timedelta(days=AIR_HISTORY_DAYS), ctx.date - datetime.timedelta(days=1)
    try:
        if (ctx.today - ctx.date).days > 55:
            means = _daily_means(ctx, ARCHIVE_URL, lat, lon, start, end)
        elif (ctx.date - ctx.today).days <= FORECAST_HORIZON_DAYS:
            means = _daily_means(ctx, FORECAST_URL, lat, lon, start, end)
        else:                                              # beyond the forecast: the same weeks of previous years
            per_year = []
            for back in range(1, AIR_YEARS + 1):
                year = ctx.today.year - back
                per_year.append(_daily_means(ctx, ARCHIVE_URL, lat, lon, _same_day_in_year(start, year),
                                             _same_day_in_year(end, year)))
            length = min(len(m) for m in per_year)
            means = []
            for i in range(length):
                column = [m[i] for m in per_year if isinstance(m[i], (int, float))]
                means.append(sum(column) / len(column) if column else None)
    except (HttpError, KeyError, IndexError, TypeError, ValueError):
        return None
    ctx.cache.put(key, means)
    return means


def bathing_status(tags: dict, near_spot: bool) -> str:
    for key in ("swimming", "bathing"):
        value = tags.get(key)
        if value in ("yes", "designated", "permissive"):
            return "allowed"
        if value in ("no", "prohibited"):
            return "forbidden"
    if near_spot or tags.get("sport") == "swimming":
        return "allowed"
    return "unknown"


def _near_text(kind: str, name: str, distance_m: float, lang: str) -> str:
    if kind == "poi":
        what = tr("wt_near_poi", lang, name=cell(name))
    elif kind == "access":
        what = tr("wt_near_access", lang, name=cell(name))
    else:
        what = tr("wt_near_" + kind, lang)
    return tr("wt_near", lang, what=what, m=int(round(distance_m / 50.0) * 50))


def _clock(hours: float) -> str:
    total = int(round(hours * 60))
    return f"{(total // 60) % 24:02d}:{total % 60:02d}" + (" (+1)" if total >= 1440 else "")


class WaterPlugin(SectionPlugin):
    plugin_id = "water"
    section_id = "hazards"
    depends_on = ("weather", "water_near")
    title_key = "hz_water"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        near = shared.get("water_near")
        if near is None or near.get("error"):
            reason = (near or {}).get("error") or "no data"
            return Section("hazards", tr("wt_unavailable", lang, reason=reason), "no-data")
        bodies = sorted(near["bodies"], key=lambda b: -b.size_km)
        sea, spots = near.get("sea"), near.get("swim_spots") or []
        if not bodies and not sea:
            return Section("hazards", "", "derived", omit=True)
        window = (shared.get("weather") or {}).get("window_rows") or []
        last_hour = max((24 * r.get("day", 0) + r["hour"] for r in window), default=23)

        header = [tr(k, lang) for k in ("wt_col_water", "wt_col_near", "wt_col_temp", "wt_col_bathing")]
        rows = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        warnings, extra, coldest = [], [], None

        if sea:
            data = sea_temperature(ctx, sea["lat"], sea["lon"])
            temp_text = "–"
            if data:
                key = "wt_temp_model" if data["kind"] == "model" else "wt_temp_climate"
                temp_text = tr(key, lang, temp=f"{data['temp']:.0f}")
                coldest = (data["temp"], tr("wt_sea", lang), "unknown")
            bathing = "allowed" if spots else "unknown"
            rows.append("| " + " | ".join([
                tr("wt_sea", lang), _near_text(sea["near_kind"], sea["near_name"], sea["distance_m"], lang),
                temp_text, tr("wt_bathing", lang)[bathing]]) + " |")
            extra += self._tides(ctx, data, last_hour, warnings)

        history = None
        detailed = bodies[:DETAILED]
        if detailed:
            lat, lon = ctx.centroid
            history = air_history(ctx, lat, lon)
        for body in detailed:
            temp = estimate_inland_temp(history, body.kind, body.size_km) if history else None
            near_spot = any(rect_distance_m(s_lat, s_lon, body.bbox) <= SWIM_SPOT_M for _, s_lat, s_lon in spots)
            bathing = bathing_status(body.tags, near_spot)
            temp_text = "–"
            if temp is not None:
                temp_text = tr("wt_temp_estimate", lang, temp=f"{temp:.0f}") + (
                    tr("wt_temp_ice", lang) if temp <= ICE_C else "")
                if bathing != "forbidden" and (coldest is None or temp < coldest[0]):
                    coldest = (temp, cell(body.name) or tr("wt_kind", lang)[body.kind], bathing)
            name = cell(body.name) or tr("wt_unnamed", lang)
            rows.append("| " + " | ".join([
                f"{name} ({tr('wt_kind', lang)[body.kind]})", _near_text(body.near_kind, body.near_name,
                                                                       body.distance_m, lang),
                temp_text, tr("wt_bathing", lang)[bathing]]) + " |")
        if coldest is not None and coldest[0] < COLD_WATER_C and coldest[2] != "forbidden":
            warnings.append(PlanWarning("caution", tr("wt_warn_cold", lang, name=coldest[1], temp=f"{coldest[0]:.0f}")))

        lines = ["\n".join(rows)]
        lines += extra
        if near.get("truncated"):
            lines.append("*" + tr("wt_truncated", lang) + "*")
        rest = bodies[DETAILED:]
        if rest:
            listed = ["- " + tr("wt_other_line", lang, name=cell(b.name) or tr("wt_unnamed", lang),
                                 kind=tr("wt_kind", lang)[b.kind], m=int(round(b.distance_m / 50.0) * 50),
                                 near=_near_text(b.near_kind, b.near_name, b.distance_m, lang).split(", ~")[0])
                      for b in rest[:LIST_MAX]]
            if len(rest) > LIST_MAX:
                listed.append("- " + tr("wt_more", lang, n=len(rest) - LIST_MAX))
            lines += [tr("wt_others", lang), "\n".join(listed)]

        fact = lookup(ctx.facts, ctx.date_iso, "water")
        if fact:
            lines += [tr("wt_web_title", lang), fact["markdown"], sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        else:
            lines.append("*" + tr("wt_pollution_none", lang) + "*")
        return Section("hazards", "\n\n".join(lines), "web-sourced" if fact else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings,
                       shared={"water_applies": True})

    @staticmethod
    def _tides(ctx, data, last_hour: int, warnings: list) -> list:
        lang = ctx.lang
        if not data or data["kind"] != "model":
            return ["*" + tr("wt_tides_unavailable", lang) + "*"]
        levels = list(data["day"]["level"])
        if last_hour >= 24:
            try:
                lat, lon = data["point"]
                levels += fetch_marine_day(ctx, lat, lon, ctx.date + datetime.timedelta(days=1))["level"]
            except (HttpError, KeyError, TypeError, ValueError):
                pass
        shown = [v for v in levels[:last_hour + 1] if v is not None]
        events = [e for e in tide_extrema(levels) if e[1] <= last_hour + 1]
        if not events or not shown:
            return ["*" + tr("wt_tides_unavailable", lang) + "*"]
        names = tr("wt_tide_names", lang)
        text = ", ".join(f"{names[kind]} {_clock(hours)} ({level:+.1f} m)" for kind, hours, level in events)
        tidal_range = max(shown) - min(shown)
        if tidal_range >= BIG_TIDE_M:
            warnings.append(PlanWarning("info", tr("wt_warn_tide", lang, range=f"{tidal_range:.1f}")))
        return [tr("wt_tides", lang, events=text)]
