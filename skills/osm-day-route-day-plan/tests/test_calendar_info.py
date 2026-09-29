import datetime
import json

import pytest

from day_plan.calendar_info import DayType, country_code, describe, resolve_day_type
from day_plan.context import build_context
from day_plan.http import HttpError

MADRID_ROUTE = ((-3.75, 40.42, 600.0), (-3.74, 40.43, 640.0))
HOLIDAYS_ES = [
    {"date": "2026-06-24", "localName": "San Juan", "name": "St John", "global": False, "counties": ["ES-CT"]},
    {"date": "2026-08-15", "localName": "Asunción", "name": "Assumption", "global": True, "counties": None},
]


class FakeWeb:
    def __init__(self, country="es", holidays=HOLIDAYS_ES):
        self.calls, self.country, self.holidays = [], country, holidays

    def __call__(self, url):
        self.calls.append(url)
        if "nominatim" in url:
            if self.country is HttpError:
                raise HttpError("down")
            return {"address": {"country_code": self.country}} if self.country else {"error": "Unable to geocode"}
        if "date.nager.at" in url:
            if self.holidays is HttpError:
                raise HttpError("404")
            return self.holidays
        raise AssertionError(url)


def _ctx(make_route, fixed_now, web, date, lang="en", facts=None, folder="route"):
    route_dir = make_route(coords=MADRID_ROUTE, folder=folder)
    if facts is not None:
        (route_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return build_context(route_dir, date, lang=lang, http=web, now=fixed_now)


def test_saturday_that_is_not_a_holiday(make_route, fixed_now):
    web = FakeWeb()
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 6, 27))
    day = resolve_day_type(ctx)
    assert (day.weekday, day.is_weekend, day.holiday, day.source, day.country) == (5, True, False, "nager", "ES")
    assert describe(day, ctx).startswith("Date: Saturday 2026-06-27 — weekend; not a public holiday (Nager.Date, ES)")


def test_global_holiday_on_a_weekday(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 8, 15))   # a Saturday in 2026, still a holiday
    day = resolve_day_type(ctx)
    assert day.holiday is True and day.holiday_name == "Asunción"
    assert "public holiday: Asunción" in describe(day, ctx)


def test_regional_holiday_is_reported_as_possible_not_as_certain(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 24))
    day = resolve_day_type(ctx)
    assert day.holiday is None and day.regional_name == "San Juan"
    assert "possible regional holiday: San Juan" in describe(day, ctx)


def test_country_and_holiday_list_are_cached_between_runs(make_route, fixed_now):
    web = FakeWeb()
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 6, 27))
    resolve_day_type(ctx)
    resolve_day_type(ctx)
    assert sum("nominatim" in u for u in web.calls) == 1
    assert sum("nager" in u for u in web.calls) == 1
    assert "zoom=3" in web.calls[0]


def test_country_lookup_failure_is_not_cached_but_no_country_is(make_route, fixed_now):
    failing = FakeWeb(country=HttpError)
    ctx = _ctx(make_route, fixed_now, failing, datetime.date(2026, 6, 27))
    assert country_code(ctx) is None and country_code(ctx) is None
    assert sum("nominatim" in u for u in failing.calls) == 2     # a transient failure is retried
    ocean = FakeWeb(country="")
    ctx2 = _ctx(make_route, fixed_now, ocean, datetime.date(2026, 6, 27), folder="ocean")
    assert country_code(ctx2) is None and country_code(ctx2) is None
    assert sum("nominatim" in u for u in ocean.calls) == 1        # a definite "no country" is remembered


def test_unknown_when_the_country_or_the_list_is_unavailable(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(country=HttpError), datetime.date(2026, 6, 27))
    day = resolve_day_type(ctx)
    assert day.holiday is None and day.note_key == "cal_no_country"
    assert "public-holiday status unknown (the country of the route could not be determined)" in describe(day, ctx)
    ctx2 = _ctx(make_route, fixed_now, FakeWeb(holidays=HttpError), datetime.date(2026, 6, 27), folder="nolist")
    day2 = resolve_day_type(ctx2)
    assert day2.holiday is None and day2.country == "ES" and day2.note_key == "cal_list_unavailable"


def test_a_web_sourced_calendar_fact_overrides_the_list(make_route, fixed_now):
    facts = {"2026-05-11": {"calendar": {"day_type": "holiday", "sources": ["https://consultant.ru/x"]}}}
    web = FakeWeb(country="ru", holidays=[])
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 5, 11), facts=facts)
    day = resolve_day_type(ctx)
    assert day.holiday is True and day.source == "facts" and day.sources == ["https://consultant.ru/x"]
    assert web.calls == []                       # no network needed when Claude recorded the day type
    assert "(web-sourced)" in describe(day, ctx)


def test_working_saturday_fact(make_route, fixed_now):
    facts = {"all": {"calendar": {"day_type": "workday", "sources": ["https://consultant.ru/x"]}}}
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), facts=facts)
    day = resolve_day_type(ctx)
    assert day.is_weekend is False and day.holiday is False
    assert "not a public holiday" in describe(day, ctx)


def test_weekend_fact_does_not_claim_the_day_is_not_a_public_holiday(make_route, fixed_now):
    facts = {"2026-06-27": {"calendar": {"day_type": "weekend", "sources": ["https://consultant.ru/x"]}}}
    web = FakeWeb()
    ctx = _ctx(make_route, fixed_now, web, datetime.date(2026, 6, 27), facts=facts)
    day = resolve_day_type(ctx)
    assert day.holiday is None and day.is_weekend is True and day.source == "facts"
    assert web.calls == []                       # no network calls for a fact
    text = describe(day, ctx)
    assert "public-holiday status unknown" in text
    assert "(web-sourced)" in text
    assert "not a public holiday" not in text


def test_a_calendar_fact_without_sources_is_ignored(make_route, fixed_now):
    facts = {"2026-06-27": {"calendar": {"day_type": "holiday"}}}
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), facts=facts)
    assert resolve_day_type(ctx).source == "nager"


def test_russian_line_and_caveat(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, FakeWeb(), datetime.date(2026, 6, 27), lang="ru")
    text = describe(resolve_day_type(ctx), ctx)
    assert text.startswith("Дата: суббота 2026-06-27 — выходной; не государственный праздник (Nager.Date, ES)")
    assert "перенесённые выходные" in text


def test_the_nominatim_request_identifies_the_app(make_route, fixed_now):
    from day_plan.http import USER_AGENT
    assert "osm-day-route-day-plan" in USER_AGENT and "github.com/cerocoder/osm-hike-route" in USER_AGENT
