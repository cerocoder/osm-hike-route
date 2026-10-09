import io
import json
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


# ---- a progress write must never raise into the work it reports on -------------------------------------------------------

class _BrokenPipe(io.StringIO):
    def write(self, text):
        raise BrokenPipeError("closed")


class _NoFlush:
    encoding = "utf-8"

    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)


def test_a_broken_stream_silences_the_output_and_never_raises():
    progress = Progress(total_steps=1, lang="ru", stream=_BrokenPipe(), clock=Clock())
    with progress.step("graph"):
        progress.tick(1, 2, "tag_progress")
        progress.detail("graph_done", nodes=1, edges=2)
    progress.note("overpass_cache_hit", age=1)
    progress.warn("overpass_failed", endpoint="e", reason="r")


def test_a_stream_without_flush_or_isatty_does_not_raise():
    progress = Progress(total_steps=1, stream=_NoFlush(), clock=Clock())
    with progress.step("graph"):
        pass


def test_a_stream_that_cannot_encode_the_no_break_space_gets_a_plain_space():
    stream = Stream(encoding="ascii")
    progress = Progress(total_steps=1, lang="en", stream=stream, clock=Clock())
    with progress.step("graph"):
        progress.detail("graph_done", nodes=35398, edges=72658)
    assert " " not in stream.getvalue() and "35 398 nodes, 72 658 edges" in stream.getvalue()

def test_the_public_route_steps_exist_and_a_russian_run_has_no_english_words():
    progress, stream, clock = make("ru", total=None)
    for key in ("public_candidates", "public_geometry", "public_elevation", "public_keypoints"):
        with progress.step(key):
            clock.advance(0.3)
            progress.tick(1, 2, "public_geometry_batch")
    with progress.step("public_candidates") as step:
        step.detail("public_candidates_done", found=12, long=3)
    with progress.step("public_keypoints") as step:
        step.detail("public_done", matching=7, shown=7)
    text = stream.getvalue()
    assert "найдено 12, дальних (многодневных) пропущено 3" in text and "подходят 7, показано 7" in text
    assert not re.search(r"\b(Public|routes|geometry|found|match|shown|key points|elevations)\b", text)


# ---- forwarding to a run log ----------------------------------------------------------------------------------------------

class _Rec:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a))


def _p(rec, **kw):
    return pr.Progress(total_steps=3, lang="ru", stream=io.StringIO(), runlog=rec, **kw)


def test_a_step_is_forwarded_with_its_localized_title_and_counter():
    rec = _Rec()
    with _p(rec).step("graph") as step:
        step.detail("graph_done", nodes=1, edges=2)
    assert rec.calls[0] == ("step_start", ("graph", "Граф дорог", 1, 3, "ru"))
    assert rec.calls[-1] == ("step_end", (True, None, "1 вершин, 2 рёбер"))


def test_the_span_name_can_differ_from_the_message_key():
    rec = _Rec()
    with _p(rec).step("plugin", text="Погода", span="plugin.weather"):
        pass
    assert rec.calls[0] == ("step_start", ("plugin.weather", "Погода", 1, 3, "ru"))


def test_a_failed_or_raising_step_is_forwarded_as_not_ok():
    rec = _Rec()
    with _p(rec).step("graph") as step:
        step.fail("HTTP 503")
    assert rec.calls[-1] == ("step_end", (False, "HTTP 503", None))
    rec2 = _Rec()
    with pytest.raises(ValueError):
        with _p(rec2).step("graph"):
            raise ValueError("bad")
    assert rec2.calls[-1] == ("step_end", (False, "ValueError: bad", None))


def test_ticks_notes_and_warnings_are_forwarded_with_their_keys():
    rec = _Rec()
    progress = _p(rec)
    progress.tick(5, 10, "tag_progress")
    progress.note("overpass_cache_hit", age=3)
    progress.warn("overpass_failed", endpoint="h", reason="504")
    assert ("progress_tick", (5, 10, "tag_progress")) in rec.calls
    assert ("message", ("note", "overpass_cache_hit", {"age": 3})) in rec.calls
    assert ("message", ("warn", "overpass_failed", {"endpoint": "h", "reason": "504"})) in rec.calls


def test_a_run_log_that_raises_never_breaks_progress():
    class Boom:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise RuntimeError("log is broken")
            return fail

    out = io.StringIO()
    progress = pr.Progress(total_steps=1, lang="en", stream=out, runlog=Boom())
    with progress.step("graph"):
        progress.tick(1, 2)
        progress.note("overpass_cache_hit", age=1)
    assert "[1/1]" in out.getvalue()


def test_status_total_exists_in_every_language():
    assert set(pr.MESSAGES["status_total"]) == set(pr.LANGS)


def test_a_real_run_log_receives_the_steps(tmp_path):
    import runlog
    log = runlog.RunLog.start(tmp_path, "plan", heartbeat=False, install_as_current=False, status_dir=tmp_path / "s")
    progress = pr.Progress(total_steps=1, lang="de", stream=io.StringIO(), runlog=log)
    with progress.step("graph"):
        pass
    log.close()
    lines = [json.loads(l) for l in log.path.read_text(encoding="utf-8").splitlines()]
    start = next(e for e in lines if e["ev"] == "span_start")
    assert start["span"] == "graph" and start["title"] == "Wegegraph"
