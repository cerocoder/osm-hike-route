#!/usr/bin/env python3
"""Hard gate on archive completeness (spec §3.11).

Exists because the pipeline in SKILL.md is prose an agent follows, not code
that enforces itself — nothing stops an agent from hand-writing route.geojson
instead of calling build_geojson, and reasoning-in-the-moment ("network
access looked unavailable, I'll just skip elevation") produces an archive
that looks done but silently has no elevation, no distance, no duration.
That happened for real (routes/cerros-de-la-maranosa-2026-09-28, 2026-09):
route.geojson shipped with 2D LineString coordinates and none of the
computed LineString properties, plus no weights.json/requests.md, because
the archive was written directly rather than through
build_geojson/save_weights/append_request. This validator turns that outcome
into a raised exception (or a nonzero exit code from the CLI) instead of a
gap a user has to notice on their own.

Usage:
    python3 archive_validate.py <route_dir>

Or import:
    from archive_validate import validate_archive, ArchiveIncompleteError
"""
import json
import sys
from pathlib import Path

REQUIRED_ARCHIVE_FILES = ("route.geojson", "weights.json", "requests.md", "notes.md")

REQUIRED_LINE_PROPERTIES = (
    "name", "mode", "style", "distance_km", "elevation_gain_m",
    "elevation_loss_m", "duration_estimate_hours", "duration_warning",
    "curated_routes_count", "is_loop", "skipped_interest_points",
)

_VALID_MODES = {"walk", "bike"}
_NUMERIC_PROPERTIES = ("distance_km", "elevation_gain_m", "elevation_loss_m", "duration_estimate_hours")


class ArchiveIncompleteError(Exception):
    pass


def validate_archive(route_dir) -> None:
    """Raises ArchiveIncompleteError listing every problem found, not just
    the first — a hand-written/skipped-pipeline archive usually fails
    several checks at once, and surfacing them together saves a re-run per
    fix."""
    route_dir = Path(route_dir)
    problems = []

    for filename in REQUIRED_ARCHIVE_FILES:
        if not (route_dir / filename).exists():
            problems.append(f"отсутствует {filename}")

    geojson = _load_json(route_dir / "route.geojson", problems)
    if geojson is not None:
        problems.extend(_validate_geojson(geojson))

    weights = _load_json(route_dir / "weights.json", problems)
    if isinstance(weights, dict) and "mode" not in weights:
        problems.append("weights.json не содержит 'mode'")

    if problems:
        details = "\n".join(f"  - {p}" for p in problems)
        raise ArchiveIncompleteError(
            f"Архив {route_dir} неполный ({len(problems)} проблем) — "
            f"маршрут нельзя считать готовым:\n{details}"
        )


def _load_json(path: Path, problems: list) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        problems.append(f"{path.name} не парсится как JSON: {exc}")
        return None


def _validate_geojson(geojson: dict) -> list[str]:
    problems = []
    features = geojson.get("features")
    if not isinstance(features, list):
        return ["route.geojson: нет списка 'features'"]

    lines = [f for f in features if f.get("geometry", {}).get("type") == "LineString"]
    if len(lines) != 1:
        problems.append(f"ожидается ровно один LineString-feature маршрута, найдено {len(lines)}")
        return problems  # nothing else to check meaningfully without exactly one line

    line = lines[0]
    coords = line.get("geometry", {}).get("coordinates") or []
    if not coords:
        problems.append("LineString маршрута пуст")
    elif any(len(c) != 3 for c in coords):
        problems.append(
            "координаты LineString не 3D — build_geojson всегда добавляет "
            "высоту (подставляя 0.0, когда она неизвестна), так что 2D "
            "координаты означают, что route.geojson был собран в обход "
            "build_geojson, минуя elevation-пайплайн (Pipeline step 12)"
        )

    props = line.get("properties", {})
    missing = [key for key in REQUIRED_LINE_PROPERTIES if key not in props]
    if missing:
        problems.append(
            "в properties LineString отсутствуют вычисляемые поля: "
            f"{', '.join(missing)} — похоже, соответствующий шаг пайплайна "
            "(elevation/duration/distance/etc.) не выполнялся, а не просто "
            "дал пустой результат"
        )

    if "mode" in props and props["mode"] not in _VALID_MODES:
        problems.append(f"mode={props['mode']!r} — ожидается 'walk' или 'bike'")

    for key in _NUMERIC_PROPERTIES:
        if key in props and not isinstance(props[key], (int, float)):
            problems.append(f"{key}={props[key]!r} — ожидалось число")

    if "is_loop" in props and not isinstance(props["is_loop"], bool):
        problems.append(f"is_loop={props['is_loop']!r} — ожидался bool")

    if "skipped_interest_points" in props and not isinstance(props["skipped_interest_points"], list):
        problems.append(f"skipped_interest_points={props['skipped_interest_points']!r} — ожидался список")

    if "segments" in props:
        problems.extend(_validate_segments(props["segments"], len(coords)))

    return problems


def _validate_segments(segments, vertex_count: int) -> list[str]:
    """segments (the road each part of the route runs on) is optional — archives saved before it existed have none —
    but when present its ranges must cover the LineString vertices exactly, otherwise a consumer would read the
    wrong road for a part of the route."""
    if not isinstance(segments, list) or not segments:
        return [f"segments={segments!r} — ожидался непустой список"]
    problems = []
    expected_from = 0
    for index, segment in enumerate(segments):
        start, end = (segment.get("from"), segment.get("to")) if isinstance(segment, dict) else (None, None)
        if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool) or isinstance(end, bool):
            problems.append(f"segments[{index}]: 'from' и 'to' должны быть целыми числами")
            return problems
        if start != expected_from or end <= start:
            problems.append(
                f"segments[{index}]: диапазон {start}..{end} не продолжает предыдущий "
                f"(ожидалось from={expected_from}, to > from)")
            return problems
        expected_from = end
    if vertex_count and expected_from != vertex_count - 1:
        problems.append(
            f"segments покрывают вершины 0..{expected_from}, а в LineString {vertex_count} вершин "
            f"(последний индекс должен быть {vertex_count - 1})")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 archive_validate.py <route_dir>", file=sys.stderr)
        sys.exit(2)
    try:
        validate_archive(sys.argv[1])
    except ArchiveIncompleteError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"OK: {sys.argv[1]} — архив полный.")
