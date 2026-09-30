"""Helpers shared by the transit and poi_hours plugins."""
import urllib.parse

from ..i18n import tr
from ..opening_hours import OpeningResult, evaluate, format_intervals


def cell(text) -> str:
    """Safe content for a Markdown table cell."""
    return " ".join(str(text).replace("|", "/").split())


def sun_from_light(light_shared: dict | None) -> dict | None:
    """{'sunrise': minute, 'sunset': minute} from the light plugin's shared data."""
    if not light_shared or light_shared.get("sunrise_local_min") is None:
        return None
    return {"sunrise": int(light_shared["sunrise_local_min"]), "sunset": int(light_shared["sunset_local_min"])}


def finish_minute(ctx) -> int | None:
    """Estimated end of the route, in minutes after midnight, when both a start time and a duration are known."""
    if ctx.start_time is None or not ctx.duration_hours:
        return None
    return ctx.start_time.hour * 60 + ctx.start_time.minute + int(round(ctx.duration_hours * 60))


def hours_on_date(spec: str | None, ctx, holiday, sun) -> tuple[str, OpeningResult | None]:
    """(text for a table cell, the evaluation or None when OSM has no hours)."""
    lang = ctx.lang
    if not spec:
        return tr("tr_hours_missing", lang), None
    result = evaluate(spec, ctx.date, holiday, sun)
    if result.status == "open_all_day":
        text = tr("tr_hours_all_day", lang)
    elif result.status == "open_hours":
        text = format_intervals(result.intervals)
    elif result.status == "closed":
        text = tr("tr_hours_closed", lang)
    else:
        text = tr("tr_hours_unknown", lang, raw=spec)
    if result.uncertain:
        text += tr("tr_hours_uncertain", lang)
    return cell(text), result


def md_link(url: str) -> str:
    """`[host](url)`; parentheses in the URL are percent-encoded so they cannot cut the link."""
    host = urllib.parse.urlparse(url).netloc or url
    return f"[{host}]({url.replace('(', '%28').replace(')', '%29')})"


def sources_line(urls: list, lang: str) -> str:
    return tr("tr_sources", lang, urls=", ".join(md_link(url) for url in urls))


def hour_ranges(hours: list) -> str:
    """[5, 6, 7, 19, 20] -> '05:00–08:00, 19:00–21:00'."""
    ranges, start, prev = [], None, None
    for h in sorted(set(hours)):
        if start is None:
            start = prev = h
        elif h == prev + 1:
            prev = h
        else:
            ranges.append((start, prev))
            start = prev = h
    if start is not None:
        ranges.append((start, prev))
    return ", ".join(f"{a:02d}:00–{b + 1:02d}:00" for a, b in ranges)
