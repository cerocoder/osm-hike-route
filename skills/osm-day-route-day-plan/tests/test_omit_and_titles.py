import datetime

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", markdown="body", confidence="derived", omit=False,
                 title_key=None, title=None, raises=False, warnings=()):
        self.plugin_id, self.section_id, self.title_key = plugin_id, section_id, title_key
        self._section = dict(markdown=markdown, confidence=confidence, omit=omit, title=title, warnings=list(warnings))
        self._raises = raises

    def run(self, ctx, shared):
        if self._raises:
            raise RuntimeError("boom")
        return Section(self.section_id, **self._section)


def _ctx(make_route, fixed_now, lang="en"):
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, http=lambda u: {}, now=fixed_now)


def test_an_omitted_section_is_left_out_of_the_file(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    shown = Section("hazards", "visible text", "derived", title="Visible")
    hidden = Section("hazards", "SECRET should not appear", "derived", omit=True, title="Hidden")
    text = assemble_markdown(ctx, [hidden, shown], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "visible text" in text and "SECRET" not in text
    assert "### Visible" not in text          # a group with a single visible section has no sub-heading


def test_a_group_of_only_omitted_sections_has_no_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    only_hidden = Section("hazards", "x", "no-data", omit=True)
    text = assemble_markdown(ctx, [only_hidden], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## Hazards" not in text


def test_an_omitted_no_data_section_is_not_listed_as_missing_in_the_summary():
    summary = build_summary_section([Section("hazards", "", "no-data", omit=True, title="Mountain hazards"),
                                     Section("weather", "", "no-data")], "en")
    assert "Weather by hour" in summary.markdown and "Mountain hazards" not in summary.markdown


def test_warnings_of_an_omitted_section_still_reach_the_summary():
    section = Section("hazards", "", "derived", omit=True, warnings=[PlanWarning("danger", "kept")])
    assert "kept" in build_summary_section([section], "en").markdown


def test_the_service_fills_the_sub_heading_from_the_plugin_title_key(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    a = Stub("a", title_key="hz_fire", markdown="fire text")
    b = Stub("b", title_key="hz_mountain", markdown="mountain text")
    result = build_plan(ctx, [a, b])
    assert "### Fire danger\n\nfire text" in result.markdown
    assert "### Mountain hazards\n\nmountain text" in result.markdown


def test_a_title_set_by_the_plugin_wins_and_the_failed_plugin_keeps_its_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    own = Stub("own", title_key="hz_fire", title="My own title")
    failing = Stub("bad", title_key="hz_air", raises=True)
    sections, _, failures = run_plugins(ctx, [own, failing])
    assert sections[0].title == "My own title"
    assert sections[1].title == "Air: pollen and pollution" and sections[1].confidence == "no-data"
    assert failures[0][0] == "bad"


def test_titles_are_localized(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now, lang="ru")
    sections, _, _ = run_plugins(ctx, [Stub("a", title_key="hz_bio"), Stub("b", title_key="hz_mountain")])
    assert [s.title for s in sections] == ["Клещи и кровососущие насекомые", "Горные опасности"]
