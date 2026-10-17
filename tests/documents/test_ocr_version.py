"""Which ocrmypdf will run: the version of the app's own module or what the program says, asked
(an answer is remembered, a failure is asked again), and what that version accepts."""

import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_version
from fastfoto_linux.documents.ocr_version import accepts_rasterizer, ocrmypdf_version
from tests import _fake_ocrmypdf as fake


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


# ---- the app's own module -------------------------------------------------------------------


def test_the_module_version_is_the_installed_distributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def installed(name: str) -> str:
        asked.append(name)
        return "17.13.0"

    monkeypatch.setattr(ocr_version, "metadata_version", installed)
    assert ocrmypdf_version(sys.executable) == "17.13.0"
    assert asked == ["ocrmypdf"]


def test_a_module_without_metadata_has_no_known_version() -> None:
    assert ocrmypdf_version(sys.executable) is None  # tests/conftest.py: not installed


# ---- a program --------------------------------------------------------------------------------


def test_a_program_is_asked_for_its_version(
    fake_on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.configure(monkeypatch, version="16.4.3")
    assert ocrmypdf_version(str(fake_on_path)) == "16.4.3"


def test_the_version_is_asked_once_per_program(
    fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "version.log"
    fake.configure(monkeypatch, version="17.13.0", version_log=str(log))
    assert ocrmypdf_version(str(fake_on_path)) == "17.13.0"
    assert ocrmypdf_version(str(fake_on_path)) == "17.13.0"
    assert log.read_text(encoding="utf-8").splitlines() == ["asked"]


@pytest.mark.parametrize(
    ("printed", "version"),
    [("16.4.3\n", "16.4.3"), ("ocrmypdf 17.0.1\n", "17.0.1"), ("17.13.0.dev3+gabc\n", "17.13.0")],
)
def test_the_version_is_read_from_the_first_number_it_prints(
    fake_on_path: Path, monkeypatch: pytest.MonkeyPatch, printed: str, version: str
) -> None:
    fake.configure(monkeypatch, version_text=printed.strip())
    assert ocrmypdf_version(str(fake_on_path)) == version


def test_a_program_that_prints_no_version_has_an_unknown_one(
    fake_on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.configure(monkeypatch, version_text="no idea")
    assert ocrmypdf_version(str(fake_on_path)) is None


def test_a_program_that_cannot_be_started_has_an_unknown_version_and_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    assert ocrmypdf_version("/nonexistent/ocrmypdf") is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_program_that_does_not_answer_is_given_up_on(
    fake_on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_version, "VERSION_TIMEOUT_S", 0.5)
    fake.configure(monkeypatch, version_hang=True)
    assert ocrmypdf_version(str(fake_on_path)) is None


def test_a_program_that_hangs_is_stopped_with_everything_it_started(
    fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    monkeypatch.setattr(ocr_version, "VERSION_TIMEOUT_S", 2.0)  # time to start the grandchild
    fake.configure(monkeypatch, version_hang=True, version_child=str(pid_file))
    try:
        assert ocrmypdf_version(str(fake_on_path)) is None
        grandchild = int(pid_file.read_text(encoding="utf-8"))
        assert fake.wait_until_gone(grandchild), (
            "the grandchild of the version probe is still alive"
        )
    finally:  # do not leave a sleeper behind when the test fails
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)


@pytest.mark.parametrize(
    "failure",
    [{"version_text": "no idea"}, {"version_hang": True}],
    ids=["no version printed", "no answer in time"],
)
def test_only_an_answer_is_remembered_a_failure_is_asked_again(
    fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: dict[str, object]
) -> None:
    monkeypatch.setattr(ocr_version, "VERSION_TIMEOUT_S", 0.5)
    log = tmp_path / "version.log"
    fake.configure(monkeypatch, version_log=str(log), **failure)
    assert ocrmypdf_version(str(fake_on_path)) is None
    fake.configure(monkeypatch, version="17.13.0", version_log=str(log))
    assert ocrmypdf_version(str(fake_on_path)) == "17.13.0"
    assert ocrmypdf_version(str(fake_on_path)) == "17.13.0"
    assert log.read_text(encoding="utf-8").splitlines() == ["asked", "asked"]


# ---- what a version accepts -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("17.0.0", True),
        ("17.13.0", True),
        ("18.1", True),
        ("100.0", True),
        ("16.4.3", False),
        ("16.99", False),
        ("9.9.9", False),
        ("", False),
        ("garbage", False),
        (None, False),  # an unknown version gets the command every version accepts
    ],
)
def test_the_rasterizer_option_is_for_version_17_and_up(
    version: str | None, accepted: bool
) -> None:
    assert accepts_rasterizer(version) is accepted
