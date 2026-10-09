import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


import pytest


@pytest.fixture(autouse=True)
def isolated_runlog(tmp_path, monkeypatch):
    """No test may write to the real ~/.cache status folder or leak an installed run log into the next test."""
    monkeypatch.setenv("OSM_HIKE_STATUS_DIR", str(tmp_path / "_status"))
    monkeypatch.setenv("OSM_HIKE_NO_LOG", "1")           # no adhoc log started behind a test's back (see runlog.ensure_started)
    monkeypatch.delenv("OSM_HIKE_ROUTE_DIR", raising=False)
    yield
    import runlog
    runlog.install(None)
