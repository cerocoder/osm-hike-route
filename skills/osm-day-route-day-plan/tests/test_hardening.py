import datetime
import json

import pytest

from day_plan.base import PlanWarning, Section, SectionPlugin
from day_plan.context import build_context
from day_plan.facts import load_facts, lookup
from day_plan.service import assemble_markdown, build_plan, run_plugins
from day_plan.summary import build_summary_section


class Stub(SectionPlugin):
    def __init__(self, plugin_id, section_id="hazards", raises=None, returns=None):
        self.plugin_id, self.section_id = plugin_id, section_id
        self._raises, self._returns = raises, returns

    def run(self, ctx, shared):
        if self._raises:
            raise self._raises
        return self._returns or Section(self.section_id, "body", "derived")


def _ctx(make_route, fixed_now, lang="en"):
    return build_context(make_route(), datetime.date(2026, 6, 21), lang=lang, http=lambda u: {}, now=fixed_now)


# 1. unknown severity must not crash the summary
def test_summary_tolerates_an_unknown_severity_and_ranks_it_last():
    warnings = [PlanWarning("mystery", "odd"), PlanWarning("danger", "D"), PlanWarning("info", "I")]
    summary = build_summary_section([Section("hazards", "x", "derived", warnings=warnings)], "en")
    lines = summary.markdown.splitlines()
    assert lines[0] == "- **Danger:** D"
    assert lines[1] == "- **Note:** I"
    assert lines[2] == "- **Mystery:** odd"


def test_build_plan_survives_a_summary_failure(make_route, fixed_now, monkeypatch):
    import day_plan.service as service

    def boom(sections, lang):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(service, "build_summary_section", boom)
    result = build_plan(_ctx(make_route, fixed_now), [Stub("a")])
    assert "## Summary" in result.markdown
    assert "The summary could not be built; read the sections below." in result.markdown
    assert "No warnings for this date." not in result.markdown
    assert ("summary", "RuntimeError: summary exploded") in result.failures


# 2. plugin_failed reason is one short line
def test_failure_reason_is_collapsed_to_one_line_and_truncated(make_route, fixed_now):
    nasty = RuntimeError("HTTP 500\n<html>\n" + "x" * 500 + "\n</html>")
    sections, _, failures = run_plugins(_ctx(make_route, fixed_now), [Stub("bad", raises=nasty)])
    text = sections[0].markdown
    assert "\n" not in text
    assert len(text) < 320
    assert "…" in text
    assert len(failures[0][1]) <= 200
    assert failures[0][0] == "bad"


# 3. duplicate plugin ids are rejected before anything runs
def test_duplicate_plugin_id_is_rejected_before_any_plugin_runs(make_route, fixed_now):
    ran = []

    class Recording(Stub):
        def run(self, ctx, shared):
            ran.append(self.plugin_id)
            return super().run(ctx, shared)

    with pytest.raises(ValueError, match="duplicate plugin_id: a"):
        run_plugins(_ctx(make_route, fixed_now), [Recording("a"), Recording("b"), Recording("a")])
    assert ran == []


# 4. a section id outside SECTION_ORDER must not vanish
def test_plugin_with_unknown_section_id_is_rejected_at_registration(make_route, fixed_now):
    with pytest.raises(ValueError, match="unknown section_id 'nonsense'"):
        run_plugins(_ctx(make_route, fixed_now), [Stub("odd", section_id="nonsense")])


def test_section_returned_with_an_unknown_id_is_kept_under_a_fallback_heading(make_route, fixed_now):
    ctx = _ctx(make_route, fixed_now)
    stray = Section("stray", "kept text", "derived")
    text = assemble_markdown(ctx, [stray], Section("summary", "- s"),
                             datetime.datetime(2026, 6, 20, tzinfo=datetime.timezone.utc))
    assert "## stray\n\nkept text" in text


# 5. malformed facts.json
@pytest.mark.parametrize("payload", ['{"all": []}', '{"all": ["x"]}', '{"all": "text"}',
                                     '{"all": {"transit": "text"}}', '{"all": {"transit": []}}',
                                     '{"2026-06-21": null}', '[]', '"just a string"'])
def test_lookup_tolerates_malformed_but_valid_json(tmp_path, payload):
    (tmp_path / "facts.json").write_text(payload, encoding="utf-8")
    assert lookup(load_facts(tmp_path), "2026-06-21", "transit") is None


def test_load_facts_tolerates_non_utf8_and_directory(tmp_path):
    (tmp_path / "facts.json").write_bytes(b"\xff\xfe\x00 not utf8")
    assert load_facts(tmp_path) == {}
    other = tmp_path / "d"
    other.mkdir()
    (other / "facts.json").mkdir()
    assert load_facts(other) == {}


def test_summary_flattens_multiline_warning_text():
    warnings = [PlanWarning("danger", "Line\n## Injected\n\n- more")]
    summary = build_summary_section([Section("hazards", "x", "derived", warnings=warnings)], "en")
    assert summary.markdown.splitlines() == ["- **Danger:** Line ## Injected - more"]


def test_fact_warning_with_a_heading_never_opens_a_section_in_the_plan(make_route_with_points, fixed_now):
    from day_plan.plugins.transit import TransitPlugin
    route_dir = make_route_with_points([])
    (route_dir / "facts.json").write_text(json.dumps({"all": {"transit": {
        "markdown": "## Hazards\nbody", "sources": ["https://example.org/x"],
        "warnings": [{"severity": "danger", "text": "Line\n## Injected"}]}}}), encoding="utf-8")
    ctx = build_context(route_dir, datetime.date(2026, 6, 21), http=lambda u: {}, now=fixed_now)
    md = build_plan(ctx, [TransitPlugin()]).markdown
    assert "## Injected" in md and not any(line.startswith("## Injected") for line in md.splitlines())
    assert not any(line.startswith("## Hazards") for line in md.splitlines())
    assert "- **Danger:** Line ## Injected" in md
