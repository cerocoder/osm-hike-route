"""The "Radiation" hazard: the route and its points against the hand-curated
registry (`data/radiation_zones.json`, see `day_plan/radiation.py`).

Independent of the network and of every other plugin, so the warning survives
whatever else fails. Its warnings are `pinned`: the Summary lists them before
other warnings of the same severity, so five gust warnings cannot push a
contaminated zone out of the top five. A route with no hit is told "no entry
in the registry", never "safe". A route far outside the registry's area
(scope) gets no radiation part at all: nothing applies."""
from ..base import PlanWarning, Section, SectionPlugin
from ..i18n import tr
from ..radiation import find_hits, in_scope, load_registry
from .common import sources_line


def _unique(urls: list) -> list:
    seen, out = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


class RadiationPlugin(SectionPlugin):
    plugin_id = "radiation"
    section_id = "hazards"
    title_key = "hz_radiation"

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        registry = load_registry()
        lat, lon = ctx.centroid
        route = [(c[0], c[1]) for c in ctx.coords]
        points = [(p.lon, p.lat) for p in ctx.access_points + ctx.interest_points]
        if not any(in_scope(registry, c[1], c[0]) for c in route[:1] + route[-1:] + [(lon, lat)]):
            return Section("hazards", "", "derived", omit=True)             # far outside the registry's area
        margin = registry["margin_km"]
        all_hits = find_hits(registry, route, points)
        hits = [h for h in all_hits if h.inside or h.zone["severity"] != "info"]     # an advisory area matters only inside it
        if not hits:
            key = "rad_none_advisory" if all_hits else "rad_none"      # near-but-outside advisory areas were dropped
            return Section("hazards", "- " + tr(key, lang, km=f"{margin:g}", areas=tr("rad_areas", lang)), "derived")
        lines, warnings, urls = [], [], []
        any_danger_zone_reached = False
        for hit in hits:
            zone = hit.zone
            name = zone["name"].get(lang) or zone["name"]["en"]
            contamination = zone["contamination"].get(lang) or zone["contamination"]["en"]
            status = zone["status"].get(lang) or zone["status"]["en"]
            danger_zone = zone["severity"] == "danger"
            severity_label = tr("rad_sev_" + zone["severity"], lang)
            if hit.inside:
                line = tr("rad_inside", lang, name=name, severity=severity_label,
                          contamination=contamination[:1].upper() + contamination[1:], status=status)
            else:
                line = tr("rad_near", lang, name=name, severity=severity_label, km=f"{hit.distance_km:.1f}",
                          contamination=contamination[:1].upper() + contamination[1:], status=status)
            if zone["approximate"]:
                line += tr("rad_approx", lang, note=zone["geometry_note"].get(lang) or zone["geometry_note"]["en"])
            lines.append(line)
            urls += [s["url"] for s in zone["sources"]]
            if hit.inside and danger_zone:
                any_danger_zone_reached = True
                warnings.append(PlanWarning("danger", tr("rad_warn_inside_danger", lang, name=name), pinned=True))
            elif hit.inside and zone["severity"] == "info":
                warnings.append(PlanWarning("info", tr("rad_warn_inside_info", lang, name=name)))
            elif hit.inside:
                warnings.append(PlanWarning("caution", tr("rad_warn_inside_caution", lang, name=name), pinned=True))
            else:
                warnings.append(PlanWarning("caution" if danger_zone else "info",
                                            tr("rad_warn_near", lang, name=name, km=f"{hit.distance_km:.1f}"),
                                            pinned=True))
        if any(h.zone["advice"] == "full" for h in hits):
            lines += ["", tr("rad_advice_title", lang), tr("rad_advice_food", lang), tr("rad_advice_water", lang),
                      tr("rad_advice_dust", lang), tr("rad_advice_wind", lang)]
        else:
            lines += ["", tr("rad_advice_title", lang), tr("rad_advice_mushrooms", lang)]
        if any_danger_zone_reached:
            lines += ["", tr("rad_replan", lang)]
        urls = _unique(urls)
        lines += ["", sources_line(urls, lang)]
        if any("OpenStreetMap" in h.zone.get("geometry_note", {}).get("en", "") for h in hits):
            lines += ["", "*" + tr("rad_osm_credit", lang) + "*"]
        primary = all(any(s["kind"] == "primary" for s in h.zone["sources"]) for h in hits)
        return Section("hazards", "\n".join(lines), "tag-backed" if primary else "web-sourced",
                       sources=urls, warnings=warnings,
                       shared={"zones": [h.zone["id"] for h in hits]})
