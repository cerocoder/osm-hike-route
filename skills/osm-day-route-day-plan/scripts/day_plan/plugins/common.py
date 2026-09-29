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


def sources_line(urls: list, lang: str) -> str:
    links = []
    for url in urls:
        host = urllib.parse.urlparse(url).netloc or url
        links.append(f"[{host}]({url})")
    return tr("tr_sources", lang, urls=", ".join(links))
