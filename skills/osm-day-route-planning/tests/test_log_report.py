import json

import log_report

EVENTS = [
    {"t": 0.0, "ev": "run_start", "tool": "plan", "argv": ["plan"]},
    {"t": 0.0, "ev": "span_start", "span": "overpass"},
    {"t": 0.1, "ev": "http", "host": "overpass-api.de", "path": "/api", "status": 504, "ok": False, "dur": 2.0,
     "t_sent": 0.1, "t_answer": 2.1, "bytes": 10, "series": "overpass", "attempt": 1},
    {"t": 5.0, "ev": "http", "host": "overpass-api.de", "path": "/api", "status": 200, "ok": True, "dur": 2.9,
     "t_sent": 2.1, "t_answer": 5.0, "bytes": 1000, "series": "overpass", "attempt": 2},
    {"t": 5.0, "ev": "http_series", "series": "overpass", "n": 2, "ok": 1, "failed": 1, "t_first_sent": 0.1,
     "t_last_answer": 5.0, "dur": 4.9, "sum_dur": 4.9, "bytes": 1010},
    {"t": 5.0, "ev": "span_end", "span": "overpass", "dur": 5.0, "ok": True},
    {"t": 5.0, "ev": "span_start", "span": "elevation"},
    {"t": 5.0, "ev": "span_start", "span": "elevation.inner"},
    {"t": 7.0, "ev": "span_end", "span": "elevation.inner", "dur": 2.0, "ok": True},
    {"t": 95.0, "ev": "http_series", "series": "elevation", "n": 91, "ok": 90, "failed": 1, "t_first_sent": 7.0,
     "t_last_answer": 95.0, "dur": 88.0, "sum_dur": 40.0, "bytes": 5000},
    {"t": 95.0, "ev": "span_end", "span": "elevation", "dur": 90.0, "ok": True},
    {"t": 95.0, "ev": "cache", "kind": "overpass", "result": "hit", "age_s": 60},
    {"t": 95.0, "ev": "cache", "kind": "overpass", "result": "miss"},
    {"t": 95.0, "ev": "warn", "msg": "overpass_failed", "params": {"endpoint": "h", "reason": "504"}},
    {"t": 96.0, "ev": "error", "msg": "plugin fire failed"},
    {"t": 100.0, "ev": "run_end", "dur": 100.0, "ok": True},
]


def test_report_has_the_total_the_span_tree_and_the_slowest_spans():
    text = log_report.report(EVENTS, top=2)
    assert "plan" in text and "100.0 s" in text and "ok" in text
    tree = text.split("Span tree")[1].split("Slowest")[0]
    assert tree.index("overpass") < tree.index("elevation") < tree.index("elevation.inner")
    assert "90.0 s" in tree and "90%" in tree                    # elevation is 90 % of the run
    assert "elevation.inner" in tree
    slowest = text.split("Slowest")[1].split("HTTP")[0]
    assert slowest.index("elevation") < slowest.index("overpass")
    assert "elevation.inner" not in slowest.split("\n", 1)[1]     # top 2 by dur: 90 s and 5 s, the 2 s span is cut


def test_report_summarises_http_per_host_and_per_series_with_the_waiting_share():
    text = log_report.report(EVENTS)
    host = next(l for l in text.splitlines() if l.strip().startswith("overpass-api.de"))
    assert "2 requests" in host and "1 failed" in host and "max 2.9" in host
    series = next(l for l in text.splitlines() if l.strip().startswith("elevation") and "wall" in l)
    assert "91 requests" in series and "wall 88.0 s" in series and "sum 40.0 s" in series and "waiting 48.0 s" in series


def test_report_lists_cache_hit_rate_warnings_and_errors():
    text = log_report.report(EVENTS)
    assert "overpass: 1 hit, 1 miss" in text
    assert "overpass_failed" in text and "plugin fire failed" in text


def test_an_unfinished_run_is_reported_not_crashed():
    text = log_report.report(EVENTS[:6])
    assert "unfinished" in text.lower()


def test_load_skips_broken_lines(tmp_path):
    path = tmp_path / "x.log.jsonl"
    path.write_text(json.dumps(EVENTS[0]) + "\n{broken\n\n" + json.dumps(EVENTS[-1]) + "\n", encoding="utf-8")
    assert [e["ev"] for e in log_report.load(path)] == ["run_start", "run_end"]


def test_main_prints_the_report(tmp_path, capsys):
    path = tmp_path / "x.log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in EVENTS), encoding="utf-8")
    assert log_report.main([str(path), "--top", "3"]) == 0
    assert "Span tree" in capsys.readouterr().out
    assert log_report.main([str(tmp_path / "missing.jsonl")]) == 1


def test_partial_or_junk_events_never_crash_the_report():
    events = [
        {"ev": "run_start"},
        {"ev": "span_end", "span": "a"},                       # no dur, no t
        {"ev": "span_end", "dur": 1.0},                        # no span name
        {"ev": "http"},                                        # no host, no dur
        {"ev": "http", "host": "h", "dur": None, "attempt": None},
        {"ev": "http_series", "series": "s"},                  # no n, dur, sum_dur
        {"ev": "cache"},
        {"ev": "warn"},
        {"ev": "error", "t": "x"},
        {"ev": "mystery"},
    ]
    text = log_report.report(events)
    assert "unfinished" in text.lower() and "Span tree" in text
    assert log_report.report([]).startswith("Run:")
