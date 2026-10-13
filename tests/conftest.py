"""Shared pytest configuration.

Tests marked ``real_scans`` read private scans from ``test-scans/`` (gitignored, never
published). They are skipped automatically when that directory is absent, e.g. in CI.
"""

import os
from pathlib import Path

import pytest

REAL_SCANS_DIR = Path(os.environ.get("FASTFOTO_REAL_SCANS", Path(__file__).parent.parent / "test-scans"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if any(REAL_SCANS_DIR.glob("*.png")):
        return
    skip = pytest.mark.skip(reason=f"private scans not found in {REAL_SCANS_DIR}")
    for item in items:
        if "real_scans" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def real_scans_dir() -> Path:
    return REAL_SCANS_DIR
