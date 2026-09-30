"""The "Mountain hazards" hazard, reported only for mountain routes: highest
point at or above 600 m, or relief (highest minus lowest) of 300 m or more,
judged from the elevations stored in route.geojson. Without elevation data the
section says so (no-data); for a flat route it is left out ("not applicable").

Tiers by highest point: from 600 m terrain, weather at altitude and cold; from
1500 m stronger UV, cold and dehydration; from 2500 m altitude sickness (oxygen
shortage is not mentioned below that: it starts to matter only there).

Inputs: the route elevations, the weather rows (freezing level, CAPE, gusts,
rain, snow, model elevation), and the shared OpenStreetMap features (`sac_scale`
paths, scree, cliffs, bare rock, glaciers). Avalanche bulletins have no keyless
machine-readable source that maps a route to a region, so the plan gives the
pointer and takes region details from facts.json (plugin id `mountain`).
Everything here is `derived` from those inputs."""

from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from ..osm_features import near
from .common import sources_line

MOUNTAIN_MIN_ELEVATION_M = 600
MOUNTAIN_MIN_RELIEF_M = 300
HIGH_M, AMS_M, AMS_STRONG_M = 1500, 2500, 3500
TRACK_RADIUS_M = 300.0
GLACIER_RADIUS_M = 1000.0
LAPSE_C_PER_KM = 6.5
CAPE_THUNDER = 1000.0
HEAVY_RAIN_MM = 10.0
SNOW_M = 0.10
SAC_ORDER = ("hiking", "mountain_hiking", "demanding_mountain_hiking", "alpine_hiking",
             "demanding_alpine_hiking", "difficult_alpine_hiking")
_THUNDER_CODES = (95, 96, 99)


def elevation_stats(coords: list):
    """(min, max, relief) of the route elevations, or None when the route carries none."""
    values = [c[2] for c in coords if len(c) > 2 and isinstance(c[2], (int, float))]
    if not values:
        return None
    return min(values), max(values), max(values) - min(values)


def _values(rows: list, key: str) -> list:
    return [r[key] for r in rows if r.get(key) is not None]


