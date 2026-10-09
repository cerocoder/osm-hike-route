#!/usr/bin/env python3
"""The Claude Code `statusLine` command: while a planner / day-plan run is alive, its progress REPLACES the normal
line; otherwise the user's normal statusline command (--fallback) runs with the same stdin and its output is shown.

    python3 statusline.py --fallback "npx -y ccusage@latest statusline"

    python3 statusline.py --check      # "installed" / "not installed" (exit 0 / 1) for the user's settings.json
    python3 statusline.py --install    # puts this script into settings.json as the statusLine, the old one as --fallback

Reads the status files written by runlog.py (~/.cache/osm-hike-route/status/<pid>.json, or $OSM_HIKE_STATUS_DIR).
A run counts as live when its pid exists and its heartbeat is younger than 30 s. Never raises and never hangs.
"""
import argparse
import json
import math
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progress import MESSAGES  # noqa: E402
from runlog import default_status_dir  # noqa: E402

STALE_AFTER_S = 30.0
FALLBACK_TIMEOUT_S = 2.0


def pid_alive(pid) -> bool:
    try:
        if int(pid) <= 0:
            return False
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError, TypeError):
        return True                                              # exists, but not ours: treat as alive
    return True


def pick_status(status_dir, now, alive=pid_alive):
    """The freshest status of a live run, or None."""
    best = None
    try:
        files = list(Path(status_dir).glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
            heartbeat = float(status["heartbeat"])
            if (not isinstance(status, dict) or not math.isfinite(heartbeat) or now - heartbeat >= STALE_AFTER_S
                    or not alive(status["pid"])):
                continue
        except Exception:  # noqa: BLE001
            continue
        if best is None or heartbeat > float(best["heartbeat"]):
            best = status
    return best


def _clock(seconds) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(status, now) -> str:
    lang = status.get("lang")
    lang = lang if isinstance(lang, str) and lang in MESSAGES["status_total"] else "en"
    if not status.get("step_title") and status.get("activity"):          # no Progress: the latest request instead
        line = f"🥾 {status.get('tool') or ''} · {status['activity']}"
        if status.get("activity_started"):
            line += f" · {_clock(now - status['activity_started'])}"
    else:
        counter = f"[{status.get('i') or 1}/{status['n']}]" if status.get("n") else f"[{status.get('i') or 1}]"
        line = f"🥾 {counter} {status.get('step_title') or ''}".rstrip()
        if status.get("total"):
            line += f" {status.get('done') or 0}/{status['total']}"
        if status.get("step_started"):
            line += f" · {_clock(now - status['step_started'])}"
    if status.get("run_started"):
        line += f" · {MESSAGES['status_total'][lang]} {_clock(now - status['run_started'])}"
    return line


def _fallback(command, stdin_text) -> str:
    try:
        process = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return ""
    try:
        out, _ = process.communicate(stdin_text.encode("utf-8", "replace"), timeout=FALLBACK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass
        return ""
    except Exception:  # noqa: BLE001
        return ""
    return out.decode("utf-8", "replace").rstrip("\n") if process.returncode == 0 else ""


def _write(stdout, line) -> None:
    buffer = getattr(stdout, "buffer", None)
    if buffer is not None:
        buffer.write(line.encode("utf-8", "replace"))
        buffer.flush()
    else:
        encoding = getattr(stdout, "encoding", None) or "utf-8"
        stdout.write(line.encode(encoding, "replace").decode(encoding, "replace"))


def settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def _ours(command) -> bool:
    """A statusLine command that runs this skill's statusline.py (wherever it is reached from)."""
    return isinstance(command, str) and "statusline.py" in command and (
        "osm-day-route-planning" in command or os.path.abspath(__file__) in command)


def _load_settings(path):
    """(dict, error): a missing file is ({}, None); anything that is not a JSON object is an error, never overwritten."""
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{path}: {e}"
    return (data, None) if isinstance(data, dict) else (None, f"{path}: not a JSON object")


def check(path) -> bool:
    data, error = _load_settings(path)
    line = (data or {}).get("statusLine")
    return error is None and isinstance(line, dict) and _ours(line.get("command"))


def install(path, script, now=time.time) -> str:
    """Sets statusLine to this script (the previous command, if any, becomes --fallback). Returns one line for the
    user. Idempotent; a copy of the file is kept first; a file that is not valid JSON is left alone."""
    data, error = _load_settings(path)
    if error:
        return f"not installed: {error}"
    old = data.get("statusLine")
    if isinstance(old, dict) and _ours(old.get("command")):
        return f"already installed in {path}"
    command = f"python3 {shlex.quote(str(script))}"
    previous = old.get("command") if isinstance(old, dict) and old.get("type", "command") == "command" else None
    if isinstance(previous, str) and previous.strip():
        command += f" --fallback {shlex.quote(previous)}"
    if path.exists():
        stamp = datetime.fromtimestamp(now(), timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    data["statusLine"] = {**(old if isinstance(old, dict) else {}), "type": "command", "command": command}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return (f"installed the statusline in {path}" + (" (the previous one is kept as --fallback)" if previous else "")
            + "; it takes effect in a new Claude Code session or on the next refresh")


def _main(argv, stdin, stdout, now, alive) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fallback", default=None, help="the normal statusline command")
    parser.add_argument("--status-dir", default=None)
    parser.add_argument("--check", action="store_true", help="is the statusline installed in settings.json?")
    parser.add_argument("--install", action="store_true", help="install it (idempotent, keeps a copy of settings.json)")
    parser.add_argument("--settings", default=None, help="settings.json to check / change (default: Claude's)")
    args = parser.parse_args(argv)
    if args.check or args.install:
        stdout = stdout if stdout is not None else sys.stdout
        path = Path(args.settings) if args.settings else settings_path()
        if args.install:
            message = install(path, os.path.abspath(__file__))
            ok = not message.startswith("not installed")
        else:
            ok = check(path)
            message = "installed" if ok else "not installed"
        stdout.write(message + "\n")
        if not ok:
            raise SystemExit(1)
        return
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        stdin_text = stdin.read()
    except Exception:  # noqa: BLE001
        stdin_text = ""
    line = ""
    try:
        status = pick_status(args.status_dir or default_status_dir(), now(), alive)
        if status is not None:
            line = render(status, now())
    except Exception:  # noqa: BLE001
        line = ""
    if not line and args.fallback:
        line = _fallback(args.fallback, stdin_text)
    if line:
        _write(stdout, line + "\n")


def main(argv=None, stdin=None, stdout=None, now=time.time, alive=pid_alive) -> int:
    try:
        _main(argv, stdin, stdout, now, alive)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
