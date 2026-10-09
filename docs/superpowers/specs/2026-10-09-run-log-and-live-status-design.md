# Run log and live status — design

Date: 2026-10-09. Scope: `osm-day-route-planning` and `osm-day-route-day-plan` (`osm-day-route-show` later, same module).

## Problem

Long planning runs show the user nothing but Claude Code's "Running… N min". `progress.py` already writes localized step lines to stderr, but the Bash tool does not stream them to the user, and the advice "run in the background and follow a log" has no log behind it. There is also nothing to profile a run with: no timestamps, no per-request timing, nothing left on disk afterwards.

## Decisions (from the user)

| Question | Decision |
|---|---|
| Live progress | A Claude Code **statusline** fed by a status file (CLI only). |
| Existing statusline (`ccusage`) | Removed by the user's request; our statusline script does not wrap it. |
| Log language | English, stable field names (a tool for analysis, not for the user). Console progress stays in the user's language. |
| Dependencies | stdlib only. |

## 1. `runlog.py` (planning: `scripts/runlog.py`; day plan: `scripts/day_plan/runlog.py`, identical copy, compared by a planning test, like `progress.py`)

- File: `<route_dir>/logs/<UTC yyyymmddTHHMMSS>-<tool>.jsonl`; the planner, which has no route directory yet, uses `routes/.cache/logs/`. The 20 newest files per folder are kept.
- One JSON object per line, flushed at once, so a killed or crashed run keeps everything up to its last line.
- Common fields: `t` (seconds since run start, 3 decimals), `ev`, optional `span` (dotted path, e.g. `plugins.weather`).

| `ev` | Fields |
|---|---|
| `run_start` | `tool`, `argv`, `python`, `platform`, `version` |
| `span_start` / `span_end` | `span`; end adds `dur`, `ok`, `error` (one line) |
| `http` | `host`, `path` (no query string, no keys), `status`, `bytes`, `dur`, `attempt`, `cache` (`hit`/`miss`/null) |
| `cache` | `kind`, `result` (`hit`/`miss`/`stale`), `age_s` |
| `metric` | `name`, `value` (counts: edges, points, batches) |
| `warn` / `error` | `msg`; error adds `traceback` |
| `run_end` | `dur`, `ok` |

- `RunLog.span(name)` is a context manager; spans nest (a thread-local-free stack: the pipeline is sequential).
- A write failure disables the log for the rest of the run and never raises (same rule as `Progress._emit`).
- `NullRunLog` is the default everywhere.

## 2. Wiring

- `Progress(..., runlog=None)`: `step` opens/closes a span, `tick` writes a `metric` (rate-limited like the console line), `note`/`warn` write `cache`/`warn` events keyed by the message key (not the translated text). Existing call sites and signatures do not change.
- HTTP: the day plan's `http.py` and the planner's Overpass and elevation transports go through one wrapper that times the call and emits `http` (retries are separate events with `attempt`). Plugins are untouched.
- `run_plugins` already opens one step per plugin, so each plugin becomes a span for free.
- `build_day_plan.main` creates the `RunLog` (CLI only; `--quiet` does not silence the log; `--no-log` does). Library callers and tests get `NullRunLog`.
- The planner SKILL.md example creates `RunLog` next to `Progress` and passes both.

## 3. Live status

- `Progress` (through `RunLog`) rewrites `~/.cache/osm-hike-route/status/<pid>.json` atomically at most once per second: `{pid, tool, lang, step_title, i, n, done, total, step_started, run_started, heartbeat, log}`. `step_title` is already localized. A `heartbeat` refresh also happens on every event, and the file is removed at exit (`atexit`; a crash leaves a file that goes stale).
- `scripts/statusline.py` (a new script in the planning skill; stdlib): reads Claude Code's JSON from stdin (ignored), picks the newest status file whose pid is alive and whose heartbeat is younger than 30 s, prints one line, e.g. `🥾 [3/9] Высоты 41/91 · 1:20 · всего 4:05`. No live run: prints nothing.
- Installation is a manual `statusLine` entry in the user's `settings.json`; the skill documents it, and the agent adds it only on the user's request.
- Limits: terminal CLI only; the statusline refreshes on Claude Code's own cadence, so a few seconds of lag is expected.

## 4. `log_report.py <log.jsonl>` (planning skill scripts)

Prints: total time and outcome; span tree with `dur` and share of the parent; top 10 longest spans; HTTP summary per host (requests, retries, total/max time, bytes); cache hit rate; all `warn`/`error` events. Plain text, English.

## 5. SKILL.md changes

- Planner and day-plan: the long script is always started in the background; the text names the log path and `log_report.py`, and points the user at the statusline for live progress.

## Testing

- Event format, span nesting, `dur` with an injected clock, flush per line, retention of 20 files.
- Write failure (read-only folder, closed stream) disables the log without an exception.
- `Progress` + `RunLog`: step/tick/note/warn produce the expected events; console output unchanged (existing tests stay green).
- HTTP wrapper: success, retry, failure, cache annotation; query strings never reach the log.
- Status file: atomic write, rate limit, removal at exit; statusline picks the newest live file, ignores stale heartbeats and dead pids, prints nothing when idle.
- `log_report.py` on a fixture log; the two `runlog.py` copies are identical.
- All three skills' suites stay green.

## Risks

- Statusline lag or absence (desktop app) → the log file and `log_report.py` work regardless.
- Log growth → retention of 20 files; `tick` metrics are rate-limited.
- Secrets in URLs → only host and path are logged; a test checks it.

## Out of scope

`render_map` instrumentation, Windows status paths, `cProfile`-level CPU profiling, shipping a statusline wrapper around other tools.
