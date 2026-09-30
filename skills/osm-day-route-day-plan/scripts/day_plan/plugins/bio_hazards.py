"""Ticks and biting insects (mosquitoes, blackflies and midges, horseflies).

An estimate from the weather rows (temperature, wind, humidity, cloud, hour),
the season for the hemisphere, and — for the habitat — the water that
OpenStreetMap shows within 1-1.5 km of the route (shared `osm_features`). It is
labelled `derived`: the thresholds below are heuristics from general
entomology, kept in one table so a region can be tuned, not measurements.
Where the season or peaks of a region differ, facts.json (plugin id
`bio_hazards`, web-sourced) adds the local picture (also the place for
regional notes on animals). When nothing is in season and no fact exists the
section is left out.

Bands per hour: 0 low, 1 moderate, 2 high; a missing habitat lowers the band
by one (never below 0)."""
from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from ..osm_features import near
from .common import hour_ranges, sources_line

TICK_ACTIVE_C = 5.0          # ticks become active at about +5..+7 C
TICK_HOT_C = 25.0            # dry heat lowers their activity
TICK_MONTHS = (3, 4, 5, 6, 7, 8, 9, 10, 11)      # northern hemisphere
INSECT_MONTHS = {"mosquito": (5, 6, 7, 8, 9), "blackfly": (5, 6, 7, 8, 9), "horsefly": (6, 7, 8)}
STILL_WATER_RADIUS_M = 1500.0
RUNNING_WATER_RADIUS_M = 1000.0
_BANDS = ("low", "moderate", "high")


def in_season(month: int, months: tuple, latitude: float) -> bool:
    """Northern seasons as given; the southern hemisphere is shifted by half a year."""
    return (month if latitude >= 0 else (month + 5) % 12 + 1) in months


def tick_band(mean_temp: float) -> int:
    if mean_temp < TICK_ACTIVE_C:
        return 0
    if mean_temp < 7.0 or mean_temp > TICK_HOT_C:
        return 1
    return 2


def mosquito_band(row: dict, dawn_dusk: bool) -> int:
    temp, wind = row.get("temp"), row.get("wind")
    if temp is None or temp < 10.0 or (wind is not None and wind >= 4.0):
        return 0
    band = 2 if 15.0 <= temp <= 28.0 else 1
    if dawn_dusk:
        band = min(2, band + 1)
    if (row.get("rh") or 0) >= 75:
        band = min(2, band + 1)
    return band


def blackfly_band(row: dict, daytime: bool) -> int:
    temp, wind = row.get("temp"), row.get("wind")
    if not daytime or temp is None or not 8.0 <= temp <= 28.0 or (wind is not None and wind >= 3.0):
        return 0
    return 2 if 15.0 <= temp <= 25.0 else 1


def horsefly_band(row: dict) -> int:
    temp, wind, cloud = row.get("temp"), row.get("wind"), row.get("cloud")
    if temp is None or temp < 20.0 or not 11 <= row["hour"] <= 17:
        return 0
    if (wind is not None and wind >= 5.0) or (cloud is not None and cloud >= 70):
        return 0
    return 2 if temp >= 24.0 else 1


class BioHazardsPlugin(SectionPlugin):
    plugin_id = "bio_hazards"
    section_id = "hazards"
    depends_on = ("weather", "light", "osm_features")
    title_key = "hz_bio"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        lat, _ = ctx.centroid
        weather = shared.get("weather") or {}
        rows = weather.get("daytime_rows") or weather.get("rows") or []
        light = shared.get("light") or {}
        osm = shared.get("osm_features") or {}
        lines, warnings = [], []
        month = ctx.date.month

        # ticks
        mean = weather.get("daily_mean_temp")
        if mean is not None and in_season(month, TICK_MONTHS, lat):
            band = tick_band(mean)
            lines.append("- " + tr("bio_tick", lang, band=tr("bio_band", lang)[_BANDS[band]], temp=f"{mean:.0f}"))
            if band >= 1:
                lines.append("  " + tr("bio_tick_advice", lang))
            if band == 2:
                warnings.append(PlanWarning("caution", tr("bio_warn_tick", lang, temp=f"{mean:.0f}")))

        # biting insects
        habitat_known = bool(osm) and not osm.get("error") and osm.get("samples") is not None
        features, samples = osm.get("features", []), osm.get("samples") or []
        still = habitat_known and bool(near(features, samples, ("water", "wetland"), STILL_WATER_RADIUS_M))
        running = habitat_known and bool(near(features, samples, "waterway", RUNNING_WATER_RADIUS_M))
        any_water = habitat_known and bool(near(features, samples, ("water", "wetland", "waterway"), STILL_WATER_RADIUS_M))
        sunrise, sunset = light.get("sunrise_local_min"), light.get("sunset_local_min")

        def dawn_dusk(hour):
            if sunrise is None or sunset is None:
                return False
            mid = hour * 60 + 30
            return sunrise <= mid <= sunrise + 120 or sunset - 120 <= mid <= sunset

        def daytime(hour):
            return sunrise is None or sunset is None or sunrise + 60 <= hour * 60 + 30 <= sunset - 60

        groups = (("mosquito", lambda r: mosquito_band(r, dawn_dusk(r["hour"])), still),
                  ("blackfly", lambda r: blackfly_band(r, daytime(r["hour"])), running),
                  ("horsefly", horsefly_band, any_water))
        advice = False
        names = tr("bio_insect_names", lang)
        for key, band_of, habitat in groups:
            if not rows or not in_season(month, INSECT_MONTHS[key], lat):
                continue
            bands = [(r["hour"], band_of(r)) for r in rows]
            if habitat_known and not habitat:
                bands = [(h, max(0, b - 1)) for h, b in bands]
            peak = max(b for _, b in bands)
            peak_hours = [h for h, b in bands if b == peak]
            if peak == 0:
                lines.append("- " + tr("bio_insect", lang, name=names[key], band=tr("bio_band", lang)["low"],
                                       hours=tr("bio_insect_none", lang)))
                continue
            advice = True
            windows = hour_ranges(peak_hours)
            lines.append("- " + tr("bio_insect", lang, name=names[key], band=tr("bio_band", lang)[_BANDS[peak]],
                                   hours=tr("bio_insect_hours", lang, hours=windows)))
            if peak == 2 and key in ("mosquito", "blackfly"):
                warnings.append(PlanWarning("caution", tr("bio_warn_insect", lang, name=names[key], hours=windows)))
        if advice:
            lines.append("  " + tr("bio_insect_advice", lang))
        if any(l.startswith("- " + names[k]) for l in lines for k in names):
            if not habitat_known:
                lines.append("  *" + tr("bio_insect_note_water", lang) + "*")
            lines.append("  *" + tr("bio_rules", lang) + "*")

        missing_weather = False
        if not lines and not rows and mean is None:
            seasons = (TICK_MONTHS, *INSECT_MONTHS.values())
            if any(in_season(month, months, lat) for months in seasons):
                lines.append("- " + tr("bio_no_weather", lang))          # in season, but nothing to judge by
                missing_weather = True

        fact = lookup(ctx.facts, ctx.date_iso, "bio_hazards")
        if fact:
            lines += ["", tr("bio_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
        if not lines:
            return Section("hazards", "", "derived", omit=True)          # nothing in season: not applicable
        return Section("hazards", "\n".join(lines), "web-sourced" if fact else "no-data" if missing_weather else "derived",
                       sources=list(fact["sources"]) if fact else [], warnings=warnings)
