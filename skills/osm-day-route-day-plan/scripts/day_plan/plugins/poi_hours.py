"""The "Points of interest" section: are the route's points of interest open
on the date (their OSM `opening_hours`), their notes from the route archive,
and — when Claude recorded them from the web — opening days and special
features (facts.json, plugin id "poi_hours"). Confidence like the transit
section: tag-backed for OSM hours, web-sourced once a facts entry is used,
no-data when there is neither."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import resolve_day_type
from ..facts import lookup
from ..i18n import tr
from .common import cell, hours_on_date, sources_line, sun_from_light

NOTE_LIMIT = 160


class PoiHoursPlugin(SectionPlugin):
    plugin_id = "poi_hours"
    section_id = "pois"
    depends_on = ("light",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        day = resolve_day_type(ctx)
        sun = sun_from_light(shared.get("light"))
        lines, warnings, has_osm, without_hours = [], [], False, []

        if not ctx.interest_points:
            lines.append("- " + tr("poi_none", lang))
        else:
            header = [tr(k, lang) for k in ("poi_col_point", "poi_col_type", "poi_col_hours", "poi_col_note")]
            rows = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            for point in ctx.interest_points:
                if not point.opening_hours and not point.note:
                    without_hours.append(point.name)
                    continue
                text, result = hours_on_date(point.opening_hours, ctx, day.holiday, sun)
                if result is None and not point.opening_hours:
                    without_hours.append(point.name)
                has_osm = has_osm or result is not None
                if result is not None and result.status == "closed" and not result.uncertain:
                    warnings.append(PlanWarning("caution", tr("poi_warn_closed", lang, name=point.name)))
                note = point.note or ""
                if len(note) > NOTE_LIMIT:
                    note = note[: NOTE_LIMIT - 1] + "…"
                rows.append(f"| {cell(point.name)} | {cell(point.type)} | {text} | {cell(note)} |")
            if len(rows) > 2:
                lines += rows
            if without_hours:
                lines += ["", "- " + tr("poi_no_hours", lang, names=", ".join(cell(n) for n in without_hours))]

        fact = lookup(ctx.facts, ctx.date_iso, "poi_hours")
        if fact:
            lines += ["", tr("poi_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))

        confidence = "web-sourced" if fact else "tag-backed" if has_osm else "no-data"
        sources = list(fact["sources"]) if fact else []
        return Section("pois", "\n".join(lines), confidence, sources=sources, warnings=warnings)
