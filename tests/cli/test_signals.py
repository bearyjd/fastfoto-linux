"""SIGTERM and SIGHUP end ``ffscan`` like Ctrl-C: scanimage is stopped and the raw pages stay."""

import os
import signal
import threading
from functools import partial
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_scan, main, rawdir
from fastfoto_linux.scanner import ScanTarget, run_scan
from tests._fake_scanimage import fake_env, install
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
