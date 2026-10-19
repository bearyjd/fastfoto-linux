"""The explicit power page uses fake hardware and the existing worker lifecycle."""

import threading
from dataclasses import replace
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.gui.power import PowerTools
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.scanner.power import PowerWriteUncertainError
from tests.gui.power_helpers import SCANNER, snapshot
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, click, invoke, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window


def fake_power(bridge: Any) -> list[Any]:
    assert hasattr(bridge, "power"), "the bridge must expose the scanner power settings page"
    calls: list[Any] = []

    def read(scanner: Any = None, **hooks: Any) -> Any:
        calls.append(("read", scanner))
        return snapshot()

    def apply(scanner: Any, changes: Any, **hooks: Any) -> Any:
        calls.append(("apply", scanner, changes))
        return replace(snapshot(), sleep_minutes=changes.sleep_minutes or 17)

    bridge._worker._power_tools = PowerTools(read=read, apply=apply)
    return calls


def test_page_opens_without_usb_read_and_displays_actual_current_values_only_after_read(
    make_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    bridge = make_bridge()
    calls = fake_power(bridge)
    window, warnings = open_window(bridge)
    invoke(child(window, "scannerSettingsAction"), "trigger")
    settle()
    assert calls == []
    assert child(window, "scannerSettingsPage")
    assert child(window, "sleepCurrent").property("text") == "Not read"
    assert not child(window, "powerApplyButton").property("enabled")
    click(child(window, "powerReadButton"))
    wait_until(lambda: bridge.power.loaded, "synthetic power settings read")
    assert calls == [("read", None)]
    assert child(window, "sleepCurrent").property("text") == "17 minutes"
    assert child(window, "powerOffCurrent").property("text") == "60 minutes"
    assert warnings == []
    assert messages == []


def test_draft_does_not_write_until_apply_and_only_edited_value_is_sent(
    make_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    bridge = make_bridge()
    calls = fake_power(bridge)
    _window, warnings = open_window(bridge)
    bridge.power.read()
    wait_until(lambda: bridge.power.loaded, "power settings")
    bridge.power.setValue("sleep_minutes", 22)
    assert len(calls) == 1
    assert bridge.power.canApply
    bridge.power.apply()
    wait_until(lambda: not bridge.power.busy, "power settings apply")
    assert len(calls) == 2
    _, scanner, changes = calls[-1]
    assert scanner == SCANNER
    assert changes.sleep_minutes == 22
    assert changes.power_off_minutes is None
    assert not bridge.power.canApply
    assert "verified" in bridge.power.message.lower()
    assert warnings == []
    assert messages == []


def test_off_choices_follow_live_capabilities_and_unsupported_controls_are_disabled(
    make_bridge: Any,
) -> None:
    bridge = make_bridge()
    fake_power(bridge)
    bridge._worker._power_tools = PowerTools(
        read=lambda *args, **kwargs: snapshot(sleep_capability=None, sleep_minutes=None)
    )
    bridge.power.read()
    wait_until(lambda: bridge.power.loaded, "capabilities")
    assert bridge.power.sleepChoices == []
    assert bridge.power.sleepCurrent == "Unsupported"
    assert bridge.power.powerOffChoices[0] == {"label": "Off", "value": 0}
    assert bridge.power.sleepDraft == -1


def test_power_job_disables_all_conflicting_actions_and_releases_on_shutdown(
    make_bridge: Any,
) -> None:
    bridge = make_bridge()
    fake_power(bridge)
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "synthetic scanner discovery")
    entered = threading.Event()
    stopped = threading.Event()

    def held(scanner: Any = None, *, cancel: threading.Event) -> Any:
        entered.set()
        try:
            assert cancel.wait(5)
            return snapshot()
        finally:
            stopped.set()

    bridge._worker._power_tools = PowerTools(read=held)
    bridge.power.read()
    try:
        assert entered.wait(5)
        assert bridge.busy
        assert not bridge.canScan
        assert not bridge.canCheck
        assert not bridge.canProcessKept
        assert not bridge.power.canRead
        assert not bridge.power.canApply
        with pytest.raises(ActionBlockedError):
            bridge.controller.start_scan()
        with pytest.raises(ActionBlockedError):
            bridge.controller.check_scanner()
    finally:
        bridge.shutdown()
    assert stopped.is_set()
    assert not bridge.job_alive


def test_desynchronized_write_blocks_scan_and_refresh_until_metadata_proves_restart(
    make_bridge: Any,
) -> None:
    bridge = make_bridge()
    fake_power(bridge)
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "synthetic scanner")
    bridge.power.read()
    wait_until(lambda: bridge.power.loaded, "settings")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PowerWriteUncertainError("partial PARA", scanner=SCANNER, reconnect_required=True)

    bridge._worker._power_tools = PowerTools(apply=fail)
    bridge.power.setValue("sleep_minutes", 20)
    bridge.power.apply()
    wait_until(lambda: not bridge.power.busy, "unsafe write report")
    assert bridge.power.reconnectRequired
    assert not bridge.canScan
    assert not bridge.canCheck
    assert not bridge.power.canRead
    assert not bridge.power.canApply
    assert "off and on" in bridge.power.message.lower()
    with pytest.raises(ActionBlockedError):
        bridge.controller.start_scan()
    bridge.cancel()
    assert bridge.power.reconnectRequired
    restarted = replace(SCANNER, device=SCANNER.device + 10)
    bridge._worker._power_tools = PowerTools(discover=lambda: (restarted,))
    bridge.power.checkConnection()
    wait_until(lambda: not bridge.power.busy, "safe USB metadata check")
    assert not bridge.power.reconnectRequired
    assert bridge.power.canRead
    assert not bridge.power.loaded
    assert not bridge.power.canApply
