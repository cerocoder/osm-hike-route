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
    (["--date", "2026-6-7", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "2026-06-27T10:00", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "20260627", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "2026-W26-6", "--plugin", "transit", "--markdown", "x", "--source", URL], "bad date"),
    (["--date", "all", "--plugin", "weather", "--markdown", "x", "--source", URL], "unknown plugin"),
    (["--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL, "--last-departure", "late"], "bad last_departure_local"),
    (["--date", "2026-06-27", "--plugin", "calendar", "--day-type", "funday", "--markdown", "x", "--source", URL], "bad day type"),
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


def test_temp_file_cleaned_up_on_write_failure(tmp_path, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("record_fact.os.replace", boom)
    assert _run(tmp_path, "--date", "all", "--plugin", "transit", "--markdown", "x", "--source", URL) == 1
    assert "disk full" in capsys.readouterr().err
    assert not (tmp_path / "facts.json").exists()
    tmp_files = [p.name for p in tmp_path.iterdir() if p.name.startswith(".facts-")]
    assert tmp_files == []


def test_existing_facts_json_unchanged_after_failed_write(tmp_path, capsys, monkeypatch):
    # Create an existing facts.json with known content
    original_content = json.dumps({"2026-06-21": {"calendar": {"day_type": "holiday", "sources": ["https://example.com"]}}})
    (tmp_path / "facts.json").write_text(original_content, encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("record_fact.os.replace", boom)

    assert _run(tmp_path, "--date", "2026-06-22", "--plugin", "transit", "--markdown", "new", "--source", URL) == 1
    assert "disk full" in capsys.readouterr().err
    # Verify facts.json is unchanged byte for byte
    assert (tmp_path / "facts.json").read_text(encoding="utf-8") == original_content
    # Verify no temporary files remain
    tmp_files = [p.name for p in tmp_path.iterdir() if p.name.startswith(".facts-")]
    assert tmp_files == []


def test_a_calendar_fact_needs_a_specific_date(tmp_path, capsys):
    assert _run(tmp_path, "--date", "all", "--plugin", "calendar", "--day-type", "holiday", "--source", URL) == 1
    assert "a calendar fact needs a specific date" in capsys.readouterr().err
    assert not (tmp_path / "facts.json").exists()


@pytest.mark.parametrize("args,plugin", [
    (["--plugin", "transit", "--day-type", "holiday"], "transit"),
    (["--plugin", "poi_hours", "--day-type", "holiday"], "poi_hours"),
    (["--plugin", "poi_hours", "--last-departure", "23:00"], "poi_hours"),
    (["--plugin", "calendar", "--last-departure", "23:00", "--day-type", "holiday"], "calendar"),
    (["--plugin", "poi_hours", "--first-departure", "05:00"], "poi_hours"),
    (["--plugin", "calendar", "--first-departure", "05:00", "--day-type", "holiday"], "calendar"),
    (["--plugin", "calendar", "--warning", "info:x", "--day-type", "holiday"], "calendar"),
])
def test_fields_the_plugin_ignores_are_refused_naming_the_plugin(tmp_path, capsys, args, plugin):
    assert _run(tmp_path, "--date", "2026-06-27", "--markdown", "x", "--source", URL, *args) == 1
    err = capsys.readouterr().err
    assert plugin in err and "does not use" in err
    assert not (tmp_path / "facts.json").exists()


def test_fields_that_the_plugin_uses_are_accepted(tmp_path):
    assert _run(tmp_path, "--date", "2026-06-27", "--plugin", "transit", "--markdown", "x", "--source", URL,
                "--last-departure", "23:00", "--first-departure", "05:00", "--warning", "info:x") == 0
    assert _run(tmp_path, "--date", "2026-06-27", "--plugin", "poi_hours", "--markdown", "x", "--source", URL,
                "--warning", "info:x") == 0
    assert _run(tmp_path, "--date", "2026-06-27", "--plugin", "calendar", "--day-type", "holiday",
                "--source", URL) == 0
