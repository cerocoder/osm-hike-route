# skills/osm-day-route-show/tests/conftest.py
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def block_real_tile_probes():
    """No test in this suite may make a real network call for tile-provider
    coverage probing. A test that needs specific probe/covers() behavior
    patches tile_providers.probe._fetch or tile_providers.providers.base.
    probe_tile itself, which takes precedence over this outer patch for
    the duration of that test. This is a safety net, not the primary
    mocking mechanism — a final whole-branch review caught a pre-existing
    test making live DNS calls with no guard in place."""
    with patch(
        "tile_providers.probe._fetch",
        side_effect=RuntimeError(
            "real network access attempted in tests — patch "
            "tile_providers.probe._fetch or tile_providers.providers.base.probe_tile "
            "explicitly in this test"
        ),
    ):
        yield
