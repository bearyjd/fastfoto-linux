"""Shared pytest configuration.

``real_scans`` tests read private scans from ``test-scans/`` (gitignored, never published);
``hardware`` tests need a connected FF-680W. Both are skipped in CI — see ``tests/_skips.py``.
"""

import os
from pathlib import Path

import pytest

from fastfoto_linux.scanner import libusb, precheck, shim_trust
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


@pytest.fixture(autouse=True)
def shim_trust_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Test files live under /tmp, which anyone can write to, so the shim policy would refuse
    every one of them: its walk up the folders stops at pytest's own (private) base folder."""
    monkeypatch.setattr(shim_trust, "SHIM_TRUST_ROOT", tmp_path_factory.getbasetemp())


@pytest.fixture(autouse=True)
def no_scanner_precheck(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check before a scan talks to the scanner over USB, and a real one may be plugged in.

    Two independent locks: the check is switched off, and libusb cannot be found, so that code
    which forgot the first still cannot open a device. A test that exercises the check removes
    the first lock itself and hands it a fake transport or a fake library.
    """
    monkeypatch.setenv(precheck.SKIP_ENV_VAR, "1")
    monkeypatch.setattr(libusb, "_LIBRARY_NAMES", ())


@pytest.fixture(autouse=True)
def private_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The note "our last scan here ended badly" lives in the user's state folder, and it is the
    evidence that lets the check send filler to a silent scanner. No test may write the real one,
    or find one that happens to be there."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("state")))
