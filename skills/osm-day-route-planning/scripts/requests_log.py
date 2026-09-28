"""Journal of verbatim user requests per route, one entry per planning
iteration (spec §3.1). Read at the start of any revision so a later
session/agent sees the full accumulated context, not just the last ask."""
import json
from datetime import datetime, timezone
from pathlib import Path

_ENTRY_MARKER = "<!-- requests_log entry: "


def _escape_html_markers(text: str) -> str:
    """Escape HTML comment markers in visible text to prevent parsing collision.

    The JSON payload (entry dict) preserves the original text; this escaping
    only affects the human-readable Markdown rendering and prevents fake
    marker lines from corrupting the parse.
    """
    text = text.replace("<!--", "&lt;!--")
    text = text.replace("-->", "--&gt;")
    return text


def append_request(route_dir: Path, request_text: str, summary: str) -> int:
    route_dir = Path(route_dir)
    route_dir.mkdir(parents=True, exist_ok=True)
    path = route_dir / "requests.md"
    existing = read_requests(route_dir)
    iteration = len(existing) + 1
    entry = {
        "iteration": iteration,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": request_text,
        "summary": summary,
    }
    # Escape HTML markers in visible text to prevent fake marker injection
    escaped_request = _escape_html_markers(request_text)
    escaped_summary = _escape_html_markers(summary)
    block = (
        f"\n## Итерация {iteration} ({entry['timestamp']})\n\n"
        f"> {escaped_request}\n\n"
        f"Изменения: {escaped_summary}\n\n"
        f"{_ENTRY_MARKER}{json.dumps(entry, ensure_ascii=False)} -->\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(block)
    return iteration


def read_requests(route_dir: Path) -> list[dict]:
    path = Path(route_dir) / "requests.md"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(_ENTRY_MARKER):
            raw_json = line[len(_ENTRY_MARKER):].rsplit("-->", 1)[0].strip()
            try:
                entries.append(json.loads(raw_json))
            except json.JSONDecodeError:
                # Skip malformed entries instead of crashing the entire journal
                continue
    return entries
