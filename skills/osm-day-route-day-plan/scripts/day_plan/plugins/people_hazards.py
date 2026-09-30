"""The "People and access" hazard: only what Claude recorded with a source
(`record_fact.py --plugin people_hazards`): access restrictions and permit
zones for border areas, conflict-zone or travel-advisory notes for the
region, known problem sections. No generalisations about populations and
nothing without a source (the fact loader drops a source-less entry).

Deviation from the spec, which says "no data" without a source: with no fact
the part is left out, otherwise every plan would list "People and access"
as missing data although nothing is missing that a script could supply."""
from ..base import PlanWarning, Section, SectionPlugin
from ..facts import lookup
from ..i18n import tr
from .common import sources_line


class PeopleHazardsPlugin(SectionPlugin):
    plugin_id = "people_hazards"
    section_id = "hazards"
    title_key = "hz_people"

    def run(self, ctx, shared: dict) -> Section:
        fact = lookup(ctx.facts, ctx.date_iso, "people_hazards")
        if not fact or not fact["markdown"]:
            return Section("hazards", "", "derived", omit=True)
        lines = [tr("ppl_web_title", ctx.lang), "", fact["markdown"], "", sources_line(fact["sources"], ctx.lang)]
        warnings = [PlanWarning(w["severity"], w["text"]) for w in fact.get("warnings", [])]
        return Section("hazards", "\n".join(lines), "web-sourced", sources=list(fact["sources"]), warnings=warnings)
