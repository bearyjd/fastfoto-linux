"""Review round 2 (12) at the Qt layer: a folder that answers slowly cannot freeze the window."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QCoreApplication

from fastfoto_linux.gui.controller import CHECKING_DISK_TEXT
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt import bridge as bridge_module
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, click, wait_until

open_window = test_qml.open_window  # the fixture that opens the window
GATE_WAIT = 20.0  # a test that forgets to open the gate fails instead of hanging


@pytest.fixture
def slow_disk(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``validate_filesystem`` as a hung network mount: it waits for ``gate``."""
    gate = threading.Event()
    threads: list[int] = []
    real = bridge_module.validate_filesystem

    def slow(form: ScanForm) -> dict[str, str]:
        threads.append(threading.get_ident())
        gate.wait(GATE_WAIT)
        return real(form)

    monkeypatch.setattr(bridge_module, "validate_filesystem", slow)
    yield SimpleNamespace(gate=gate, threads=threads)
    gate.set()


def found(bridge: Any) -> None:
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")


def test_a_bridge_does_not_wait_for_the_disk_when_it_is_made(
    make_bridge: Any, slow_disk: Any
) -> None:
    begun = time.monotonic()
    bridge = make_bridge()
    assert time.monotonic() - begun < GATE_WAIT / 2
    assert bridge.whyNotScan == CHECKING_DISK_TEXT
    assert not bridge.canScan
    wait_until(lambda: slow_disk.threads, "the folder check to start")
    assert slow_disk.threads[0] != threading.get_ident()
    slow_disk.gate.set()
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the folder and the scanner to be found")
    assert bridge.whyNotScan == ""


def test_leaving_the_folder_field_returns_at_once_and_the_answer_comes_later(
    make_bridge: Any, slow_disk: Any, tmp_path: Path
) -> None:
    bridge = make_bridge(form=ScanForm(output_folder=str(tmp_path / "gone")))
    slow_disk.gate.set()
    wait_until(lambda: "output_folder" in bridge.errors, "the startup check to answer")
    slow_disk.gate.clear()
    bridge.setField("output_folder", str(tmp_path))
    begun = time.monotonic()
    bridge.checkDisk()
    assert time.monotonic() - begun < GATE_WAIT / 2
    assert bridge.whyNotScan == CHECKING_DISK_TEXT
    slow_disk.gate.set()
    wait_until(lambda: bridge.errors == {}, "the answer for the folder that exists")


def test_an_answer_about_an_old_folder_never_shows(
    make_bridge: Any, slow_disk: Any, tmp_path: Path
) -> None:
    bridge = make_bridge(form=ScanForm(output_folder=str(tmp_path)))  # the check waits at the gate
    bridge.setField("output_folder", str(tmp_path / "other"))
    bridge.checkDisk()
    slow_disk.gate.set()
    wait_until(lambda: "output_folder" in bridge.errors, "the answer about the new folder")
    assert "other" in bridge.errors["output_folder"]
    time.sleep(0.2)
    QCoreApplication.processEvents()
    assert "other" in bridge.errors["output_folder"]  # the old, good answer did not replace it


def test_pressing_scan_looks_at_the_folder_off_the_gui_thread_and_then_scans(
    make_bridge: Any, slow_disk: Any
) -> None:
    bridge = make_bridge()
    slow_disk.gate.set()
    found(bridge)
    slow_disk.gate.clear()
    begun = time.monotonic()
    bridge.startScan()
    assert time.monotonic() - begun < GATE_WAIT / 2
    assert bridge.state == "ready"
    assert bridge.busy
    assert bridge.whyNotScan == CHECKING_DISK_TEXT
    slow_disk.gate.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    assert bridge.photoCount == 3


def test_closing_the_window_while_the_disk_is_read_is_harmless(
    make_bridge: Any, slow_disk: Any
) -> None:
    bridge = make_bridge()
    bridge.shutdown()
    slow_disk.gate.set()
    time.sleep(0.2)
    QCoreApplication.processEvents()  # the late answer is dropped, nothing raises


def test_a_folder_check_that_raises_is_a_field_error_and_not_a_page_that_waits_for_ever(
    make_bridge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(form: ScanForm) -> dict[str, str]:
        raise PermissionError("access denied")

    monkeypatch.setattr(bridge_module, "validate_filesystem", broken)
    bridge = make_bridge()
    wait_until(lambda: "output_folder" in bridge.errors, "the folder check to answer")
    assert "access denied" in bridge.errors["output_folder"]
    assert bridge.whyNotScan != CHECKING_DISK_TEXT


def test_a_hung_folder_check_before_a_scan_can_be_given_up_with_cancel(
    make_bridge: Any, slow_disk: Any
) -> None:
    bridge = make_bridge()
    slow_disk.gate.set()
    found(bridge)
    slow_disk.gate.clear()
    bridge.startScan()
    assert bridge.startingScan
    bridge.cancel()
    assert not bridge.startingScan
    assert not bridge.busy
    assert bridge.state == "ready"
    slow_disk.gate.set()  # the folder answers after all: no scan starts by itself
    time.sleep(0.2)
    QCoreApplication.processEvents()
    assert bridge.state == "ready"


@pytest.mark.usefixtures("kirigami")
def test_the_cancel_button_is_enabled_while_a_scan_waits_for_the_folder(
    make_bridge: Any, slow_disk: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    slow_disk.gate.set()
    found(bridge)
    cancel = child(window, "cancelButton")
    assert cancel.property("enabled") is False
    slow_disk.gate.clear()
    bridge.startScan()
    wait_until(lambda: cancel.property("enabled") is True, "Cancel to be enabled")
    click(cancel)
    wait_until(lambda: cancel.property("enabled") is False, "Cancel to be disabled again")
    assert bridge.state == "ready"
