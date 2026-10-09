#!/usr/bin/env python3
"""The Claude Code `statusLine` command: while a planner / day-plan run is alive, its progress REPLACES the normal
line; otherwise the user's normal statusline command (--fallback) runs with the same stdin and its output is shown.

    python3 statusline.py --fallback "npx -y ccusage@latest statusline"

Reads the status files written by runlog.py (~/.cache/osm-hike-route/status/<pid>.json, or $OSM_HIKE_STATUS_DIR).
A run counts as live when its pid exists and its heartbeat is younger than 30 s. Never raises and never hangs.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from progress import MESSAGES  # noqa: E402
from runlog import default_status_dir  # noqa: E402

STALE_AFTER_S = 30.0
FALLBACK_TIMEOUT_S = 2.0


def pid_alive(pid) -> bool:
    try:
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
            if not isinstance(status, dict) or now - heartbeat >= STALE_AFTER_S or not alive(status["pid"]):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if best is None or heartbeat > float(best["heartbeat"]):
            best = status
    return best


def _clock(seconds) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(status, now) -> str:
    lang = status.get("lang") if status.get("lang") in MESSAGES["status_total"] else "en"
    counter = f"[{status['i']}/{status['n']}]" if status.get("n") else f"[{status.get('i') or 1}]"
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
                                   stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    except OSError:
        return ""
    try:
        out, _ = process.communicate(stdin_text, timeout=FALLBACK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.communicate()
        return ""
    except Exception:  # noqa: BLE001
        return ""
    return out.rstrip("\n") if process.returncode == 0 else ""


def main(argv=None, stdin=None, stdout=None, now=time.time, alive=pid_alive) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fallback", default=None, help="the normal statusline command")
    parser.add_argument("--status-dir", default=None)
    args = parser.parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        stdin_text = stdin.read()
    except Exception:  # noqa: BLE001
        stdin_text = ""
    status = pick_status(args.status_dir or default_status_dir(), now(), alive)
    if status is not None:
        line = render(status, now())
    else:
        line = _fallback(args.fallback, stdin_text) if args.fallback else ""
    if line:
        stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
