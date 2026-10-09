#!/usr/bin/env python3
"""Text report of a run log (<tool>-<time>.log.jsonl): where did the time go?

    python3 log_report.py routes/<slug>-<date>/plan-20261009T101500.log.jsonl [--top 10]

Sections: run summary, span tree (time and share of the run; time outside any top-level span; plugins that ran
with no data or failed are marked), slowest spans, plugins (outcome, where the data came from, HTTP and cache use),
Overpass queries (size, timeout, area, elements, mirror, tries), HTTP per host and per series (wall time
first-sent -> last-answer, sum of single times, the waiting between requests), cache (hits, misses, stale), warnings
and errors.
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


def _bytes(n) -> str:
    """', N bytes', or nothing when no size was recorded (some callers cannot see the raw answer)."""
    return f", {n} bytes" if n else ""


def report(events: list, top: int = 10) -> str:
    start = next((e for e in events if e.get("ev") == "run_start"), {})
    end = next((e for e in reversed(events) if e.get("ev") == "run_end"), None)
    total = _dur(end) if end else max((_num(e.get("t")) for e in events), default=0.0)
    state = "ok" if end and end.get("ok") else ("FAILED" if end else "unfinished (no run_end: the run was killed or is still going)")
    out = [f"Run: {start.get('tool', '?')}  total {_s(total)}  {state}"]
    if start.get("argv"):
        out.append("argv: " + " ".join(map(str, start["argv"])))
    if start.get("adhoc"):
        out.append(f"adhoc run (the script did not start a log itself): script {start.get('script', '?')}, "
                   f"cwd {start.get('cwd', '?')}")

    spans = [e for e in events if e.get("ev") == "span_end"]
    results = {str(e.get("plugin")): e for e in events if e.get("ev") == "plugin_result"}
    out.append("")
    out.append("Span tree")
    for span in sorted(spans, key=_tree_order):
        name = str(span.get("span", "?"))
        share = 100 * _dur(span) / total if total else 0
        flag = "" if span.get("ok", True) else f"  FAILED: {span.get('error', '')}"
        result = results.get(name.rsplit(".", 1)[-1]) if name.startswith("plugins.") else None
        if result and result.get("outcome") not in (None, "ok"):
            flag += f"  {str(result['outcome']).upper()}"
        out.append(f"{'  ' * (name.count('.') + 1)}{name}  {_s(_dur(span))}  {share:.0f}%{flag}")
    outside = total - sum(_dur(e) for e in spans if "." not in str(e.get("span", "?")))
    if spans and total and outside / total >= 0.02:
        out.append(f"  (outside any top-level span)  {_s(outside)}  {100 * outside / total:.0f}%")

    out.append("")
    out.append(f"Slowest spans (top {top})")
    for span in sorted(spans, key=lambda e: -_dur(e))[:max(top, 0)]:
        out.append(f"  {span.get('span', '?')}  {_s(_dur(span))}")

    if results:
        out.append("")
        out.append("Plugins (in the order they ran)")
        durations = {str(e.get("span")): _dur(e) for e in spans}
        for name, e in results.items():
            used = ", ".join(f"{k.replace('_', ' ')} {int(_num(e[k]))}" for k in
                             ("http_ok", "http_failed", "cache_hit", "cache_miss", "cache_stale") if e.get(k))
            reason = f"  ({e['reason']})" if e.get("reason") else ""
            out.append(f"  {name}  {_s(durations.get('plugins.' + name))}  {e.get('outcome', '?')}, "
                       f"data from {e.get('source', '?')}{', ' + used if used else ''}{reason}")

    queries = [e for e in events if e.get("ev") == "overpass"]
    if queries:
        out.append("")
        out.append("Overpass queries")
        for e in queries:
            where = str(e.get("span") or "-")
            size = f"{int(_num(e.get('ql_bytes')))} B"
            if e.get("timeout_s") is not None:
                size += f", timeout {int(_num(e['timeout_s']))} s"
            if e.get("radius_m") is not None:
                size += f", radius {int(_num(e['radius_m']))} m"
            if e.get("bbox_km2") is not None:
                size += f", bbox {_num(e['bbox_km2']):.1f} km2"
            tail = (f"{int(_num(e.get('elements')))} elements from {e.get('mirror', '?')}" if e.get("ok", True)
                    else f"FAILED: {e.get('error', '')}")
            out.append(f"  [{_num(e.get('t')):.1f} s] {where}  query {size}; {int(_num(e.get('tries')))} "
                       f"mirror tries; {tail}")

    out.append("")
    out.append("HTTP per host")
    hosts = defaultdict(list)
    for call in (e for e in events if e.get("ev") == "http"):
        hosts[str(call.get("host", "?"))].append(call)
    for host, items in sorted(hosts.items(), key=lambda kv: -sum(_dur(c) for c in kv[1])):
        failed = sum(1 for c in items if not c.get("ok", True))
        retries = sum(1 for c in items if _num(c.get("attempt"), 1) > 1)
        out.append(f"  {host}  {len(items)} requests, {failed} failed, {retries} retries, "
                   f"total {_s(sum(_dur(c) for c in items))}, max {max(_dur(c) for c in items):.1f} s"
                   f"{_bytes(sum(int(_num(c.get('bytes'))) for c in items))}")

    out.append("")
    out.append("HTTP series (wall time first request sent -> last answer)")
    series = [e for e in events if e.get("ev") == "http_series"]
    owners = {(e.get("span"), e.get("n"), e.get("failed"), e.get("bytes"), e.get("dur")) for e in series
              if e.get("series") == e.get("span")}
    for s in sorted(series, key=lambda e: -_dur(e)):
        name = s.get("series", "?")
        if name != s.get("span") and (s.get("span"), s.get("n"), s.get("failed"), s.get("bytes"), s.get("dur")) in owners:
            continue                                            # the same requests, already listed under their span
        label = f"{name} in {s['span']}" if s.get("span") and name != s.get("span") else name
        waiting = max(0.0, _dur(s) - _num(s.get("sum_dur")))
        out.append(f"  {label}  {int(_num(s.get('n')))} requests, {int(_num(s.get('failed')))} failed, "
                   f"wall {_s(_dur(s))}, sum {_s(s.get('sum_dur'))}, waiting {_s(waiting)}"
                   f"{_bytes(int(_num(s.get('bytes'))))}")

    cache = defaultdict(lambda: defaultdict(int))
    ages = defaultdict(list)
    for e in events:
        if e.get("ev") == "cache":
            kind = str(e.get("kind", "?"))
            cache[kind][str(e.get("result", "?"))] += 1
            if e.get("result") in ("hit", "stale") and e.get("age_s") is not None:
                ages[kind].append(_num(e["age_s"]))
    if cache:
        out.append("")
        out.append("Cache")
        for kind, outcomes in cache.items():
            old = f" (oldest entry {max(ages[kind]) / 3600:.1f} h)" if ages[kind] else ""
            out.append(f"  {kind}: " + ", ".join(f"{n} {name}" for name, n in sorted(outcomes.items())) + old)

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
