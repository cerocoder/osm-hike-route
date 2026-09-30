"""Runs the plugins in dependency order with per-plugin fault isolation
(same discipline as place_info.PlaceInfoService and
tile_providers.TileProviderService), then assembles the Markdown file."""
import datetime
from dataclasses import dataclass

from .base import SECTION_ORDER, Section
from .i18n import tr
from .summary import build_summary_section


@dataclass
class PlanResult:
    markdown: str
    sections: list
    failures: list  # [(plugin_id, reason)]


def _ordered(plugins: list) -> list:
    """Topological order; registration order breaks ties. A dependency that
    is not registered is ignored (the dependent handles its absence)."""
    registered = {p.plugin_id for p in plugins}
    done, order, remaining = set(), [], list(plugins)
    while remaining:
        progressed = False
        for plugin in list(remaining):
            deps = [d for d in plugin.depends_on if d in registered]
            if all(d in done for d in deps):
                order.append(plugin)
                done.add(plugin.plugin_id)
                remaining.remove(plugin)
                progressed = True
        if not progressed:
            raise ValueError("dependency cycle among plugins: " + ", ".join(p.plugin_id for p in remaining))
    return order


def _one_line(text: str, limit: int = 200) -> str:
    """Collapse whitespace and truncate, so a traceback or an HTTP error body
    cannot break the Markdown layout."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _validate_registration(plugins: list) -> None:
    seen = set()
    for plugin in plugins:
        if plugin.plugin_id in seen:
            raise ValueError(f"duplicate plugin_id: {plugin.plugin_id}")
        seen.add(plugin.plugin_id)
        if plugin.section_id not in SECTION_ORDER:
            raise ValueError(f"plugin {plugin.plugin_id}: unknown section_id {plugin.section_id!r} "
                             f"(known: {', '.join(SECTION_ORDER)})")


def run_plugins(ctx, plugins: list):
    """Returns (sections_in_registration_order, shared, failures)."""
    _validate_registration(plugins)
    shared, failures, by_id = {}, [], {}
    for plugin in _ordered(plugins):
        deps = {d: shared[d] for d in plugin.depends_on if d in shared}
        try:
            section = plugin.run(ctx, deps)
        except Exception as e:  # noqa: BLE001 — isolate any plugin failure
            reason = _one_line(f"{type(e).__name__}: {e}")
            failures.append((plugin.plugin_id, reason))
            section = Section(plugin.section_id, tr("plugin_failed", ctx.lang, reason=reason), "no-data")
        else:
            shared[plugin.plugin_id] = section.shared
        by_id[plugin.plugin_id] = section
    return [by_id[p.plugin_id] for p in plugins], shared, failures


def _fetched_at(ctx, shared: dict) -> datetime.datetime:
    stamp = (shared.get("weather") or {}).get("fetched_at")
    if stamp is None:
        return ctx.now
    return datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc)


def assemble_markdown(ctx, sections: list, summary: Section, fetched_at: datetime.datetime,
                      utc_offset_seconds: float | None = None, plugins: list = ()) -> str:
    lang = ctx.lang
    stamp = fetched_at.strftime("%Y-%m-%d %H:%M")
    local = ""
    if utc_offset_seconds is not None:
        local_time = fetched_at + datetime.timedelta(seconds=utc_offset_seconds)
        local = tr("meta_local", lang, local=local_time.strftime("%Y-%m-%d %H:%M"))
    mode = tr("mode_bike" if ctx.mode == "bike" else "mode_walk", lang)
    meta = tr("meta", lang, fetched=stamp + " UTC" + local, mode=mode)
    if ctx.departure:
        meta += tr("meta_from", lang, departure=ctx.departure)
    header = "\n".join([
        f"# {ctx.route_name} — {ctx.date_iso}",
        f"<!-- day-plan fetched_at: {fetched_at.strftime('%Y-%m-%dT%H:%M:%SZ')} -->",
        f"*{meta}*",
    ] + ([f"<!-- plugins: {', '.join(f'{p.plugin_id} {p.version}' for p in plugins)} -->"] if plugins else []))
    parts = [
        header,
        f"## {tr('h_summary', lang)}\n\n{summary.markdown}",
    ]
    for section_id in SECTION_ORDER:
        if section_id == "summary":
            continue
        group = [s for s in sections if s.section_id == section_id]
        if not group:
            continue
        body = []
        for s in group:
            if len(group) > 1 and s.title:
                body.append(f"### {s.title}\n\n{s.markdown}")
            else:
                body.append(s.markdown)
        parts.append(f"## {tr('h_' + section_id, lang)}\n\n" + "\n\n".join(body))
    for s in sections:  # never drop a section whose id is not in SECTION_ORDER
        if s.section_id not in SECTION_ORDER:
            parts.append(f"## {s.section_id}\n\n{s.markdown}")
    return "\n\n".join(parts) + "\n"


def build_plan(ctx, plugins: list) -> PlanResult:
    sections, shared, failures = run_plugins(ctx, plugins)
    try:
        summary = build_summary_section(sections, ctx.lang)
    except Exception as e:  # noqa: BLE001 — the summary is outside run_plugins' isolation
        failures.append(("summary", _one_line(f"{type(e).__name__}: {e}")))
        summary = Section("summary", "- " + tr("summary_unavailable", ctx.lang), "derived")
    markdown = assemble_markdown(ctx, sections, summary, _fetched_at(ctx, shared),
                                 (shared.get("weather") or {}).get("utc_offset_seconds"), plugins)
    return PlanResult(markdown=markdown, sections=sections, failures=failures)
