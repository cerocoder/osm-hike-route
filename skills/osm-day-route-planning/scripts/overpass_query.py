#!/usr/bin/env python3
"""Overpass API helper: query + haversine length calc.

Standard-library only (urllib), no pip dependencies required.

Usage:
    python3 overpass_query.py '<overpass QL query>'

Or import:
    from overpass_query import query_overpass, route_length_m
"""
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# A plain, non-browser User-Agent is required: overpass-api.de's WAF
# 406s ordinary browser UA strings.
HEADERS = {
    "User-Agent": "research-script/1.0",
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
}


CACHE_MAX_AGE_S = 24 * 3600          # OSM changes slowly, but a closure matters: a cached answer is at most a day old
CACHE_PRUNE_AGE_S = 7 * 24 * 3600   # older entries are deleted whenever a new one is written


def _cache_file(cache_dir, ql: str) -> Path:
    """The query text holds the centre, the radius and the tag patterns, so its hash is the whole key."""
    return Path(cache_dir) / "overpass" / (hashlib.sha256(ql.encode("utf-8")).hexdigest() + ".json")


def _read_cache(path: Path, max_age_s: float):
    """(answer, age_seconds) of a fresh, readable entry; None for a missing, expired or malformed one."""
    try:
        age = time.time() - path.stat().st_mtime
        if age < 0 or age > max_age_s:                      # a file from the future (clock stepped back) is not fresh
            return None
        answer = json.loads(path.read_text(encoding="utf-8"))
        return (answer, age) if isinstance(answer, dict) else None
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, result: dict) -> None:
    """Atomic (temporary file, then rename); a failure to cache never fails the query."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")      # a name of its own per writer
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(result))
        os.replace(temporary, path)
        temporary = None
        cutoff = time.time() - CACHE_PRUNE_AGE_S
        for old in list(path.parent.glob("*.json")) + list(path.parent.glob("*.tmp")):
            if old != path and old.stat().st_mtime < cutoff:
                old.unlink()
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _host(endpoint: str) -> str:
    return urllib.parse.urlparse(endpoint).netloc or endpoint


def query_overpass(ql: str, timeout: int = 90, retries: int = 2, cache_dir=None,
                   max_age_s: float = CACHE_MAX_AGE_S, refresh: bool = False, progress=None) -> dict:
    """Run an Overpass QL query, trying each endpoint, retrying on
    5xx/timeout-body responses. Raises RuntimeError if all attempts fail.

    With `cache_dir` the answer is kept in <cache_dir>/overpass/ and a fresh one (younger than `max_age_s`) is
    returned without a request; `refresh=True` skips the read. `progress` (optional: see progress.py) is told about
    a cache hit, every retry or endpoint switch and every failed attempt."""
    cache_path = _cache_file(cache_dir, ql) if cache_dir is not None else None
    if cache_path is not None and not refresh:
        cached = _read_cache(cache_path, max_age_s)
        if cached is not None:
            if progress is not None:
                progress.note("overpass_cache_hit", age=int(cached[1] // 3600))
            return cached[0]
    body = urllib.parse.urlencode({"data": ql}).encode()
    last_error = None
    for endpoint_index, endpoint in enumerate(ENDPOINTS):
        for attempt in range(retries):
            if progress is not None and (endpoint_index, attempt) != (0, 0):
                progress.note("overpass_attempt", endpoint=_host(endpoint), n=attempt + 1, m=retries)
            try:
                req = urllib.request.Request(endpoint, data=body, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if resp.status != 200:
                        last_error = f"{endpoint}: HTTP {resp.status}"
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    if "runtime error" in text.lower() or "timeout" in text.lower() and text.lstrip().startswith("<"):
                        last_error = f"{endpoint}: server-side timeout/error body"
                        time.sleep(2)
                        continue
                    result = json.loads(text)
                    if cache_path is not None:
                        _write_cache(cache_path, result)
                    return result
            except Exception as e:
                last_error = f"{endpoint}: {e}"
                if progress is not None:
                    progress.warn("overpass_failed", endpoint=_host(endpoint), reason=" ".join(str(e).split())[:80])
                time.sleep(2)
    raise RuntimeError(f"Overpass query failed on all endpoints/attempts: {last_error}")


def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def route_length_m(elements) -> float:
    """elements: list of Overpass relation members (from 'out geom;')
    or a flat list of way elements, each with a 'geometry' field."""
    total = 0.0
    for member in elements:
        geom = member.get("geometry")
        if not geom:
            continue
        for i in range(len(geom) - 1):
            total += haversine(geom[i]["lat"], geom[i]["lon"], geom[i + 1]["lat"], geom[i + 1]["lon"])
    return total


def build_curated_routes_query(lat: float, lon: float, radius_m: int, route_tags: list[str]) -> str:
    """spec §3.10 — walk passes route_tags=['hiking','foot'], bike passes
    ['bicycle','mtb']. Geometry is never used, only the count, so this
    query only asks Overpass to count, not to return full geometry."""
    tags_pattern = "|".join(route_tags)
    return f"""
    [out:json][timeout:25];
    relation["route"~"{tags_pattern}"](around:{radius_m},{lat},{lon});
    out count;
    """


def count_curated_routes(result: dict) -> int:
    """Extract the relations count from an Overpass 'out count;' response.
    The response contains a single element with type='count' and tags.relations field."""
    for el in result.get("elements", []):
        if el.get("type") == "count":
            try:
                return int(el.get("tags", {}).get("relations", 0))
            except (TypeError, ValueError):
                return 0
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 overpass_query.py '<overpass QL query>'", file=sys.stderr)
        sys.exit(1)
    result = query_overpass(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
