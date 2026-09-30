"""Air: pollen, pollution and industrial emissions.

* Pollen and pollution come from the Open-Meteo Air Quality API (CAMS models,
  keyless). Checked live: the pollen model returns `null` outside its European
  domain (about 30-71 N, up to about 45 E: Moscow yes, Kazan and Yekaterinburg
  no) and real zeros inside it, so `null` is reported as "no data", never as
  "no pollen". Pollution values exist for the whole world, for about four days
  ahead; two more days return only nulls and later dates answer HTTP 400.
* Pollen levels use the US National Allergy Bureau scale (tree 15/90/1500,
  grass 5/20/200, weed 10/50/500 grains/m3); the European AQI classes are the
  EEA ones (20/40/60/80/100).
* Emissions: industrial sites and power plants from the shared OpenStreetMap
  features within 5 km of the route, and the hours at which the wind carries
  them toward the route (within 45 degrees of the bearing site -> route).
All of it is `derived`; facts.json (plugin id `air`, web-sourced) can add
regional advisories (for example smoke)."""
import math

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..http import HttpError
from ..i18n import tr
from ..osm_features import haversine_m, near
from .common import hour_ranges, sources_line

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN_VARS = ("alder_pollen", "birch_pollen", "olive_pollen", "grass_pollen", "mugwort_pollen", "ragweed_pollen")
POLLUTION_VARS = ("pm2_5", "pm10", "ozone", "nitrogen_dioxide", "sulphur_dioxide", "dust", "european_aqi")
AQ_VARS = POLLEN_VARS + POLLUTION_VARS
AQ_TTL_S = 3 * 3600
POLLEN_SCALES = {                       # (moderate from, high from, very high from) in grains/m3
    "tree": (15, 90, 1500), "grass": (5, 20, 200), "weed": (10, 50, 500)}
POLLEN_GROUP = {"alder_pollen": "tree", "birch_pollen": "tree", "olive_pollen": "tree", "grass_pollen": "grass",
                "mugwort_pollen": "weed", "ragweed_pollen": "weed"}
AQI_STEPS = (20, 40, 60, 80, 100)       # European AQI: good, fair, moderate, poor, very poor, extremely poor
EMISSION_RADIUS_M = 5000.0
DOWNWIND_TOLERANCE_DEG = 45.0
DEFAULT_HOURS = range(6, 22)


def pollen_level(variable: str, value: float) -> str:
    moderate, high, very_high = POLLEN_SCALES[POLLEN_GROUP[variable]]
    if value >= very_high:
        return "very_high"
    if value >= high:
        return "high"
    if value >= moderate:
        return "moderate"
    return "low"


def aqi_class(aqi: float) -> int:
    for i, limit in enumerate(AQI_STEPS):
        if aqi < limit:
            return i
    return len(AQI_STEPS)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_difference(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _fetch(ctx, lat: float, lon: float) -> dict:
    """The hourly air-quality arrays for the date. Raises HttpError."""
    key = f"air|{lat:.2f}|{lon:.2f}|{ctx.date_iso}"
    cached = ctx.cache.get_entry(key, AQ_TTL_S if ctx.date >= ctx.today else None)
    if cached is not None:
        return cached[0]
    d = ctx.date_iso
    data = ctx.http(f"{AQ_URL}?latitude={lat:.4f}&longitude={lon:.4f}&hourly={','.join(AQ_VARS)}"
                    f"&timezone=auto&start_date={d}&end_date={d}")
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict) or "time" not in hourly:
        raise HttpError((data or {}).get("reason", "unexpected answer") if isinstance(data, dict) else "unexpected answer")
    ctx.cache.put(key, hourly)
    return hourly


def _daytime_max(hourly: dict, variable: str, hours) -> float | None:
    series = hourly.get(variable)
    if not series:
        return None
    values = [v for t, v in zip(hourly["time"], series) if v is not None and int(t[11:13]) in hours]
    return max(values) if values else None


def _number(value, digits=0) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _grains(value: float) -> str:
    """Small pollen counts keep a decimal (0.4 must not read as 0)."""
    return f"{value:.1f}" if value < 10 else f"{value:.0f}"


