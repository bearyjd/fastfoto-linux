"""Shared pytest configuration.

``real_scans`` tests read private scans from ``test-scans/`` (gitignored, never published);
``hardware`` tests need a connected FF-680W. Both are skipped in CI — see ``tests/_skips.py``.
"""

import os
from pathlib import Path

import pytest

from tests._skips import scans_dir_from_env, skip_reason

REAL_SCANS_DIR = scans_dir_from_env(os.environ, Path(__file__).parent.parent / "test-scans")
GATED_MARKERS = ("real_scans", "hardware")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        for marker in GATED_MARKERS:
            if item.get_closest_marker(marker) is None:
                continue
            reason = skip_reason(marker, os.environ, REAL_SCANS_DIR)
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def real_scans_dir() -> Path:
    return REAL_SCANS_DIR
