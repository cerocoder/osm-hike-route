# One-off run log, activity status, statusline install — plan

**Spec:** `docs/superpowers/specs/2026-10-09-adhoc-run-log-and-statusline-install-design.md`
**Tests:** `cd skills && python3 -m pytest -q osm-day-route-planning/tests osm-day-route-day-plan/tests`
**Constraint:** the two `runlog.py` copies stay byte-identical (edit the planning one, copy to `day_plan/runlog.py`).

- [x] 1. `runlog.py`: `ensure_started(cache_dir)`, `RunLog.start(..., **context)` into `run_start`, adhoc close at exit; tests.
- [x] 2. Wire `ensure_started` into `query_overpass`, `ElevationService`, public geometry; `overpass` event in `query_overpass`; tests; autouse `OSM_HIKE_NO_LOG` in both conftests.
- [x] 3. `runlog.py`: `activity` in the status file; `statusline.render` without a step; tests.
- [x] 4. `statusline.py --check` / `--install`; tests on temporary settings files.
- [x] 5. `log_report.py`: show `adhoc` runs (script, cwd) and the `overpass` events of the planner; test.
- [x] 6. SKILL.md (planning + day-plan), README, spec of the run log: the rules above. Full suite green.