class AirPlugin(SectionPlugin):
    plugin_id = "air"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_air"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, lon = ctx.centroid
        weather = shared.get("weather") or {}
        day_rows = weather.get("daytime_rows") or []
        hours = {r["hour"] for r in day_rows} or set(DEFAULT_HOURS)
        lines, warnings, has_data = [], [], False

        try:
            hourly = _fetch(ctx, lat, lon)
        except HttpError as e:
            lines.append("- " + tr("air_unavailable", lang, reason=str(e) or "error"))
        else:
            # pollen
            peaks = {v: _daytime_max(hourly, v, hours) for v in POLLEN_VARS}
            if all(p is None for p in peaks.values()):
                lines.append("- " + tr("air_pollen_no_data", lang))
            else:
                has_data = True
                present = {v: p for v, p in peaks.items() if p is not None and p > 0}
                if not present:
                    lines.append("- " + tr("air_pollen_none", lang))
                else:
                    names, levels = tr("air_pollen_kinds", lang), tr("air_level", lang)
                    parts = ", ".join(f"{names[v]} {_grains(p)} ({levels[pollen_level(v, p)]})"
                                      for v, p in sorted(present.items(), key=lambda kv: -kv[1]))
                    lines.append("- " + tr("air_pollen_line", lang, parts=parts))
                    lines.append("  *" + tr("air_pollen_scale", lang) + "*")
                    worst = max(present.items(), key=lambda kv: (pollen_level(kv[0], kv[1]) in ("high", "very_high"), kv[1]))
                    if pollen_level(*worst) in ("high", "very_high"):
                        warnings.append(PlanWarning("caution", tr("air_warn_pollen", lang, kind=names[worst[0]],
                                                                  value=_grains(worst[1]))))
            # pollution
            values = {v: _daytime_max(hourly, v, hours) for v in POLLUTION_VARS}
            if values["european_aqi"] is None and all(v is None for v in values.values()):
                lines.append("- " + tr("air_pollution_no_data", lang))
            else:
                has_data = True
                aqi = values["european_aqi"]
                cls = aqi_class(aqi) if aqi is not None else 0
                lines.append("- " + tr("air_pollution_line", lang, pm25=_number(values["pm2_5"]), pm10=_number(values["pm10"]),
                                       o3=_number(values["ozone"]), no2=_number(values["nitrogen_dioxide"]),
                                       so2=_number(values["sulphur_dioxide"]), dust=_number(values["dust"]),
                                       aqi=_number(aqi), aqi_class=tr("air_aqi", lang)[cls]))
                if aqi is not None and cls >= 3:
                    warnings.append(PlanWarning("danger" if cls >= 5 else "caution", tr("air_warn_aqi", lang, aqi=f"{aqi:.0f}")))

        # industrial emissions carried toward the route by the wind
        osm = shared.get("osm_features") or {}
        if osm.get("samples") and not osm.get("error"):
            sites = near(osm.get("features", []), osm["samples"], "industrial", EMISSION_RADIUS_M)
            if sites:
                km = f"{EMISSION_RADIUS_M / 1000:.0f}"
                downwind_sites, downwind_hours = set(), set()
                for row in day_rows:
                    if row.get("wind") is None or row.get("wdir") is None or row["wind"] < 1.0:
                        continue
                    carried_to = (row["wdir"] + 180.0) % 360.0
                    for feature, _ in sites:
                        nearest = min(osm["samples"], key=lambda s: haversine_m(feature.lat, feature.lon, s[0], s[1]))
                        if angle_difference(bearing_deg(feature.lat, feature.lon, nearest[0], nearest[1]), carried_to) \
                                <= DOWNWIND_TOLERANCE_DEG:
                            downwind_sites.add((feature.lat, feature.lon))
                            downwind_hours.add(row["hour"])
                if downwind_hours:
                    windows = hour_ranges(sorted(downwind_hours))
                    lines.append("- " + tr("air_emissions", lang, km=km, count=len({(f.lat, f.lon) for f, _ in sites}),
                                           down=len(downwind_sites), hours=windows))
                    warnings.append(PlanWarning("info", tr("air_warn_emissions", lang, hours=windows)))
                else:
                    lines.append("- " + tr("air_emissions_none_downwind", lang, km=km,
                                           count=len({(f.lat, f.lon) for f, _ in sites})))

        fact = lookup(ctx.facts, ctx.date_iso, "air")
        if fact:
            lines += ["", tr("air_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        confidence = "web-sourced" if fact else "derived" if has_data else "no-data"
        return Section("hazards", "\n".join(lines), confidence, sources=list(fact["sources"]) if fact else [],
                       warnings=warnings)
