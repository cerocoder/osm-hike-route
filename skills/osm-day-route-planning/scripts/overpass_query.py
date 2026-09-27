#!/usr/bin/env python3
"""Overpass API helper: query + haversine length calc.

Standard-library only (urllib), no pip dependencies required.

Usage:
    python3 overpass_query.py '<overpass QL query>'

Or import:
    from overpass_query import query_overpass, route_length_m
"""
import json
import math
import sys
import time
import urllib.request
import urllib.parse

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


def query_overpass(ql: str, timeout: int = 90, retries: int = 2) -> dict:
    """Run an Overpass QL query, trying each endpoint, retrying on
    5xx/timeout-body responses. Raises RuntimeError if all attempts fail."""
    body = urllib.parse.urlencode({"data": ql}).encode()
    last_error = None
    for endpoint in ENDPOINTS:
        for attempt in range(retries):
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
                    return json.loads(text)
            except Exception as e:
                last_error = f"{endpoint}: {e}"
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 overpass_query.py '<overpass QL query>'", file=sys.stderr)
        sys.exit(1)
    result = query_overpass(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
