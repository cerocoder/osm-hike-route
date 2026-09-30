"""What kind of day is the plan for: weekday, weekend, public holiday.

Sources, in order: a `calendar` entry in facts.json with a `day_type` (Claude
looked it up on the web — the way to cover transferred days off; the free
list is incomplete for Russia: it misses 8 January and the transferred days
off, for example 9 March and 11 May 2026; a calendar fact is per date, an
"all" entry is ignored); otherwise the route's country from
Nominatim (cached for good — a country does not move; one request per route)
and the public-holiday list from Nager.Date (keyless, cached 30 days). When
neither is available the holiday status is None (unknown), never assumed."""
import urllib.parse
from dataclasses import dataclass, field

from .facts import lookup
from .http import HttpError
from .i18n import tr
from .plugins.common import md_link

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays"
HOLIDAY_LIST_TTL_S = 30 * 86400


@dataclass
class DayType:
    weekday: int                       # Monday = 0
    is_weekend: bool
    holiday: bool | None               # None = unknown
    holiday_name: str | None = None
    source: str = "none"               # "facts" | "nager" | "none"
    country: str | None = None         # upper-case ISO 3166-1 alpha-2
    note_key: str | None = None        # i18n key explaining an unknown holiday status
    regional_name: str | None = None
    sources: list = field(default_factory=list)   # URLs when source == "facts"


def country_code(ctx) -> str | None:
    lat, lon = ctx.centroid
    key = f"country|{lat:.2f}|{lon:.2f}"
    cached = ctx.cache.get_entry(key)          # never expires
    if cached is not None:
        return cached[0] or None
    query = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.4f}", "lon": f"{lon:.4f}",
                                    "zoom": 3, "addressdetails": 1})
    try:
        data = ctx.http(f"{NOMINATIM_URL}?{query}")
    except HttpError:
        return None                            # transient: not cached
    code = ((data or {}).get("address") or {}).get("country_code") if isinstance(data, dict) else None
    code = code.upper() if isinstance(code, str) and len(code) == 2 else ""
    ctx.cache.put(key, code)
    return code or None


def _holidays(ctx, code: str) -> list | None:
    key = f"nager|{code}|{ctx.date.year}"
    cached = ctx.cache.get_entry(key, HOLIDAY_LIST_TTL_S)
    if cached is not None:
        return cached[0]
    try:
        data = ctx.http(f"{NAGER_URL}/{ctx.date.year}/{code}")
    except HttpError:
        return None
    if not isinstance(data, list):
        return None
    ctx.cache.put(key, data)
    return data


def resolve_day_type(ctx) -> DayType:
    weekday = ctx.date.weekday()
    weekend = weekday >= 5
    fact = lookup(ctx.facts, ctx.date_iso, "calendar", allow_all=False)
    if fact and fact.get("day_type"):
        kind = fact["day_type"]
        is_weekend_val = True if kind == "weekend" else False if kind == "workday" else weekend
        holiday_val = True if kind == "holiday" else False if kind == "workday" else None
        return DayType(weekday, is_weekend_val, holiday_val, source="facts", sources=fact["sources"])
    code = country_code(ctx)
    if code is None:
        return DayType(weekday, weekend, None, note_key="cal_no_country")
    holidays = _holidays(ctx, code)
    if holidays is None:
        return DayType(weekday, weekend, None, country=code, note_key="cal_list_unavailable")
    today = [h for h in holidays if isinstance(h, dict) and h.get("date") == ctx.date_iso]
    for h in today:
        if h.get("global", True):
            return DayType(weekday, weekend, True, holiday_name=h.get("localName") or h.get("name"),
                           source="nager", country=code)
    if today:
        h = today[0]
        return DayType(weekday, weekend, None, source="nager", country=code,
                       regional_name=h.get("localName") or h.get("name"))
    return DayType(weekday, weekend, False, source="nager", country=code)


def describe(day: DayType, ctx) -> str:
    """One line for the plan: 'Date: Saturday 2026-06-27 — weekend; not a public holiday (Nager.Date, ES)'."""
    lang = ctx.lang
    if day.holiday is True:
        holiday = (tr("cal_holiday_yes", lang, name=day.holiday_name) if day.holiday_name
                   else tr("cal_holiday_yes_noname", lang))
    elif day.holiday is False:
        holiday = tr("cal_holiday_no", lang)
    elif day.regional_name:
        holiday = tr("cal_holiday_regional", lang, name=day.regional_name)
    else:
        holiday = tr("cal_holiday_unknown", lang)
    if day.source == "nager":
        source = tr("cal_source_nager", lang, country=day.country)
    elif day.source == "facts":
        source = tr("cal_source_facts", lang, urls=", ".join(md_link(u) for u in day.sources))
    else:
        source = "(" + tr(day.note_key, lang, country=day.country or "?") + ")" if day.note_key else ""
    if day.is_weekend:
        kind = tr("cal_weekend", lang)
    else:
        kind = tr("cal_dayoff" if day.holiday is True else "cal_workday", lang)
    line = tr("cal_line", lang, weekday=tr("weekday_names", lang)[day.weekday], date=ctx.date_iso,
              kind=kind, holiday=holiday, source=source).rstrip()
    if day.source == "nager":
        line += " *" + tr("cal_caveat", lang) + "*"
    return line
