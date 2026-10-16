"""CLI test fixtures. A scanner may be attached while these run: nothing may reach it."""

from pathlib import Path

import pytest

from fastfoto_linux.session import raw as rawdir
from tests import _fake_ocrmypdf as fake_ocr
from tests.cli.doc_scan_helpers import STAMP
from tests.cli.fakes import FakeTransport, block_hardware, spy_process_pages
from tests.documents.scan_fakes import DocTransport


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch: pytest.MonkeyPatch) -> None:
    block_hardware(monkeypatch)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    fake = FakeTransport()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch):
    return spy_process_pages(monkeypatch)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root


@pytest.fixture
def doc_transport(monkeypatch: pytest.MonkeyPatch) -> DocTransport:
    fake = DocTransport()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ffscan doc scan`` never runs a real ``ocrmypdf``, even on a machine that has one."""
    fake_ocr.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


@pytest.fixture
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kept raw pages go to a folder named after the time; pin it (``doc_scan_helpers.STAMP``)."""
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)
