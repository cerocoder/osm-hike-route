"""The "Getting there" section: the route's access points, their hours on the
date, the public-transport lines serving them (OSM, via Overpass), the kind of
day (weekday/holiday), and — when Claude recorded them from the web — the
timetables and directions from the departure point (facts.json, plugin id
"transit"). Confidence: tag-backed for OSM data, web-sourced as soon as a
facts entry is used; no-data when there is neither."""
from ..base import PlanWarning, Section, SectionPlugin
from ..calendar_info import describe, resolve_day_type
from ..facts import lookup
from ..i18n import tr
from ..opening_hours import evaluate, format_intervals, latest_close
from ..overpass import OverpassError, format_interval, routes_near
from .common import cell, finish_minute, hours_on_date, sources_line, sun_from_light

CLOSING_MARGIN_MIN = 30


def _clock(minute: int) -> str:
    return f"{(minute // 60) % 24:02d}:{minute % 60:02d}"


def _to_minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _return_point(points: list):
    """The access point the person comes back to: the one with role 'end', or
    the only one; None when that is ambiguous (no cross-check is made then)."""
    for point in points:
        if point.role == "end":
            return point
    return points[0] if len(points) == 1 else None


class TransitPlugin(SectionPlugin):
    plugin_id = "transit"
    section_id = "transit"
    depends_on = ("light",)

    def run(self, ctx, shared: dict) -> Section:
        lang = ctx.lang
        day = resolve_day_type(ctx)
        sun = sun_from_light(shared.get("light"))
        finish = finish_minute(ctx)
        lines = ["- " + describe(day, ctx)]
        warnings, has_osm = [], False
        return_point = _return_point(ctx.access_points)

        if not ctx.access_points:
            lines.append("- " + tr("tr_no_access_points", lang))
        else:
            rows = [f"| {tr('tr_col_point', lang)} | {tr('tr_col_role', lang)} | {tr('tr_col_hours', lang)} |",
                    "|---|---|---|"]
            for point in ctx.access_points:
                text, result = hours_on_date(point.opening_hours, ctx, day.holiday, sun)
                has_osm = has_osm or result is not None
                role = tr("tr_role_" + point.role, lang) if point.role in ("start", "end") else tr("tr_role_none", lang)
                rows.append(f"| {cell(point.name)} | {role} | {text} |")
                if (point is return_point and finish is not None and result is not None
                        and result.status == "open_hours"):
                    close = latest_close(result)
                    if close is not None and close < finish:
                        warnings.append(PlanWarning("caution", tr(
                            "tr_warn_closed_before_return", lang, name=point.name, close=_clock(close),
                            finish=_clock(finish))))
            lines += ["", tr("tr_access_points", lang), "", *rows]

            route_rows, failed = [], False
            for point in ctx.access_points:
                try:
                    routes = routes_near(ctx, point.lat, point.lon)
                except OverpassError:
                    failed = True
                    continue
                for r in routes:
                    runs = tr("tr_runs_unknown", lang)
                    if r.opening_hours:
                        res = evaluate(r.opening_hours, ctx.date, day.holiday, sun)
                        if res.status in ("open_hours", "open_all_day"):
                            runs = tr("tr_runs_yes", lang, hours=(tr("tr_hours_all_day", lang)
                                                                  if res.status == "open_all_day"
                                                                  else format_intervals(res.intervals)))
                        elif res.status == "closed":
                            runs = tr("tr_runs_no", lang)
                    direction = f"{r.from_} → {r.to}" if r.from_ and r.to else r.name
                    route_rows.append(
                        f"| {cell(point.name)} | {cell(r.ref or r.name)} | {tr('tr_type_' + r.mode, lang)} | "
                        f"{cell(direction)} | {cell(format_interval(r.interval, lang))} | {cell(runs)} |")
            if route_rows:
                has_osm = True
                header = [tr(k, lang) for k in ("tr_col_point", "tr_col_line", "tr_col_type", "tr_col_direction",
                                                "tr_col_interval", "tr_col_runs")]
                lines += ["", tr("tr_routes_title", lang), "",
                          "| " + " | ".join(header) + " |", "|" + "---|" * len(header), *route_rows]
            else:
                lines += ["", "- " + tr("tr_no_osm_lines", lang)]

        fact = lookup(ctx.facts, ctx.date_iso, "transit")
        if fact:
            lines += ["", tr("tr_web_title", lang), "", fact["markdown"], "", sources_line(fact["sources"], lang)]
            for w in fact.get("warnings", []):
                warnings.append(PlanWarning(w["severity"], w["text"]))
            last_text = fact.get("last_departure_local")
            if last_text and finish is not None:
                last = _to_minutes(last_text)
                if last < 240:          # a departure at 00:30 belongs to the night after this date
                    last += 1440
                if finish > last:
                    warnings.append(PlanWarning("danger", tr("tr_warn_last_departure", lang, last=last_text,
                                                             finish=_clock(finish))))
                elif last - finish < CLOSING_MARGIN_MIN:
                    warnings.append(PlanWarning("caution", tr("tr_warn_last_departure_tight", lang,
                                                              last=last_text, finish=_clock(finish))))
        else:
            lines += ["", "- " + tr("tr_no_web", lang)]

        confidence = "web-sourced" if fact else "tag-backed" if has_osm else "no-data"
        sources = list(fact["sources"]) if fact else []
        return Section("transit", "\n".join(lines), confidence, sources=sources, warnings=warnings)
