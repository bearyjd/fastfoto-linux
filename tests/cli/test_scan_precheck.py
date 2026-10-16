"""``ffscan scan`` checks the scanner first: a stuck or busy one is exit 3, in one line."""

from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import ScannerDisconnectedError, ScannerInUseError, ScannerStuckError
from fastfoto_linux.scanner import precheck as precheck_module
from tests._output_helpers import names
from tests.cli.fakes import DEVICE
from tests.process_helpers import plain_sheet

FAST = ["--no-orient", "--no-restore", "--discard-raw"]
WAITING_LINE = "Waiting for the scanner to answer\u2026"


@pytest.fixture(autouse=True)
def check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(precheck_module.SKIP_ENV_VAR, raising=False)


def scan(out: Path) -> int:
    return main(["scan", "--out", str(out), *FAST])


def install_check(
    monkeypatch: pytest.MonkeyPatch, error: BaseException | None = None, *, slow: bool = False
):
    calls: list[tuple[str, dict[str, Any]]] = []

    def check(device: str, **options: Any) -> None:
        calls.append((device, options))
        if slow and options.get("on_slow") is not None:
            options["on_slow"]()  # the check has been waiting for the scanner for a while
        if error is not None:
            raise error

    monkeypatch.setattr("fastfoto_linux.session.run.check_scanner", check)
    return calls


def test_the_scanner_is_checked_with_its_device_before_the_scan(
    out, transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_check(monkeypatch)
    transport.sheets = [plain_sheet(0)]

    assert scan(out) == 0

    assert [device for device, _ in calls] == [DEVICE]
    assert names(out) == ["FastFoto_0001.jpg"]


def test_a_stuck_scanner_is_exit_3_with_one_line_and_no_scan(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch, ScannerStuckError())

    assert scan(out) == 3

    err = capsys.readouterr().err
    assert err.strip() == (
        "ffscan: error: The scanner isn't answering. Switch it off and on, then try again."
    )
    assert transport.jobs == []
    assert names(out) == []


def test_a_scanner_held_by_another_program_is_exit_3_too(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch, ScannerInUseError())

    assert scan(out) == 3

    assert "in use by another program" in capsys.readouterr().err
    assert transport.jobs == []


def test_a_scanner_that_disappeared_is_exit_3_with_one_line(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch, ScannerDisconnectedError())

    assert scan(out) == 3

    assert capsys.readouterr().err.strip() == (
        "ffscan: error: The scanner disappeared (it may have restarted) \u2014 try again."
    )
    assert transport.jobs == []


def test_a_check_that_waits_for_the_scanner_prints_one_line_about_it(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch, slow=True)
    transport.sheets = [plain_sheet(0)]

    assert scan(out) == 0

    assert capsys.readouterr().err.splitlines().count(WAITING_LINE) == 1


def test_a_quick_check_prints_nothing_about_waiting(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch)
    transport.sheets = [plain_sheet(0)]

    assert scan(out) == 0

    assert WAITING_LINE not in capsys.readouterr().err


def test_ctrl_c_during_the_check_is_exit_130(
    out, transport, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    install_check(monkeypatch, KeyboardInterrupt())

    assert scan(out) == 130

    assert "interrupted" in capsys.readouterr().err
    assert transport.jobs == []


def test_the_environment_switches_the_check_off(
    out, transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_check(monkeypatch)
    monkeypatch.setenv(precheck_module.SKIP_ENV_VAR, "1")
    transport.sheets = [plain_sheet(0)]

    assert scan(out) == 0

    assert calls == []