class MountainPlugin(SectionPlugin):
    plugin_id = "mountain"
    section_id = "hazards"
    depends_on = ("weather", "osm_features")
    title_key = "hz_mountain"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        stats = elevation_stats(ctx.coords)
        if stats is None:
            return Section("hazards", "- " + tr("mt_no_elevation", lang), "no-data")
        low, top, relief = stats
        if top < MOUNTAIN_MIN_ELEVATION_M and relief < MOUNTAIN_MIN_RELIEF_M:
            return Section("hazards", "", "derived", omit=True)          # not a mountain route

        weather = shared.get("weather") or {}
        rows = weather.get("daytime_rows") or weather.get("rows") or []
        osm = shared.get("osm_features") or {}
        lines = ["- " + tr("mt_header", lang, min=f"{low:.0f}", max=f"{top:.0f}", relief=f"{relief:.0f}")]
        warnings = []

        # terrain from OpenStreetMap
        if osm.get("error"):
            lines.append("- " + tr("mt_osm_unavailable", lang, reason=osm["error"]))
        elif osm.get("samples") is not None:
            features, samples = osm.get("features", []), osm["samples"]
            sac = near(features, samples, "sac", TRACK_RADIUS_M)
            rated = [f for f, _ in sac if f.detail in SAC_ORDER]
            if rated:
                worst = max(rated, key=lambda f: SAC_ORDER.index(f.detail)).detail
                names = tr("mt_sac_names", lang)
                lines.append("- " + tr("mt_sac", lang, scale=names[worst], count=len(rated)))
                level = SAC_ORDER.index(worst)
                if level >= 2:
                    warnings.append(PlanWarning("caution" if level == 2 else "danger",
                                                tr("mt_warn_sac", lang, scale=names[worst])))
            parts = []
            for kind in ("scree", "cliff", "bare_rock"):
                count = len(near(features, samples, kind, TRACK_RADIUS_M))
                if count:
                    parts.append(tr("mt_rock_" + kind, lang, n=count))
            if parts:
                lines.append("- " + tr("mt_rock", lang, parts=", ".join(parts)))
            glaciers = near(features, samples, "glacier", GLACIER_RADIUS_M)
            if glaciers:
                metres = f"{glaciers[0][1]:.0f}"
                lines.append("- " + tr("mt_glacier", lang, m=metres))
                warnings.append(PlanWarning("caution", tr("mt_warn_glacier", lang, m=metres)))

        # weather at altitude
        fzl = _values(rows, "fzl")
        if fzl:
            lowest = min(fzl)
            below = lowest < top
            lines.append("- " + tr("mt_freezing", lang, fzl=f"{lowest:.0f}", top=f"{top:.0f}",
                                   relation=tr("mt_freezing_below" if below else "mt_freezing_above", lang),
                                   effect=tr("mt_freezing_below_effect" if below else "mt_freezing_above_effect", lang)))
            if lowest < top - 200:
                warnings.append(PlanWarning("caution", tr("mt_warn_freezing", lang, fzl=f"{lowest:.0f}", top=f"{top:.0f}")))
        temps = _values(rows, "temp")
        if temps:
            reference = weather.get("elevation_m")
            if reference is None:
                reference = next((c[2] for c in ctx.coords if len(c) > 2 and c[2] is not None), low)
            estimate = min(temps) - LAPSE_C_PER_KM * max(0.0, top - reference) / 1000.0
            lines.append("- " + tr("mt_top_temp", lang, temp=f"{estimate:.0f}", top=f"{top:.0f}"))
            if estimate <= 0:
                warnings.append(PlanWarning("caution", tr("mt_warn_top_cold", lang, temp=f"{estimate:.0f}")))
        cape = max(_values(rows, "cape"), default=0.0)
        forecast_thunder = any(r.get("code") in _THUNDER_CODES for r in rows)
        if forecast_thunder:
            lines.append("- " + tr("mt_thunder_forecast", lang))
        if cape >= CAPE_THUNDER or forecast_thunder:
            if cape >= CAPE_THUNDER:
                lines.append("- " + tr("mt_thunder", lang, cape=f"{cape:.0f}"))
            warnings.append(PlanWarning("danger" if forecast_thunder else "caution",
                                        tr("mt_warn_thunder", lang, cape=f"{cape:.0f}")))
        gusts = _values(rows, "gust")
        if gusts and relief >= 500:
            lines.append("- " + tr("mt_wind", lang, gust=f"{max(gusts):.0f}"))
        rain = sum(_values(rows, "precip"))
        if rain >= HEAVY_RAIN_MM:
            lines.append("- " + tr("mt_rain", lang, mm=f"{rain:.0f}"))
            warnings.append(PlanWarning("caution", tr("mt_warn_rain", lang, mm=f"{rain:.0f}")))

        # altitude tiers
        if top >= HIGH_M:
            lines.append("- " + tr("mt_high", lang))
        if top >= AMS_M:
            lines.append("- " + tr("mt_ams", lang))
            if top >= AMS_STRONG_M:
                warnings.append(PlanWarning("caution", tr("mt_warn_ams", lang)))

        # snow and avalanches
        snow = max(_values(rows, "snow_m"), default=0.0)
        winter = ctx.date.month in (11, 12, 1, 2, 3, 4)
        if top >= 1000 and relief >= 300 and (snow >= SNOW_M or (winter and snow > 0)):
            lines.append("- " + tr("mt_snow", lang))
            warnings.append(PlanWarning("caution", tr("mt_warn_snow", lang)))
        if relief >= 500:
            lines.append("- " + tr("mt_shade", lang))

        fact = lookup(ctx.facts, ctx.date_iso, "mountain")
        if fact:
            lines += ["", tr("mt_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        return Section("hazards", "\n".join(lines), "web-sourced" if fact else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings)
