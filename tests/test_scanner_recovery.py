"""A killed maintenance operation cannot lose its durable USB recovery guard."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fastfoto_linux.scanner import libusb, power, precheck, recovery, target
from fastfoto_linux.scanner.errors import ScannerInUseError
from fastfoto_linux.scanner.job import ScanJob
from fastfoto_linux.scanner.power import PowerSettingsError
from fastfoto_linux.scanner.run import run_scan
from fastfoto_linux.scanner.usb import UsbScanner
from tests.libusb_fake import FakeLibusb
from tests.power_helpers import TARGET, ScriptedUsb, frame, install_usb, read_usb


@pytest.mark.parametrize(
    "guard",
    [
        lambda: recovery.require_ready(TARGET),
        lambda: recovery.require_address_ready(1, 4),
        recovery.require_ready,
    ],
)
def test_pending_marker_blocks_new_service_or_process(monkeypatch, guard):
    recovery.begin(TARGET)
    assert recovery.pending_targets() == (TARGET,)
    with pytest.raises(PowerSettingsError) as error:
        guard()
    assert error.value.reconnect_required
    assert error.value.scanner == TARGET
    script = (
        "from fastfoto_linux.scanner import recovery; "
        "from fastfoto_linux.scanner.power import PowerSettingsError; "
        "import sys; "
        "\ntry: recovery.require_ready()"
        "\nexcept PowerSettingsError as e: sys.exit(17 if e.reconnect_required else 18)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], env=os.environ.copy(), check=False, capture_output=True
    )
    assert result.returncode == 17, result.stderr.decode()


def test_marker_exists_before_first_maintenance_out_and_clears_after_fin(monkeypatch):
    usb = read_usb()
    original = usb.write

    def noted_write(data, timeout_ms):
        assert recovery.pending_targets() == (TARGET,)
        return original(data, timeout_ms)

    monkeypatch.setattr(usb, "write", noted_write)
    install_usb(monkeypatch, usb)
    assert power.read_power_settings(TARGET).sleep_minutes == 10
    assert recovery.pending_targets() == ()
    assert usb.released


def test_interrupted_operation_remains_blocked_after_new_service_call(monkeypatch):
    usb = ScriptedUsb(b"\x06", b"CAPAx00")
    install_usb(monkeypatch, usb)
    with pytest.raises(PowerSettingsError):
        power.read_power_settings(TARGET)
    assert recovery.pending_targets() == (TARGET,)
    old_stream = usb.stream
    with pytest.raises(PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert error.value.reconnect_required
    assert usb.stream == old_stream


def test_process_exit_after_begin_leaves_recovery_marker():
    script = (
        "from pathlib import Path; from fastfoto_linux.scanner import recovery; "
        "from fastfoto_linux.scanner.usb import UsbScanner; import os; "
        "recovery.begin(UsbScanner(1, 4, Path('/synthetic/usb'))); os._exit(0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], env=os.environ.copy(), check=False, capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()
    with pytest.raises(PowerSettingsError):
        recovery.require_ready(TARGET)


@pytest.mark.parametrize(
    "contents",
    [
        b"{broken",
        b"{}",
        json.dumps(
            {"version": 1, "bus": True, "address": 4, "sysfs_path": "/synthetic/usb"}
        ).encode(),
        b"x" * 4096,
    ],
)
def test_corrupt_marker_never_becomes_permission_to_send(contents):
    recovery.begin(TARGET)
    recovery.marker_path(TARGET).write_bytes(contents)
    with pytest.raises(PowerSettingsError) as error:
        recovery.require_ready()
    assert error.value.reconnect_required
    with pytest.raises(PowerSettingsError):
        recovery.check_reconnection((UsbScanner(1, 5, TARGET.sysfs_path),))


def test_persistence_failure_sends_no_usb_commands(monkeypatch):
    usb = read_usb()
    install_usb(monkeypatch, usb)

    def fail(_scanner):
        raise PowerSettingsError("Recovery state cannot be saved.")

    monkeypatch.setattr(recovery, "begin", fail)
    with pytest.raises(PowerSettingsError):
        power.read_power_settings(TARGET)
    assert usb.stream == b""
    assert usb.released
    assert recovery.pending_targets() == ()


def test_busy_claim_creates_no_marker(monkeypatch):
    def busy(*_args):
        raise ScannerInUseError

    monkeypatch.setattr(power, "open_scanner", busy)
    with pytest.raises(ScannerInUseError):
        power.read_power_settings(TARGET)
    assert recovery.pending_targets() == ()


@pytest.mark.parametrize("scanners", [(), (TARGET,), (UsbScanner(2, 5, Path("/different/port")),)])
def test_absence_same_enumeration_or_different_port_does_not_clear(scanners):
    recovery.begin(TARGET)
    with pytest.raises(PowerSettingsError):
        recovery.check_reconnection(scanners)
    assert recovery.pending_targets() == (TARGET,)


def test_verified_new_enumeration_clears_only_its_physical_port():
    other = UsbScanner(2, 9, Path("/different/port"))
    replacement = UsbScanner(1, 5, TARGET.sysfs_path)
    recovery.begin(TARGET)
    assert recovery.check_reconnection((replacement, other)) == replacement
    recovery.require_ready(replacement)
    assert recovery.pending_targets() == ()


def test_other_scanner_is_not_globally_quarantined():
    recovery.begin(TARGET)
    other = UsbScanner(2, 9, Path("/different/port"))
    recovery.require_ready(other)


def test_direct_libusb_guard_runs_before_any_library_call():
    recovery.begin(TARGET)
    lib = FakeLibusb()
    with (
        pytest.raises(PowerSettingsError),
        libusb.open_scanner(TARGET.bus, TARGET.device, lib=lib),
    ):
        pytest.fail("must not open an unsafe scanner")
    assert lib.calls == []


def test_no_precheck_environment_cannot_bypass_durable_guard(monkeypatch):
    recovery.begin(TARGET)
    monkeypatch.setenv(precheck.SKIP_ENV_VAR, "1")
    with pytest.raises(PowerSettingsError):
        precheck.check_scanner(TARGET.sane_usb_device_name())


def test_scanning_guard_prevents_starting_sane(monkeypatch, tmp_path):
    recovery.begin(TARGET)

    def forbidden(*_args, **_kwargs):
        pytest.fail("SANE must never start while maintenance recovery is pending")

    with pytest.raises(PowerSettingsError):
        run_scan(ScanJob(TARGET.sane_usb_device_name(), tmp_path / "out"), env={}, popen=forbidden)


def test_safe_semantic_error_fin_clears_durable_marker(monkeypatch):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", b"#SAVRANGd240d001#---"), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert not error.value.reconnect_required
    assert recovery.pending_targets() == ()


def test_actual_state_sync_failure_prevents_first_out(monkeypatch):
    usb = read_usb()
    install_usb(monkeypatch, usb)

    def fail_sync(_fd):
        raise OSError("synthetic state storage failure")

    monkeypatch.setattr(recovery.os, "fsync", fail_sync)
    with pytest.raises(PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert usb.stream == b""
    assert str(recovery.marker_path(TARGET)) in str(error.value)
    assert usb.released


def test_corrupt_state_diagnostic_names_repair_location():
    recovery.begin(TARGET)
    recovery.marker_path(TARGET).write_text("broken", encoding="ascii")
    with pytest.raises(PowerSettingsError) as error:
        recovery.require_ready()
    assert str(recovery.marker_path(TARGET)) in str(error.value)
    assert "off" in str(error.value)
    assert "broken" not in str(error.value)


def test_verified_fin_but_failed_marker_clear_still_blocks_future_operations(monkeypatch):
    usb = read_usb()
    install_usb(monkeypatch, usb)

    def fail_clear(_scanner):
        raise PowerSettingsError("Could not clear state", scanner=TARGET, reconnect_required=True)

    monkeypatch.setattr(recovery, "complete", fail_clear)
    with pytest.raises(power.PowerCleanupError) as error:
        power.read_power_settings(TARGET)
    assert error.value.reconnect_required
    assert recovery.pending_targets() == (TARGET,)
    assert usb.stream.endswith(b"FIN x0000000")


def test_target_resolution_cannot_ignore_saved_recovery(monkeypatch):
    recovery.begin(TARGET)
    monkeypatch.setattr(target, "find_usb_scanners", lambda _root: (TARGET,))
    with pytest.raises(PowerSettingsError):
        target.resolve_target(shim_candidates=())


def test_unknown_usb_sane_name_cannot_bypass_guard(tmp_path):
    recovery.begin(TARGET)
    with pytest.raises(PowerSettingsError):
        run_scan(ScanJob("epson2:libusb:001:004", tmp_path / "out"), env={})


def test_network_alias_cannot_bypass_unsafe_physical_scanner_guard(tmp_path):
    recovery.begin(TARGET)
    with pytest.raises(PowerSettingsError):
        run_scan(ScanJob("epsonds:net:scanner.example", tmp_path / "out"), env={})
