import json

import pytest

import record_fact
from day_plan.facts import load_facts, lookup

URL = "https://www.crtm.es/horarios"


def _run(route_dir, *args):
    return record_fact.main([str(route_dir), *args])


def test_records_a_fact_that_the_plan_can_read_back(tmp_path, capsys):
    code = _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "Bus 41 every 20 min.",
                "--source", URL, "--source", "https://metromadrid.es", "--last-departure", "23:10",
                "--warning", "caution:Line 10 closed for works")
    assert code == 0 and "recorded transit for 2026-06-27 (2 source(s))" in capsys.readouterr().out
    entry = lookup(load_facts(tmp_path), "2026-06-27", "transit")
    assert entry["markdown"] == "Bus 41 every 20 min." and entry["last_departure_local"] == "23:10"
    assert entry["warnings"] == [{"severity": "caution", "text": "Line 10 closed for works"}]
    assert entry["sources"] == [URL, "https://metromadrid.es"]


def test_later_facts_are_merged_not_overwritten(tmp_path):
    _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "general", "--source", URL)
    _run(tmp_path, "--date", "2026-06-27", "--plugin", "poi_hours", "--markdown", "museum", "--source", URL)
    _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "specific", "--source", URL)
    facts = json.loads((tmp_path / "facts.json").read_text(encoding="utf-8"))
    assert facts["all"]["transit"]["markdown"] == "general"
    assert facts["2026-06-27"]["poi_hours"]["markdown"] == "museum"
    assert facts["2026-06-27"]["transit"]["markdown"] == "specific"


def test_markdown_can_come_from_a_file(tmp_path):
    (tmp_path / "note.md").write_text("From a file, with ünïcode.", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown-file", str(tmp_path / "note.md"),
                "--source", URL) == 0
    assert "ünïcode" in (tmp_path / "facts.json").read_text(encoding="utf-8")   # not escaped to ü


def test_calendar_fact_needs_only_a_day_type_and_a_source(tmp_path):
    assert _run(tmp_path, "--date", "2026-05-11", "--plugin", "calendar", "--day-type", "holiday",
                "--source", "https://www.consultant.ru/x") == 0
    assert lookup(load_facts(tmp_path), "2026-05-11", "calendar")["day_type"] == "holiday"


@pytest.mark.parametrize("args,reason", [
    (["--date", "2026-06-27", "--plugin", "transit", "--markdown", "no source"], "at least one http(s) --source"),
    (["--date", "2026-06-27", "--plugin", "transit", "--markdown", "x", "--source", "ftp://x"], "at least one http(s)"),
    (["--date", "2026-06-27", "--plugin", "transit", "--source", URL], "non-empty text"),
    (["--date", "27-06-2026", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "all", "--plugin", "weather", "--markdown", "x", "--source", URL], "unknown plugin"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--last-departure", "late"], "bad last_departure_local"),
    (["--date", "all", "--plugin", "calendar", "--day-type", "funday", "--markdown", "x", "--source", URL], "bad day type"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--warning", "mystery:oops"], "bad warning"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--warning", "no separator"], "bad warning"),
])
def test_invalid_facts_are_refused_and_nothing_is_written(tmp_path, capsys, args, reason):
    assert _run(tmp_path, *args) == 1
    assert reason in capsys.readouterr().err
    assert not (tmp_path / "facts.json").exists()


def test_an_unparsable_facts_file_is_never_overwritten(tmp_path, capsys):
    (tmp_path / "facts.json").write_text("{broken", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert (tmp_path / "facts.json").read_text(encoding="utf-8") == "{broken"


def test_a_non_object_facts_file_is_never_overwritten(tmp_path, capsys):
    (tmp_path / "facts.json").write_text("[1, 2]", encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 1
    assert (tmp_path / "facts.json").read_text(encoding="utf-8") == "[1, 2]"


def test_a_scope_that_is_not_an_object_is_replaced_safely(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({"all": ["junk"]}), encoding="utf-8")
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 0
    assert lookup(load_facts(tmp_path), "2026-06-27", "transit")["markdown"] == "x"


def test_no_temporary_file_is_left_behind(tmp_path):
    _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL)
    assert [p.name for p in tmp_path.iterdir()] == ["facts.json"]


def test_bad_arguments(tmp_path, capsys):
    assert record_fact.main([str(tmp_path / "missing"), "--date", "all", "--plugin", "transit"]) == 1
    assert "is not a directory" in capsys.readouterr().err
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "a", "--markdown-file", "b") == 1
    assert "not both" in capsys.readouterr().err
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown-file", str(tmp_path / "nope.md"),
                "--source", URL) == 1
