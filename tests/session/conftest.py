"""Session test fixtures. A scanner may be attached while these run: nothing may reach it."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.pipeline.process import ProcessSettings
from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import RawPolicy, ScanRequest, Stage, run_session
from fastfoto_linux.session import raw as session_raw
from tests.cli.fakes import DEVICE, FakeTransport, refuse
from tests.process_helpers import settings_for

STAMP = "20261013T230000Z"
DPI = 300


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real scan function is what a session uses unless a test hands it another one."""
    monkeypatch.setattr("fastfoto_linux.session.run.run_scan", refuse)


@pytest.fixture(autouse=True)
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_raw, "utc_stamp", lambda: STAMP)


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root


def make_request(
    out: Path,
    *,
    policy: RawPolicy = RawPolicy.AUTO,
    duplex: bool = True,
    raw_parent: Path | None = None,
    **settings: Any,
) -> ScanRequest:
    """A request for a face-down duplex batch into ``out`` unless overridden.

    Backs are never kept or dropped by default, so that a plain sheet is a clean run; pass
    ``back_policy=BackPolicy.AUTO`` to have blank backs dropped.
    """
    process_settings: ProcessSettings = settings_for(
        out, duplex=duplex, **{"back_policy": BackPolicy.NEVER, **settings}
    )
    return ScanRequest(
        target=ScanTarget(device=DEVICE),
        dpi=DPI,
        duplex=duplex,
        settings=process_settings,
        raw_policy=policy,
        raw_parent=raw_parent,
    )


class Events:
    """Everything the callbacks of one session were told, in order."""

    def __init__(self) -> None:
        self.pages: list[int] = []
        self.photos: list[Any] = []
        self.stages: list[Stage] = []

    def callbacks(self) -> dict[str, Callable[..., None]]:
        return {
            "on_page": self.pages.append,
            "on_photo": self.photos.append,
            "on_stage": self.stages.append,
        }


def run(request: ScanRequest, transport: FakeTransport, **options: Any):
    """``run_session`` with the fake scanner transport."""
    return run_session(request, scan=transport.run_scan, **options)


def raw_leftovers(root: Path) -> list[str]:
    """The raw folders in ``root``: the temporary ones and ``.raw``."""
    return sorted(
        p.name
        for p in root.iterdir()
        if p.name == session_raw.KEPT_DIR_NAME or p.name.startswith(session_raw.TEMP_PREFIX)
    )


def kept_names(path: Path | None) -> list[str]:
    return sorted(p.name for p in path.iterdir()) if path is not None else []
