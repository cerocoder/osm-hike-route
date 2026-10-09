# Run log for one-off scripts, activity status, statusline install — design

Extends `2026-10-09-run-log-and-live-status-design.md`. Spec of the plugin/cache/Overpass log events (`plugin_result`,
`overpass`, `cache`, `attempt`) is in that document.

## Problem

An agent session fetched Overpass tiles with throw-away scripts (`fetch.py`, `fetch2.py`, `pub.py` in its scratchpad)
that call `fetch_area_data` / `suggest` directly. Only the documented main script calls `RunLog.start`, so these runs
wrote no log and no status file: 10 minutes of Overpass 500s and retries were invisible to the user and to
`log_report.py`.

## Decisions (from the user)

- Every script that touches the network is logged, one-off ones included.
- The log of a route lives with the route. The statusline shows one-off runs too.
- The statusline is installed automatically (once, reported in one line); this replaces "offer it, never write it unasked".

## 1. Logging in one-off scripts

- **Rule (SKILL.md):** every script that fetches or plans starts with `RunLog.start(route_dir, "<name>", argv=sys.argv)`,
  `route_dir` being the folder with `requests.md` (it exists before the first fetch). Then the log is next to the route.
- **Safety net, `runlog.ensure_started(cache_dir)`**, called by the network layers (`query_overpass`, `ElevationService`,
  public-route geometry) when no run log is current:
  - folder: env `OSM_HIKE_ROUTE_DIR` if set (a route folder); else `<cache_dir>/../.logs/` (`routes/.logs/`); no
    folder known (no `cache_dir`) → nothing is started;
  - tool `adhoc`; `run_start` carries `adhoc: true`, `cwd`, `script` (argv[0]) and `cache_dir`, so a log can be traced to
    the script and to the route (`cwd`, `argv`);
  - tried once per process (a failure is not retried on every call); `OSM_HIKE_NO_LOG=1` switches it off (tests do);
  - closed at exit (`ok: true`, `note: "adhoc: closed at exit"`).
- No time-window guessing to attach `routes/.logs/` files to a route: the route-folder variable or the explicit
  `RunLog.start(route_dir)` is the way.
- `query_overpass` logs one `overpass` event per call (same fields as the day-plan one: `ql_bytes`, `timeout_s`,
  `radius_m`/`bbox_km2` when found in the query, `elements`, `mirror`, `tries`, or `error`), so tiles an Overpass server
  cannot serve at a given radius are visible in the report.

## 2. Status of a run without `Progress`

`RunLog` keeps an `activity` in the status file when no `Progress` step is set: `<host> #<requests so far> <failed>✗`
with `activity_started` (the moment the current request was sent). Updated when a request starts and when it ends.
`statusline.py` renders `🥾 <tool> · <host> #7 4✗ · 0:45 · total 5:40` when there is no `step_title`; with a step the
line is unchanged.

## 3. `statusline.py --check` / `--install`

- Settings file: `$CLAUDE_CONFIG_DIR/settings.json`, else `~/.claude/settings.json`.
- `--check`: prints `installed` / `not installed`, exit 0 / 1. Installed = `statusLine.command` runs this `statusline.py`.
- `--install`: idempotent. Writes a copy `settings.json.bak-<UTC time>` first, keeps every other key, sets
  `statusLine = {type: command, command: "python3 <this script> --fallback '<previous command>'"}`; a previous command
  that already runs our script is not nested; no previous `statusLine` → no `--fallback`. Prints one line saying what changed.
- SKILL.md: before the first network script of a session the agent runs `--check` and, if needed, `--install`, and tells
  the user in one line. It works only in the terminal CLI.

## Testing

`ensure_started` (env folder, cache-dir folder, no folder, once per process, `OSM_HIKE_NO_LOG`), the `overpass` event of
`query_overpass`, activity in the status file and `render`, `--check`/`--install` on a temporary settings file (no file,
foreign `statusLine`, already installed, broken JSON → untouched), the two `runlog.py` copies identical.

## Risks

- `--install` edits a global file: backup first, refuse to touch a settings file that is not valid JSON.
- `routes/.logs` is not a route folder: nothing links its files to a route unless `OSM_HIKE_ROUTE_DIR` / `RunLog.start(route_dir)` was used.
