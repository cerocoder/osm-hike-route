"""The "Mobile coverage" section. Deliberately modest: OpenStreetMap records
only a share of the masts (a few hundred metres of forest road may have no
mast recorded in a place that has good signal, and the reverse), so the plugin
counts the masts recorded near the route, says plainly that this is not a
coverage measurement, gives the practical advice and links to the
coverage maps that can be opened from a browser (nPerf, OpenCellID). It never
warns above `info`.

Deviation from the spec, which asked for a terrain-aware weak-signal model:
without measured data such a model would be a guess presented as an estimate."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import country_code
from ..i18n import tr
from ..osm_features import MARGIN_KM, near

NPERF_GLOBAL = "https://www.nperf.com/en/map"
NPERF_COUNTRY = "https://www.nperf.com/en/map/{code}/-/-/signal"


def nperf_url(ctx) -> str:
    code = country_code(ctx)
    return NPERF_COUNTRY.format(code=code.upper()) if code and code.isalpha() and len(code) == 2 else NPERF_GLOBAL


class CellCoveragePlugin(SectionPlugin):
    plugin_id = "cell_coverage"
    section_id = "cell_coverage"
    depends_on = ("osm_features",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        osm = shared.get("osm_features") or {}
        tail = [tr("cell_caveat", lang), tr("cell_advice", lang), tr("cell_maps", lang, nperf=nperf_url(ctx))]
        if osm.get("error") or osm.get("samples") is None:
            reason = osm.get("error") or "no data"
            return Section("cell_coverage", "\n".join([tr("cell_osm_unavailable", lang, reason=reason)] + tail),
                           "no-data")
        masts = near(osm.get("features", []), osm["samples"], "mast", MARGIN_KM * 1000.0)
        km = f"{MARGIN_KM:g}"
        warnings = []
        if masts:
            nearest = tr("cell_nearest", lang, dist=f"{masts[0][1] / 1000.0:.1f}")
            lines = [tr("cell_masts", lang, km=km, count=len(masts), nearest=nearest)]
        else:
            lines = [tr("cell_none", lang, km=km)]
            warnings.append(PlanWarning("info", tr("cell_warn_none", lang)))
        return Section("cell_coverage", "\n".join(lines + tail), "tag-backed", warnings=warnings)
