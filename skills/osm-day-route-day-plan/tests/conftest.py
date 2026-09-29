import datetime
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def block_real_network():
    """No test may touch the network. Tests pass a fake `http` callable via
    the context; a test of the real helper patches day_plan.http._open
    itself, which takes precedence over this outer patch."""
    with patch("day_plan.http._open", side_effect=RuntimeError("real network access attempted in tests")):
        yield


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Overpass retries pause between rounds; tests must never wait for real."""
    monkeypatch.setattr("day_plan.overpass._default_sleep", lambda seconds: None)


@pytest.fixture
def make_route(tmp_path):
    """Writes a minimal route.geojson (London-ish, 3D coords) and returns the folder."""
    def _make(name="Test route", mode="walk", duration_hours=5.0, distance_km=15.0,
              coords=((-0.20, 51.45, 30.0), (-0.05, 51.55, 60.0)), folder="route"):
        route_dir = tmp_path / folder
        route_dir.mkdir()
        geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
            "properties": {"name": name, "mode": mode, "distance_km": distance_km,
                           "duration_estimate_hours": duration_hours},
        }]}
        (route_dir / "route.geojson").write_text(json.dumps(geojson), encoding="utf-8")
        return route_dir
    return _make


@pytest.fixture
def weather_response():
    """Factory for an Open-Meteo hourly response for one date. Every hour
    gets the same values unless `overrides` maps a variable name to either a
    scalar (all hours) or a {hour: value} dict."""
    def _make(date="2026-06-21", utc_offset_seconds=3600, timezone=None, **overrides):
        base = {
            "temperature_2m": 18.0, "apparent_temperature": 17.0, "precipitation": 0.0,
            "precipitation_probability": 10, "cloud_cover": 40, "visibility": 24000.0,
            "weather_code": 1, "wind_speed_10m": 3.0, "wind_direction_10m": 270,
            "wind_gusts_10m": 6.0, "snow_depth": 0.0,
        }
        hourly = {"time": [f"{date}T{h:02d}:00" for h in range(24)]}
        for var, default in base.items():
            spec = overrides.get(var, default)
            hourly[var] = [spec.get(h, default) if isinstance(spec, dict) else spec for h in range(24)]
        response = {"utc_offset_seconds": utc_offset_seconds, "hourly": hourly}
        if timezone:
            response["timezone"] = timezone
        return response
    return _make


@pytest.fixture
def fixed_now():
    return datetime.datetime(2026, 6, 20, 12, 0, tzinfo=datetime.timezone.utc)
