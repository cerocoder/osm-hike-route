"""The "Fire danger" hazard: the official Fire Weather Index (ECMWF via
Copernicus GWIS, keyless, global, 8 days ahead), for Russian routes also the
Nesterov index by Rosleskhoz order No. 287, satellite-detected active fires
near the route (last three days), the wind that would carry fire and smoke,
and — from facts.json, plugin id `fire` — forest-access and open-fire
restrictions found on the web.

The spec asked for an own stdlib FWI; the official GWIS values replace it
because the FWI's Drought Code needs a whole-season spin-up that a per-day
plan cannot reproduce. Tiers: FWI and Nesterov are `derived` (model output),
detections and facts are `web-sourced`."""
import datetime
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import country_code
from ..facts import lookup
from ..fire_index import daily_from_hourly, fwi_class, history_range, kpo_class, nesterov_index
from ..gwis import (
    FWI_HORIZON_DAYS, FWI_FORECAST_TTL_S, HOTSPOT_RADIUS_KM, HOTSPOT_WINDOW_DAYS, fwi_at, hotspots_near,
)
from ..http import HttpError
from ..i18n import compass, tr
from .common import sources_line
from .weather import ARCHIVE_URL, FORECAST_HORIZON_DAYS as OM_HORIZON, FORECAST_PAST_DAYS, FORECAST_URL

ROMAN = ("I", "II", "III", "IV", "V")
_ELEVATED = ("high", "very_high", "extreme")


def _nesterov(ctx, lat: float, lon: float):
    """(index, class) for the date from the last NESTEROV_DAYS days of Open-Meteo data, or None when the date is
    beyond the forecast horizon. Raises HttpError / KeyError on a bad answer."""
    delta = (ctx.date - ctx.today).days
    if delta > OM_HORIZON:
        return None
    forecast = delta >= -FORECAST_PAST_DAYS
    start, end = history_range(ctx.date)
    key = f"nesterov|{'forecast' if forecast else 'archive'}|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, FWI_FORECAST_TTL_S if forecast else None)
    if cached is not None:
        value = cached[0]
    else:
        url = (f"{FORECAST_URL if forecast else ARCHIVE_URL}?latitude={lat:.4f}&longitude={lon:.4f}"
               f"&hourly=temperature_2m,dew_point_2m,precipitation&timezone=auto"
               f"&start_date={start.isoformat()}&end_date={end.isoformat()}")
        days = daily_from_hourly(ctx.http(url))
        if not days:
            raise KeyError("no daily values")
        value = nesterov_index(days)
        ctx.cache.put(key, value)
    return value, kpo_class(value)


def prevailing_wind(rows: list):
    """(direction_from_deg, max_speed_ms) over the given hourly rows, or None."""
    usable = [r for r in rows if r.get("wind") is not None and r.get("wdir") is not None]
    if not usable:
        return None
    x = sum(math.sin(math.radians(r["wdir"])) for r in usable)
    y = sum(math.cos(math.radians(r["wdir"])) for r in usable)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(x, y)) % 360, max(r["wind"] for r in usable)


