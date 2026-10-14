"""CLI test fixtures. A scanner may be attached while these run: nothing may reach it."""

from pathlib import Path

import pytest

from tests.cli.fakes import FakeTransport, block_hardware, spy_process_pages


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
