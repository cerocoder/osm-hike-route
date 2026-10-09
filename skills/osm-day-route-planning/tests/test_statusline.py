import io
import json
import os
import sys

import pytest

import statusline

NOW = 1_700_000_100.0


def put(directory, pid, **fields):
    status = {"pid": pid, "tool": "plan", "lang": "ru", "step_title": "Высоты", "i": 3, "n": 9, "done": 41,
              "total": 91, "step_started": NOW - 80, "run_started": NOW - 245, "heartbeat": NOW - 2, "log": "/x"}
    status.update(fields)
    (directory / f"{pid}.json").write_text(json.dumps(status), encoding="utf-8")


def run(directory, argv=(), now=NOW, stdin="{}"):
    out = io.StringIO()
    code = statusline.main(["--status-dir", str(directory), *argv], stdin=io.StringIO(stdin), stdout=out,
                           now=lambda: now, alive=lambda pid: True)
    return code, out.getvalue()


def test_a_running_skill_replaces_the_normal_line(tmp_path):
    put(tmp_path, 111)
    code, out = run(tmp_path, ["--fallback", "echo NORMAL"])
    assert code == 0 and out.strip() == "🥾 [3/9] Высоты 41/91 · 1:20 · всего 4:05"


def test_english_label_and_a_step_without_counters(tmp_path):
    put(tmp_path, 111, lang="en", step_title="Road graph", done=None, total=None, n=None, i=2)
    _, out = run(tmp_path)
    assert out.strip() == "🥾 [2] Road graph · 1:20 · total 4:05"


def test_nothing_running_runs_the_fallback_with_the_same_stdin(tmp_path):
    code, out = run(tmp_path, ["--fallback", f"{sys.executable} -c \"import sys; print('NORMAL', sys.stdin.read())\""],
                    stdin='{"model": "x"}')
    assert code == 0 and out.strip() == 'NORMAL {"model": "x"}'


def test_no_fallback_and_nothing_running_prints_nothing(tmp_path):
    assert run(tmp_path) == (0, "")


def test_dead_pid_and_stale_heartbeat_are_ignored(tmp_path):
    put(tmp_path, 222)
    put(tmp_path, 333, heartbeat=NOW - 31)
    out = io.StringIO()
    statusline.main(["--status-dir", str(tmp_path)], stdin=io.StringIO("{}"), stdout=out, now=lambda: NOW,
                    alive=lambda pid: pid != 222)
    assert out.getvalue() == ""


def test_the_freshest_of_several_live_runs_wins_and_junk_is_skipped(tmp_path):
    put(tmp_path, 1, step_title="Старый", heartbeat=NOW - 10)
    put(tmp_path, 2, step_title="Новый", heartbeat=NOW - 1)
    (tmp_path / "3.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "4.json").write_text("[]", encoding="utf-8")
    _, out = run(tmp_path)
    assert "Новый" in out


def test_a_missing_status_folder_is_not_an_error(tmp_path):
    assert run(tmp_path / "nope") == (0, "")


def test_slow_or_failing_fallback_prints_nothing(tmp_path):
    assert run(tmp_path, ["--fallback", "exit 3"])[1] == ""
    slow = f"{sys.executable} -c \"import time; time.sleep(10)\""
    import time
    started = time.monotonic()
    assert run(tmp_path, ["--fallback", slow])[1] == ""
    assert time.monotonic() - started < 5


def test_pid_alive_for_this_process_and_a_dead_one():
    assert statusline.pid_alive(os.getpid()) is True
    assert statusline.pid_alive(2 ** 22 + 12345) is False
