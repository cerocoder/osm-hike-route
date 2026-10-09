#!/usr/bin/env python3
"""Text report of a run log (<tool>-<time>.log.jsonl): where did the time go?

    python3 log_report.py routes/<slug>-<date>/plan-20261009T101500.log.jsonl [--top 10]

Sections: run summary, span tree (time and share of the run), slowest spans, HTTP per host and per series
(wall time first-sent -> last-answer, sum of single times, the waiting between requests), cache, warnings and errors.
A log of a killed run or with partial events is reported as far as it goes, never an exception.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path) -> list:
    events = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _num(value, default=0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _s(value) -> str:
    return f"{_num(value):.1f} s"


def _dur(event) -> float:
    return _num(event.get("dur"))


def _tree_order(span) -> tuple:
    """By start time (t - dur); a parent that starts at the same moment as its child goes first."""
    return round(_num(span.get("t")) - _dur(span), 3), str(span.get("span", "?")).count(".")


def report(events: list, top: int = 10) -> str:
    start = next((e for e in events if e.get("ev") == "run_start"), {})
    end = next((e for e in reversed(events) if e.get("ev") == "run_end"), None)
    total = _dur(end) if end else max((_num(e.get("t")) for e in events), default=0.0)
    state = "ok" if end and end.get("ok") else ("FAILED" if end else "unfinished (no run_end: the run was killed or is still going)")
    out = [f"Run: {start.get('tool', '?')}  total {_s(total)}  {state}"]
    if start.get("argv"):
        out.append("argv: " + " ".join(map(str, start["argv"])))

    spans = [e for e in events if e.get("ev") == "span_end"]
    out.append("")
    out.append("Span tree")
    for span in sorted(spans, key=_tree_order):
        name = str(span.get("span", "?"))
        share = 100 * _dur(span) / total if total else 0
        flag = "" if span.get("ok", True) else f"  FAILED: {span.get('error', '')}"
        out.append(f"{'  ' * (name.count('.') + 1)}{name}  {_s(_dur(span))}  {share:.0f}%{flag}")

    out.append("")
    out.append(f"Slowest spans (top {top})")
    for span in sorted(spans, key=lambda e: -_dur(e))[:max(top, 0)]:
        out.append(f"  {span.get('span', '?')}  {_s(_dur(span))}")

    out.append("")
    out.append("HTTP per host")
    hosts = defaultdict(list)
    for call in (e for e in events if e.get("ev") == "http"):
        hosts[str(call.get("host", "?"))].append(call)
    for host, items in sorted(hosts.items(), key=lambda kv: -sum(_dur(c) for c in kv[1])):
        failed = sum(1 for c in items if not c.get("ok", True))
        retries = sum(1 for c in items if _num(c.get("attempt"), 1) > 1)
        out.append(f"  {host}  {len(items)} requests, {failed} failed, {retries} retries, "
                   f"total {_s(sum(_dur(c) for c in items))}, max {max(_dur(c) for c in items):.1f} s, "
                   f"{sum(int(_num(c.get('bytes'))) for c in items)} bytes")

    out.append("")
    out.append("HTTP series (wall time first request sent -> last answer)")
    for s in sorted((e for e in events if e.get("ev") == "http_series"), key=lambda e: -_dur(e)):
        waiting = max(0.0, _dur(s) - _num(s.get("sum_dur")))
        out.append(f"  {s.get('series', '?')}  {int(_num(s.get('n')))} requests, {int(_num(s.get('failed')))} failed, "
                   f"wall {_s(_dur(s))}, sum {_s(s.get('sum_dur'))}, waiting {_s(waiting)}, "
                   f"{int(_num(s.get('bytes')))} bytes")

    cache = defaultdict(lambda: defaultdict(int))
    for e in events:
        if e.get("ev") == "cache":
            cache[str(e.get("kind", "?"))][str(e.get("result", "?"))] += 1
    if cache:
        out.append("")
        out.append("Cache")
        for kind, results in cache.items():
            out.append(f"  {kind}: " + ", ".join(f"{n} {name}" for name, n in sorted(results.items())))

    problems = [e for e in events if e.get("ev") in ("warn", "error")]
    if problems:
        out.append("")
        out.append("Warnings and errors")
        for e in problems:
            extra = f" {e['params']}" if e.get("params") else ""
            out.append(f"  [{_num(e.get('t')):.1f} s] {e['ev']}: {e.get('msg', '')}{extra}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        events = load(args.log)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(report(events, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
