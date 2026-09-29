import datetime

import pytest

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.plugins.light import LightPlugin
from day_plan.plugins.weather import WeatherPlugin
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", depends_on=(), markdown="body", warnings=(),
                 confidence="derived", title=None, raises=False, shared=None):
        self.plugin_id, self.section_id, self.depends_on = plugin_id, section_id, tuple(depends_on)
        self._args = dict(markdown=markdown, warnings=list(warnings), confidence=confidence,
                          title=title, shared=shared or {})
        self._raises = raises
        self.seen_shared = None

    def run(self, ctx, shared):
        self.seen_shared = shared
        if self._raises:
            raise RuntimeError("boom")
        return Section(self.section_id, **self._args)


def _ctx(make_route, fixed_now, lang="en", departure=None, http=None, weather_response=None):
    http = http or (lambda url: weather_response())
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, departure=departure,
                         http=http, now=fixed_now)


def test_dependency_order_and_shared_data_are_passed(make_route, fixed_now):
    a = Stub("a", shared={"x": 1})
    b = Stub("b", depends_on=("a",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    run_plugins(ctx, [b, a])
    assert b.seen_shared == {"a": {"x": 1}}


def test_failing_plugin_becomes_no_data_and_others_still_run(make_route, fixed_now):
    good, bad = Stub("good"), Stub("bad", raises=True)
    dependent = Stub("dep", depends_on=("bad",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections, shared, failures = run_plugins(ctx, [bad, good, dependent])
    assert [s.confidence for s in sections] == ["no-data", "derived", "derived"]
    assert failures == [("bad", "RuntimeError: boom")]
    assert dependent.seen_shared == {}   # failed dependency is simply absent


def test_unregistered_dependency_is_ignored(make_route, fixed_now):
    p = Stub("p", depends_on=("missing",))
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections, _, failures = run_plugins(ctx, [p])
    assert failures == [] and len(sections) == 1


def test_dependency_cycle_raises(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    with pytest.raises(ValueError):
        run_plugins(ctx, [Stub("a", depends_on=("b",)), Stub("b", depends_on=("a",))])


def test_summary_sorts_by_severity_and_caps_at_five():
    warnings = [PlanWarning("info", f"i{i}") for i in range(4)] + [
        PlanWarning("danger", "D"), PlanWarning("caution", "C")]
    summary = build_summary_section([Section("hazards", "x", "derived", warnings=warnings)], "en")
    lines = summary.markdown.splitlines()
    assert len(lines) == 5
    assert lines[0] == "- **Danger:** D"
    assert lines[1] == "- **Caution:** C"


def test_summary_without_warnings_says_so_and_lists_no_data_sections():
    sections = [Section("light", "x", "derived"), Section("weather", "x", "no-data")]
    summary = build_summary_section(sections, "en")
    assert "No warnings for this date." in summary.markdown
    assert "Sections without data: Weather by hour." in summary.markdown


def test_summary_is_localized():
    summary = build_summary_section([Section("light", "x", "derived",
                                             warnings=[PlanWarning("danger", "т")])], "ru")
    assert summary.markdown == "- **Опасно:** т"


def test_full_plan_has_fixed_section_order_and_metadata(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, departure="Waterloo", weather_response=weather_response)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    lines = result.markdown.splitlines()
    assert lines[0] == "# Test route — 2026-06-21"
    assert lines[1] == "<!-- day-plan fetched_at: 2026-06-20T12:00:00Z -->"
    assert lines[2] == ("*Data fetched 2026-06-20 12:00 UTC (2026-06-20 13:00 local)"
                        " · Mode: walking · From: Waterloo*")
    assert lines[3] == "<!-- plugins: weather 1, light 1 -->"
    headings = [l for l in lines if l.startswith("## ")]
    assert headings == ["## Summary", "## Daylight", "## Weather by hour"]
    assert result.failures == []


def test_group_with_several_plugins_gets_subheadings(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, http=lambda u: {})
    sections = [Section("hazards", "one", title="Ticks"), Section("hazards", "two", title="Fire")]
    text = assemble_markdown(ctx, sections, Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## Hazards\n\n### Ticks\n\none\n\n### Fire\n\ntwo" in text


def test_metadata_uses_weather_fetch_time_not_run_time(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, weather_response=weather_response)
    stamp = datetime.datetime(2026, 6, 20, 7, 30, tzinfo=datetime.timezone.utc).timestamp()
    stub = Stub("weather", section_id="weather", shared={"fetched_at": stamp})
    result = build_plan(ctx, [stub])
    assert "fetched_at: 2026-06-20T07:30:00Z" in result.markdown


def test_russian_plan_headings(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, lang="ru", weather_response=weather_response)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    assert "## Главное на день" in result.markdown
    assert "## Световой день" in result.markdown
    assert "## Погода по часам" in result.markdown
    assert "Режим: пешком" in result.markdown


def test_weather_outage_does_not_break_the_plan(make_route, fixed_now):
    from day_plan.http import HttpError

    def http(url):
        raise HttpError("offline")

    ctx = _ctx(make_route, fixed_now, http=http)
    result = build_plan(ctx, [WeatherPlugin(), LightPlugin()])
    assert "estimated from longitude" in result.markdown       # light still works
    assert "Sections without data: Weather by hour." in result.markdown


def _meta_line(make_route, fixed_now, fetched, shared, lang="en"):
    ctx = _ctx(make_route, fixed_now, lang=lang)
    stub = Stub("weather", section_id="weather", shared=dict(shared, fetched_at=fetched.timestamp()))
    return build_plan(ctx, [stub]).markdown.splitlines()


def test_metadata_shows_local_time_when_offset_known(make_route, fixed_now):
    fetched = datetime.datetime(2026, 9, 29, 22, 31, tzinfo=datetime.timezone.utc)
    lines = _meta_line(make_route, fixed_now, fetched, {"utc_offset_seconds": 10800})
    assert lines[2] == "*Data fetched 2026-09-29 22:31 UTC (2026-09-30 01:31 local) · Mode: walking*"


def test_metadata_is_utc_only_without_offset(make_route, fixed_now):
    fetched = datetime.datetime(2026, 9, 29, 22, 31, tzinfo=datetime.timezone.utc)
    lines = _meta_line(make_route, fixed_now, fetched, {"utc_offset_seconds": None})
    assert lines[2] == "*Data fetched 2026-09-29 22:31 UTC · Mode: walking*"
    assert "local" not in lines[2]


def test_metadata_is_neutral_and_localized_in_all_languages():
    from day_plan.i18n import LANGS, STRINGS, tr
    assert tr("meta", "en", fetched="X", mode="m").startswith("Data fetched X")
    assert tr("meta", "ru", fetched="X", mode="m").startswith("Данные получены X")
    for lang in LANGS:
        assert "orecast" not in STRINGS[lang]["meta"] and "прогноз" not in STRINGS[lang]["meta"].lower()
        assert "{local}" in STRINGS[lang]["meta_local"]


def test_plugin_versions_comment_follows_metadata_line(make_route, fixed_now, weather_response):
    ctx = _ctx(make_route, fixed_now, weather_response=weather_response)
    lines = build_plan(ctx, [WeatherPlugin(), LightPlugin()]).markdown.splitlines()
    assert lines[3] == "<!-- plugins: weather 1, light 1 -->"
    assert lines[4] == ""
