import importlib.util
from pathlib import Path

import pytest

import notes_headings
from notes_headings import HEADINGS, LANGUAGES, REQUIRED_KEYS, heading, missing_sections


def test_every_section_has_a_heading_in_every_language_and_no_two_collide():
    for key, by_lang in HEADINGS.items():
        assert set(by_lang) == set(LANGUAGES), key
    every = [text.casefold() for by_lang in HEADINGS.values() for text in by_lang.values()]
    assert len(every) == len(set(every))                  # a heading names exactly one section


def test_heading_falls_back_to_english_for_an_unknown_language():
    assert heading("interest", "ru") == "Точки интереса" and heading("interest", "xx") == "Points of interest"


def test_missing_sections_uses_exact_headings_only():
    text = "## Access\n- x\n\n## Points of interest (8)\n- x\n"
    assert missing_sections(text) == ["request", "reasoning", "interest", "distance"]       # a suffix is not the heading
    assert missing_sections("") == list(REQUIRED_KEYS)


def test_the_show_skill_carries_the_same_table():
    path = Path(__file__).resolve().parents[2] / "osm-day-route-show" / "scripts" / "render_map.py"
    if not path.exists():
        pytest.skip("osm-day-route-show is not next to this skill")
    import sys
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("render_map_for_headings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.NOTES_HEADINGS == {k: dict(v) for k, v in HEADINGS.items()}
