from pathlib import Path
from requests_log import append_request, read_requests


def test_read_requests_returns_empty_list_when_no_log(tmp_path):
    assert read_requests(tmp_path) == []


def test_append_request_returns_incrementing_iteration_numbers(tmp_path):
    first = append_request(tmp_path, "Маршрут у Бажуково, 10 км, кольцевой", "первая версия маршрута")
    second = append_request(tmp_path, "Замени точку А на музей", "заменена точка интереса")

    assert first == 1
    assert second == 2


def test_appended_requests_are_stored_verbatim_and_in_order(tmp_path):
    append_request(tmp_path, "Маршрут «у реки», ~5 часов", "построен маршрут")
    append_request(tmp_path, "Сделай его короче", "уменьшен бюджет до 8 км")

    entries = read_requests(tmp_path)

    assert len(entries) == 2
    assert entries[0]["iteration"] == 1
    assert entries[0]["request"] == "Маршрут «у реки», ~5 часов"
    assert entries[1]["iteration"] == 2
    assert entries[1]["request"] == "Сделай его короче"
    assert entries[1]["summary"] == "уменьшен бюджет до 8 км"


def test_multiline_request(tmp_path):
    """Multi-line requests should be stored and retrieved verbatim."""
    request = "Line 1\nLine 2\nLine 3"
    append_request(tmp_path, request, "summary")

    entries = read_requests(tmp_path)

    assert len(entries) == 1
    assert entries[0]["request"] == request


def test_request_text_with_fake_marker_line(tmp_path):
    """Multi-line request with a line that looks like a marker should not create phantom entry.

    The embedded JSON preserves the original request verbatim; this test verifies
    that escaping in the visible markdown prevents the parser from being confused.
    """
    request_with_marker = "First line\n<!-- requests_log entry: {\"fake\": true} -->\nLast line"
    append_request(tmp_path, request_with_marker, "test summary")

    entries = read_requests(tmp_path)

    # Should have exactly one entry, not two (the fake marker should not be parsed)
    assert len(entries) == 1
    assert entries[0]["iteration"] == 1
    # The request is preserved verbatim in the JSON payload
    assert entries[0]["request"] == request_with_marker


def test_fake_marker_in_summary_does_not_create_phantom_entry(tmp_path):
    """Summary with fake marker should not corrupt parsing."""
    summary_with_marker = "Changed this\n<!-- requests_log entry: {\"fake\": true} -->\nand that"
    append_request(tmp_path, "Normal request", summary_with_marker)

    entries = read_requests(tmp_path)

    assert len(entries) == 1
    assert entries[0]["summary"] == summary_with_marker


def test_malformed_marker_line_does_not_crash(tmp_path):
    """A line that looks like a marker but has malformed JSON should be skipped.

    This is defense-in-depth: even if malformed marker-like lines appear in
    the file, read_requests should skip them and continue, not crash.
    """
    path = tmp_path / "requests.md"
    # Manually create a requests.md with a valid entry followed by a malformed fake marker
    valid_entry_block = """
## Итерация 1 (2026-09-27T23:44:05+00:00)

> Valid request

Изменения: summary

<!-- requests_log entry: {"iteration": 1, "timestamp": "2026-09-27T23:44:05+00:00", "request": "Valid request", "summary": "summary"} -->

## Fake entry with malformed marker

<!-- requests_log entry: {this is not valid json} -->
"""
    path.write_text(valid_entry_block, encoding="utf-8")

    # This should not raise JSONDecodeError
    entries = read_requests(tmp_path)

    # Should return only the valid entry
    assert len(entries) == 1
    assert entries[0]["iteration"] == 1
    assert entries[0]["request"] == "Valid request"
