"""SIGTERM and SIGHUP end ``ffscan`` like Ctrl-C: scanimage is stopped and the raw pages stay."""

import errno
import os
import signal
import sys
import threading
from functools import partial
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_scan, main
from fastfoto_linux.scanner import ScanTarget, run_scan
from fastfoto_linux.session import raw as rawdir
from tests._fake_scanimage import fake_env, install
from tests._output_helpers import names
from tests.cli.fakes import DEVICE, write_dummy_page
from tests.process_helpers import plain_sheet, write_sheets

FAST = ["--no-orient", "--no-restore"]
STAMP = "20261013T230000Z"
SIGNALS = [signal.SIGTERM, signal.SIGHUP]
INTERRUPT_DELAY_S = 0.3
SCAN_TIMEOUT_S = 3.0  # a scan that is not interrupted gives up soon instead of hanging the suite


class Sentinel:
    """A handler installed before ``main`` runs: the signal never kills the test process."""

    def __init__(self, signum: signal.Signals) -> None:
        self.signum = signum
        self.received = 0
        self.previous = signal.signal(signum, self)

    def __call__(self, signum: int, frame: object) -> None:
        self.received += 1

    def restore(self) -> None:
        signal.signal(self.signum, self.previous)


@pytest.fixture
def sentinels():
    installed = [Sentinel(signum) for signum in SIGNALS]
    yield {s.signum: s for s in installed}
    for sentinel in installed:
        sentinel.restore()


@pytest.fixture
def dispositions():
    """Put back whatever SIGTERM and SIGHUP did before the test changed them."""
    saved = {signum: signal.getsignal(signum) for signum in SIGNALS}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler if handler is not None else signal.SIG_DFL)


def signal_before(signum: int, then):
    """``then`` preceded by ``signum`` being sent to this process."""

    def run(*args, **kwargs):
        signal.raise_signal(signum)
        return then(*args, **kwargs)

    return run


@pytest.mark.parametrize("signum", SIGNALS)
def test_the_signal_interrupts_the_command_like_ctrl_c(
    out, monkeypatch, capsys, sentinels, signum
) -> None:
    page = write_dummy_page(out.parent / "raw", "page-1.png")
    monkeypatch.setattr(
        "fastfoto_linux.cli.cmd_process.process_pages", lambda *a, **k: signal.raise_signal(signum)
    )
    assert main(["process", str(page), "--out", str(out)]) == 130
    assert "interrupted" in capsys.readouterr().err
    assert sentinels[signum].received == 0  # main's handler took it, not ours


@pytest.mark.parametrize("signum", SIGNALS)
def test_the_previous_handlers_are_back_after_main(tmp_path, out, sentinels, signum) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), *FAST]) == 0
    assert signal.getsignal(signum) is sentinels[signum]


@pytest.mark.parametrize("signum", SIGNALS)
def test_the_previous_handlers_are_back_after_an_interrupt(
    tmp_path, out, monkeypatch, sentinels, signum
) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")
    monkeypatch.setattr(
        "fastfoto_linux.cli.cmd_process.process_pages", lambda *a, **k: signal.raise_signal(signum)
    )
    assert main(["process", str(page), "--out", str(out)]) == 130
    assert signal.getsignal(signum) is sentinels[signum]


def test_a_signal_during_a_scan_keeps_the_raw_pages(
    out, transport, capsys, monkeypatch, sentinels
) -> None:
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)

    def hang_up(pages):
        signal.raise_signal(signal.SIGHUP)  # the terminal closed with the pages on disk
        return RuntimeError("the signal was not turned into an interrupt")

    transport.sheets = [plain_sheet()]
    transport.failure = hang_up
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 130
    kept = out / ".raw" / STAMP
    assert len(list(kept.iterdir())) == 2
    assert str(kept) in capsys.readouterr().err


def test_main_works_off_the_main_thread(tmp_path, out) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    codes: list[int] = []
    thread = threading.Thread(
        target=lambda: codes.append(main(["process", *map(str, pages), "--out", str(out), *FAST]))
    )
    thread.start()
    thread.join()
    assert codes == [0]


@pytest.mark.usefixtures("sentinels")
@pytest.mark.parametrize("signum", SIGNALS)
def test_a_signal_stops_scanimage_and_keeps_what_it_scanned(
    out, monkeypatch, capsys, signum
) -> None:
    marker = out.parent / "sigterm-marker"
    for name, value in fake_env(
        install(out.parent / "bin"), pages=1, hang=True, sigterm_marker=str(marker)
    ).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cmd_scan, "resolve_target", lambda **kw: ScanTarget(device=DEVICE))
    monkeypatch.setattr(cmd_scan, "run_scan", partial(run_scan, timeout_s=SCAN_TIMEOUT_S))
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)
    timer = threading.Timer(INTERRUPT_DELAY_S, os.kill, (os.getpid(), signum))
    monkeypatch.setattr(cmd_scan, "_log_page", lambda number: timer.start())
    try:
        assert main(["scan", "--out", str(out), *FAST, "--simplex", "--discard-raw"]) == 130
    finally:
        timer.cancel()
    assert marker.read_text() == "terminated"
    assert [p.name for p in (out / ".raw" / STAMP).iterdir()] == ["page-0001.png"]
    assert str(Path(out / ".raw" / STAMP)) in capsys.readouterr().err