class FirePlugin(SectionPlugin):
    plugin_id = "fire"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_fire"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        lines, warnings = [], []
        has_model = has_web = False
        elevated = False

        # 1. official FWI
        delta = (ctx.date - ctx.today).days
        if delta > FWI_HORIZON_DAYS:
            lines.append("- " + tr("fire_fwi_beyond", lang, days=FWI_HORIZON_DAYS))
        else:
            try:
                values = fwi_at(ctx, lat, lon, ctx.date)
            except HttpError as e:
                lines.append("- " + tr("fire_fwi_unavailable", lang, reason=str(e) or "error"))
            else:
                if values is None:
                    lines.append("- " + tr("fire_fwi_none", lang))
                else:
                    has_model = True
                    cls = fwi_class(values["FWI"])
                    elevated = cls in _ELEVATED
                    parts = ", ".join(f"{k} {values[k]:.1f}" for k in ("ISI", "BUI", "FFMC", "DMC", "DC") if k in values)
                    lines.append("- " + tr("fire_fwi_line", lang, fwi=f"{values['FWI']:.1f}",
                                           cls=tr("fire_class_" + cls, lang), components=parts or "–"))
                    lines.append("  *" + tr("fire_fwi_note", lang) + "*")
                    if cls in ("high", "very_high", "extreme"):
                        warnings.append(PlanWarning("caution" if cls == "high" else "danger", tr(
                            "fire_warn_fwi", lang, cls=tr("fire_class_" + cls, lang), fwi=f"{values['FWI']:.1f}")))

        # 2. Russia: the Nesterov index of order No. 287
        if country_code(ctx) == "RU":
            try:
                result = _nesterov(ctx, lat, lon)
            except (HttpError, KeyError, IndexError, ValueError, TypeError) as e:
                lines.append("- " + tr("fire_kpo_unavailable", lang, reason=str(e) or type(e).__name__))
            else:
                if result is not None:
                    value, cls = result
                    has_model = True
                    name = tr("fire_kpo_names", lang)[cls - 1]
                    lines.append("- " + tr("fire_kpo_line", lang, value=f"{value:.0f}", roman=ROMAN[cls - 1], name=name))
                    lines.append("  *" + tr("fire_kpo_note", lang) + "*")
                    if cls >= 4:
                        elevated = True
                        warnings.append(PlanWarning("caution" if cls == 4 else "danger", tr(
                            "fire_warn_kpo", lang, roman=ROMAN[cls - 1], name=name)))
                else:
                    lines.append("- " + tr("fire_kpo_beyond", lang))

        # 3. active fires near the route (only meaningful around today)
        hotspots = []
        if -1 <= delta <= HOTSPOT_WINDOW_DAYS:
            samples = shared.get("osm_features", {}).get("samples") or [(lat, lon)]
            try:
                hotspots = hotspots_near(ctx, samples, ctx.today - datetime.timedelta(days=HOTSPOT_WINDOW_DAYS),
                                         ctx.today)
            except HttpError as e:
                lines.append("- " + tr("fire_hotspots_unavailable", lang, reason=str(e) or "error"))
            else:
                has_web = True
                km = f"{HOTSPOT_RADIUS_KM:.0f}"
                if not hotspots:
                    lines.append("- " + tr("fire_hotspots_none", lang, km=km))
                else:
                    elevated = True
                    lines.append("- " + tr("fire_hotspots_some", lang, km=km))
                    for h, distance in hotspots[:5]:
                        frp = tr("fire_hotspot_frp", lang, frp=f"{h.frp_mw:.1f}") if h.frp_mw is not None else ""
                        lines.append(tr("fire_hotspot_item", lang, dist=f"{distance:.1f}", date=h.date, time=h.time,
                                        sat=h.satellite or "?", conf=h.confidence or "?", frp=frp))
                    nearest, distance = hotspots[0]
                    warnings.append(PlanWarning("danger" if distance <= 5.0 else "caution", tr(
                        "fire_warn_hotspot", lang, km=f"{distance:.0f}", date=nearest.date)))

        # 4. the wind that would carry it
        if elevated:
            wind = prevailing_wind((shared.get("weather") or {}).get("daytime_rows") or [])
            if wind:
                deg, speed = wind
                lines.append("- " + tr("fire_wind", lang, dir=compass(deg, lang), deg=f"{deg:.0f}",
                                       speed=f"{speed:.1f}", to=compass((deg + 180) % 360, lang)))

        # 5. restrictions recorded from the web
        fact = lookup(ctx.facts, ctx.date_iso, "fire")
        if fact:
            lines += ["", tr("fire_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))

        confidence = "web-sourced" if (fact or has_web) else "derived" if has_model else "no-data"
        return Section("hazards", "\n".join(lines), confidence, sources=list(fact["sources"]) if fact else [],
                       warnings=warnings)
