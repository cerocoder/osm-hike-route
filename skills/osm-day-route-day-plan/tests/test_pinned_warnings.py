from day_plan.base import PlanWarning, Section
from day_plan.summary import MAX_ITEMS, build_summary_section


def test_the_summary_keeps_a_pinned_danger_in_the_top_items_even_after_many_other_dangers():
    storm = Section("weather", "", "derived", warnings=[PlanWarning("danger", f"Storm {i}") for i in range(MAX_ITEMS + 2)])
    radiation = Section("hazards", "", "tag-backed", warnings=[
        PlanWarning("caution", "Bryansk caution", pinned=True), PlanWarning("danger", "Zone danger", pinned=True)])
    summary = build_summary_section([storm, radiation], "en")
    lines = summary.markdown.splitlines()
    assert lines[0] == "- **Danger:** Zone danger"
    assert "Bryansk caution" not in summary.markdown                        # the cap is still five items
    assert len([l for l in lines if l.startswith("- **")]) == MAX_ITEMS


def test_pinned_only_breaks_ties_within_a_severity():
    a = Section("weather", "", "derived", warnings=[PlanWarning("danger", "Storm")])
    b = Section("hazards", "", "tag-backed", warnings=[PlanWarning("caution", "Zone", pinned=True)])
    assert build_summary_section([b, a], "en").markdown.splitlines()[:2] == ["- **Danger:** Storm", "- **Caution:** Zone"]