# --- a signal that was ignored stays ignored ("nohup ffscan scan &") ----------------------------


@pytest.mark.usefixtures("dispositions")
@pytest.mark.parametrize("signum", SIGNALS)
def test_an_ignored_signal_stays_ignored_and_the_scan_carries_on(
    out, transport, capsys, monkeypatch, signum
) -> None:
    signal.signal(signum, signal.SIG_IGN)
    monkeypatch.setattr(cmd_scan, "process_pages", signal_before(signum, cmd_scan.process_pages))
    transport.sheets = [plain_sheet()]
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 0
    assert "interrupted" not in capsys.readouterr().err
    assert names(out) == ["FastFoto_0001.jpg"]
    assert signal.getsignal(signum) is signal.SIG_IGN


@pytest.mark.usefixtures("dispositions")
@pytest.mark.parametrize("signum", SIGNALS)
def test_the_other_signal_still_interrupts_while_one_is_ignored(
    out, transport, sentinels, monkeypatch, signum
) -> None:
    ignored = next(s for s in SIGNALS if s != signum)
    signal.signal(ignored, signal.SIG_IGN)
    monkeypatch.setattr(cmd_scan, "process_pages", signal_before(signum, cmd_scan.process_pages))
    transport.sheets = [plain_sheet()]
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 130
    assert signal.getsignal(ignored) is signal.SIG_IGN
    assert signal.getsignal(signum) is sentinels[signum]  # only what main installed is undone


@pytest.mark.usefixtures("dispositions")
@pytest.mark.parametrize("signum", SIGNALS)
def test_a_signal_with_the_default_action_still_interrupts(tmp_path, out, monkeypatch, signum):
    signal.signal(signum, signal.SIG_DFL)
    page = write_dummy_page(tmp_path / "raw", "page-1.png")

    def hang_up(*args, **kwargs):
        # The default action would end this process: fail the test instead of dying.
        assert signal.getsignal(signum) is not signal.SIG_DFL, "the signal was not taken over"
        signal.raise_signal(signum)

    monkeypatch.setattr("fastfoto_linux.cli.cmd_process.process_pages", hang_up)
    assert main(["process", str(page), "--out", str(out)]) == 130
    assert signal.getsignal(signum) is signal.SIG_DFL


# --- a terminal that hung up: every write fails -------------------------------------------------


class DeadStream:
    """What stdout and stderr become when the terminal is gone: every write fails with EIO."""

    def write(self, text: str) -> int:
        raise OSError(errno.EIO, "Input/output error")

    def flush(self) -> None:
        raise OSError(errno.EIO, "Input/output error")


def hang_up_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Call it inside the test: pytest's capture puts its own streams back after fixtures ran."""
    monkeypatch.setattr(sys, "stdout", DeadStream())
    monkeypatch.setattr(sys, "stderr", DeadStream())


def kept_pages(out: Path) -> list[str]:
    return sorted(p.name for p in (out / ".raw" / STAMP).iterdir())


def test_a_hangup_during_a_scan_is_still_an_interrupt_when_nothing_can_be_printed(
    out, transport, monkeypatch, sentinels
) -> None:
    hang_up_terminal(monkeypatch)
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)
    transport.sheets = [plain_sheet()]
    transport.failure = lambda pages: (
        signal.raise_signal(signal.SIGHUP),
        RuntimeError("the signal was not turned into an interrupt"),
    )[1]
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 130
    assert len(kept_pages(out)) == 2


def test_ctrl_c_is_still_exit_130_when_nothing_can_be_printed(out, transport, monkeypatch) -> None:
    hang_up_terminal(monkeypatch)
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)
    transport.sheets = [plain_sheet()]
    transport.failure = lambda pages: KeyboardInterrupt()
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 130
    assert len(kept_pages(out)) == 2


def test_an_error_keeps_its_exit_code_when_nothing_can_be_printed(
    out, transport, monkeypatch
) -> None:
    def boom(pages, settings):
        raise RuntimeError("processing blew up")

    hang_up_terminal(monkeypatch)
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)
    monkeypatch.setattr(cmd_scan, "process_pages", boom)
    transport.sheets = [plain_sheet()]
    assert main(["scan", "--out", str(out), *FAST]) == 1
    assert len(kept_pages(out)) == 2
