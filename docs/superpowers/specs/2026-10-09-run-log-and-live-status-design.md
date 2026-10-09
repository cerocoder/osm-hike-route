# Run log and live status — design

Date: 2026-10-09. Scope: `osm-day-route-planning` and `osm-day-route-day-plan` (`osm-day-route-show` later, same module).

## Problem

Long planning runs show the user nothing but Claude Code's "Running… N min". `progress.py` already writes localized step lines to stderr, but the Bash tool does not stream them to the user, and the advice "run in the background and follow a log" has no log behind it. There is also nothing to profile a run with: no timestamps, no per-request timing, nothing left on disk afterwards.

## Decisions (from the user)

| Question | Decision |
|---|---|
| Live progress | A Claude Code **statusline** fed by a status file (CLI only). |
| Existing statusline (`ccusage`) | The normal statusline stays; while a skill runs, our progress **replaces** it, afterwards the normal line returns (section 3). |
| Log location | The route folder itself, next to `route.geojson` and the map. |
| Log language | English, stable field names (a tool for analysis, not for the user). Console progress stays in the user's language. |
| Dependencies | stdlib only. |

## 1. `runlog.py` (planning: `scripts/runlog.py`; day plan: `scripts/day_plan/runlog.py`, identical copy, compared by a planning test, like `progress.py`)

- File: `<route_dir>/<tool>-<UTC yyyymmddTHHMMSS>.log.jsonl` — directly in the route folder (`routes/<slug>-<date>/`), next to `route.geojson`, `notes.md` and the map; no subfolder. The planner resolves (or creates) the route folder at the start of the pipeline, before the first step, so the log exists from the first Overpass query on. The 20 newest logs per route folder are kept. `archive_validate` ignores extra files, so logs do not affect archive completeness.
- One JSON object per line, flushed at once, so a killed or crashed run keeps everything up to its last line.
- Common fields: `t` (seconds since run start, 3 decimals), `ev`, optional `span` (dotted path, e.g. `plugins.weather`).

| `ev` | Fields |
|---|---|
| `run_start` | `tool`, `argv`, `python`, `platform`, `version` |
| `span_start` / `span_end` | `span`; end adds `dur`, `ok`, `error` (one line) |
| `http` | `host`, `path` (no query string, no keys), `status`, `bytes`, `attempt`, `cache` (`hit`/`miss`/null), `t_sent`, `t_answer`, `dur` (= `t_answer - t_sent`: from sending the request to receiving the answer, for every single request, retries included as separate events) |
| `http_series` | `series` (name, e.g. `elevation_batches`), `n` (requests), `ok`, `failed`, `t_first_sent`, `t_last_answer`, `dur` (= `t_last_answer - t_first_sent`: wall time from the first request of the series to the last answer, including pauses between requests such as the 1 req/s rate limit), `sum_dur` (sum of the single `dur`s), `bytes` |
| `cache` | `kind`, `result` (`hit`/`miss`/`stale`), `age_s` |
| `metric` | `name`, `value` (counts: edges, points, batches) |
| `warn` / `error` | `msg`; error adds `traceback` |
| `run_end` | `dur`, `ok` |

- **Request timing rule:** every request is logged with the total time from sending to answer; every series of requests (elevation batches, geometry batches, the plugin's several calls, Overpass attempts across mirrors) also gets one `http_series` event with the total time from the start of the series to the last answer. `RunLog.http_series(name)` is a context manager; single `http` events inside it are tagged with `series`. A request that fails or times out still gets `t_sent`, `t_answer` (the moment of the failure) and `dur`. Time spent waiting between requests (rate limit, backoff) is visible as `dur - sum_dur`.
- `RunLog.span(name)` is a context manager; spans nest (a thread-local-free stack: the pipeline is sequential).
- A write failure disables the log for the rest of the run and never raises (same rule as `Progress._emit`).
- `NullRunLog` is the default everywhere.

## 2. Wiring

- `Progress(..., runlog=None)`: `step` opens/closes a span, `tick` writes a `metric` (rate-limited like the console line), `note`/`warn` write `cache`/`warn` events keyed by the message key (not the translated text). Existing call sites and signatures do not change.
- HTTP: the day plan's `http.py` and the planner's Overpass and elevation transports go through one wrapper that times the call and emits `http` (retries are separate events with `attempt`). Plugins are untouched.
- `run_plugins` already opens one step per plugin, so each plugin becomes a span for free.
- `build_day_plan.main` creates the `RunLog` (CLI only; `--quiet` does not silence the log; `--no-log` does). Library callers and tests get `NullRunLog`.
- The planner SKILL.md example creates `RunLog` next to `Progress` and passes both.

## 3. Live status (replaces the normal statusline while a skill runs)

- `Progress` (through `RunLog`) rewrites `~/.cache/osm-hike-route/status/<pid>.json` atomically at most once per second: `{pid, tool, lang, step_title, i, n, done, total, step_started, run_started, heartbeat, log}`. `step_title` is already localized. A `heartbeat` refresh also happens on every event, and the file is removed at exit (`atexit`; a crash leaves a file that goes stale).
- `scripts/statusline.py` (a new script in the planning skill; stdlib) is the one `statusLine` command. It reads Claude Code's JSON from stdin and:
  - **a skill is running** (a status file whose pid is alive and whose heartbeat is younger than 30 s): prints only the progress line, e.g. `🥾 [3/9] Высоты 41/91 · 1:20 · всего 4:05`; the normal line is **not** shown;
  - **nothing is running:** runs the user's normal statusline command, passing the same stdin through, and prints its output unchanged. The normal command comes from `--fallback "<command>"` (for this user: `npx -y ccusage@latest statusline`). Without `--fallback`, it prints nothing. A failing or slow (> 2 s) fallback prints nothing and never breaks the line.
  - The moment the run ends (status file removed or stale), the next refresh returns the normal line; no cleanup is needed in `settings.json`.
- Installation is a manual `statusLine` entry in the user's `settings.json`, e.g. `"command": "python3 <plugin>/skills/osm-day-route-planning/scripts/statusline.py --fallback 'npx -y ccusage@latest statusline'"`; the skill documents it, and the agent adds it only on the user's request. (The ccusage entry removed from `settings.json` on 2026-10-09 is restored this way.)
- Limits: terminal CLI only; the statusline refreshes on Claude Code's own cadence, so a few seconds of lag is expected.

## 4. `log_report.py <log.jsonl>` (planning skill scripts)

Prints: total time and outcome; span tree with `dur` and share of the parent; top 10 longest spans; HTTP summary per host (requests, retries, total/max single time, bytes) and per series (wall time first-sent → last-answer, sum of single times, waiting share); cache hit rate; all `warn`/`error` events. Plain text, English.

## 5. SKILL.md changes

- Planner and day-plan: the long script is always started in the background; the text names the log path and `log_report.py`, and points the user at the statusline for live progress.

## Testing

- Log file lands in the route folder with the documented name; `http` has `t_sent`/`t_answer`/`dur` for success and failure; `http_series` has first-sent to last-answer time and `sum_dur`, with a fake clock and a rate-limit pause between requests.
- Statusline: running skill replaces the normal line (fallback not executed); no running skill runs the fallback with the same stdin and prints its output; broken or slow fallback prints nothing.
- Event format, span nesting, `dur` with an injected clock, flush per line, retention of 20 logs per route folder.
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

`render_map` instrumentation, Windows status paths, `cProfile`-level CPU profiling, wrapping any statusline other than the one passed via `--fallback`.
