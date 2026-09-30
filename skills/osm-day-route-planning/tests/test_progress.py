import io
import re
from pathlib import Path

import pytest

import progress as pr
from progress import LANGS, MESSAGES, NullProgress, Progress, format_number


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Stream(io.StringIO):
    def __init__(self, tty=False, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    @property
    def encoding(self):
        return self._encoding

    def isatty(self):
        return self._tty


def make(lang="en", tty=False, total=3, **kwargs):
    stream, clock = Stream(tty), Clock()
    return Progress(total_steps=total, lang=lang, stream=stream, clock=clock, **kwargs), stream, clock


def test_a_plain_step_prints_a_start_line_and_a_done_line():
    progress, stream, clock = make()
    with progress.step("graph"):
        clock.advance(0.14)
        progress.detail("graph_done", nodes=35398, edges=72658)
    assert stream.getvalue().splitlines() == [
        "[1/3] Road graph …", "      ✓ 0.1 s · 35 398 nodes, 72 658 edges"]


def test_the_counter_advances_and_works_without_a_known_total():
    progress, stream, _ = make(total=None)
    with progress.step("graph"):
        pass
    with progress.step("elevation"):
        pass
    assert [l for l in stream.getvalue().splitlines() if l.startswith("[")] == ["[1] Road graph …", "[2] Elevations …"]


def test_russian_output_uses_a_decimal_comma_and_russian_words():
    progress, stream, clock = make("ru")
    with progress.step("graph"):
        clock.advance(2.4)
        progress.detail("graph_done", nodes=1234, edges=5)
    assert stream.getvalue().splitlines() == ["[1/3] Граф дорог …", "      ✓ 2,4 с · 1\u00a0234 вершин, 5 рёбер"]


def test_a_russian_run_prints_no_english_words():
    progress, stream, clock = make("ru", total=None)
    for key in ("overpass", "graph", "tag_edges", "elevation", "routing", "optional"):
        with progress.step(key):
            clock.advance(0.5)
    progress.note("overpass_cache_hit", age=3)
    progress.warn("overpass_failed", endpoint="overpass-api.de", reason="HTTP 504")
    with progress.step("overpass"):
        progress.detail("overpass_done", walkable=3, restricted=1)
    text = stream.getvalue()
    assert not re.search(r"\b(ways|nodes|edges|attempt|Road|Overpass query|cached|answer|did not)\b", text)


def test_an_unknown_language_falls_back_to_english_and_an_unknown_key_prints_the_key():
    progress, stream, _ = make("xx")
    with progress.step("graph"):
        pass
    progress.note("no_such_key")
    assert "Road graph" in stream.getvalue() and "no_such_key" in stream.getvalue()


def test_a_bad_placeholder_never_raises():
    progress, stream, _ = make()
    progress.note("overpass_attempt", endpoint="x")          # n and m missing
    assert "attempt" in stream.getvalue()


def test_ticks_without_a_terminal_are_rate_limited_and_never_shown_for_a_quick_step():
    progress, stream, clock = make()
    with progress.step("elevation"):
        for i in range(1, 11):
            clock.advance(0.2)
            progress.tick(i, 10, "elevation_batch")
    assert len(stream.getvalue().splitlines()) == 2                     # the start and the done line only

    progress, stream, clock = make()
    with progress.step("elevation"):
        for i in range(1, 92):
            clock.advance(0.3)                                          # 27 s in total
            progress.tick(i, 91, "elevation_batch")
    ticks = [l for l in stream.getvalue().splitlines() if l.startswith("      …")]
    assert 4 <= len(ticks) <= 6 and "elevation request" in ticks[0] and "%" in ticks[0]
    assert "\r" not in stream.getvalue() and "\x1b" not in stream.getvalue()


def test_a_terminal_rewrites_the_tick_line_and_colours_the_marks(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    progress, stream, clock = make(tty=True)
    with progress.step("elevation"):
        progress.tick(1, 4, "elevation_batch")
        progress.tick(2, 4, "elevation_batch")
    out = stream.getvalue()
    assert out.count("\r\x1b[K      …") == 2 and "\x1b[32m✓\x1b[0m" in out
    assert out.endswith("\n") and out.count("\n") == 2                  # the ticks stay on one screen line


def test_no_color_is_respected_on_a_terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    progress, stream, _ = make(tty=True)
    with progress.step("graph"):
        pass
    progress.warn("overpass_failed", endpoint="e", reason="r")
    assert "\x1b[3" not in stream.getvalue()


def test_an_exception_is_reported_in_one_line_and_reraised():
    progress, stream, clock = make()
    with pytest.raises(RuntimeError):
        with progress.step("graph"):
            clock.advance(1.0)
            raise RuntimeError("boom\nsecond line")
    assert stream.getvalue().splitlines()[-1] == "      ✗ 1.0 s · RuntimeError: boom second line"


def test_fail_marks_a_step_without_raising_and_text_replaces_the_title():
    progress, stream, _ = make()
    with progress.step("graph", text="Weather") as step:
        step.fail("HTTP 503")
    assert stream.getvalue().splitlines() == ["[1/3] Weather …", "      ✗ 0.0 s · HTTP 503"]


def test_a_stream_that_cannot_print_the_marks_gets_ascii():
    stream, clock = Stream(encoding="ascii"), Clock()
    progress = Progress(total_steps=1, stream=stream, clock=clock)
    with progress.step("graph"):
        pass
    assert "ok" in stream.getvalue() and "✓" not in stream.getvalue() and "..." in stream.getvalue()


def test_null_progress_accepts_every_call():
    progress = NullProgress()
    with progress.step("graph") as step:
        step.tick(1, 2)
        step.detail("graph_done", nodes=1, edges=2)
        step.fail("x")
    progress.tick(1, 2)
    progress.detail("graph_done")
    progress.note("x")
    progress.warn("x")


def test_format_number():
    assert format_number(1234567.5, "en", 1) == "1 234 567.5"
    assert format_number(1234567.5, "de", 1) == "1 234 567,5"
    assert format_number(0.04, "ru", 1) == "0,0"


def test_every_message_exists_in_every_language_with_the_same_placeholders():
    for key, entry in MESSAGES.items():
        assert set(entry) == set(LANGS), key
        placeholders = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in entry.items()}
        assert len({frozenset(p) for p in placeholders.values()}) == 1, (key, placeholders)


def test_the_day_plan_copy_is_identical():
    copy = Path(__file__).resolve().parents[2] / "osm-day-route-day-plan" / "scripts" / "day_plan" / "progress.py"
    if not copy.exists():
        pytest.skip("osm-day-route-day-plan is not next to this skill")
    assert copy.read_text(encoding="utf-8") == Path(pr.__file__).read_text(encoding="utf-8")
