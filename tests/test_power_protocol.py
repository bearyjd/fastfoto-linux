"""Fragmented and hostile maintenance replies are bounded and never become fabricated values."""

import pytest

from fastfoto_linux.scanner import power
from tests.power_helpers import CAPS, CURRENT, TARGET, ScriptedUsb, frame, install_usb, read_usb


def test_fragmented_reads_and_partial_writes_preserve_exact_stream(monkeypatch):
    usb = read_usb(fragment=1, partial=1)
    install_usb(monkeypatch, usb)
    assert power.read_power_settings(TARGET).power_off_minutes == 60
    assert usb.stream == b"\x1cZCAPAx0000000RESAx0000000FIN x0000000"
    assert usb.released


@pytest.mark.parametrize(
    "header",
    [
        b"CAPAxFFFFFFF",
        b"CAPAx00000Q0",
        b"INFOx0000000",
        b"CAPAd064",
        b"CAPAx0000000#nrdBUSY",
        b"CAPAx0000000#errADF ERR ",
    ],
)
def test_bad_oversized_and_error_headers_are_rejected(monkeypatch, header):
    usb = ScriptedUsb(b"\x06", (header + b"#---").ljust(64, b"\x00"), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings(TARGET)
    assert b"RESA" not in usb.stream
    assert usb.released


@pytest.mark.parametrize(
    "caps",
    [
        b"#SAVRANGd240d001#---",
        b"#SAVLIST#---",
        b"#SAVRANGd001#---",
        b"#SAVLISTd0Q1#---",
        b"#SAVRANGi0000001i0001000#---",
        b"#SAVRANGd001d240#SAVLISTd005#---",
    ],
)
def test_malformed_or_unwritable_power_capabilities_are_rejected(monkeypatch, caps):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", caps), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings(TARGET)
    assert usb.released


def test_unknown_fields_are_skipped_and_unsupported_values_remain_unavailable(monkeypatch):
    caps = b"#ADFi0000001#XYZh004abcd#SAVLISTd005d010#---"
    current = b"#SAVd005#POFd060#---"
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", caps), frame(b"RESA", current), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    answer = power.read_power_settings(TARGET)
    assert answer.sleep_capability == power.TimerCapability(values=(5, 10))
    assert answer.sleep_minutes == 5
    assert answer.power_off_capability is None
    assert answer.power_off_minutes is None


@pytest.mark.parametrize("current", [b"#---", b"#SAVd010#---"])
def test_missing_current_value_is_not_replaced_with_vendor_defaults(monkeypatch, current):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", current), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    snapshot = power.read_power_settings(TARGET)
    assert snapshot.power_off_minutes is None


@pytest.mark.parametrize(
    "current", [b"#SAVd250#POFd060#---", b"#SAVd010#POFd0Q0#---", b"#SAVd010#SAVd030#---"]
)
def test_inconsistent_or_malformed_current_values_fail(monkeypatch, current):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", current), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings(TARGET)
    assert usb.released


@pytest.mark.parametrize(
    "cap,value,accepted",
    [
        (power.TimerCapability(values=(0, 30)), 0, True),
        (power.TimerCapability(values=(30,)), 0, False),
        (power.TimerCapability(minimum=1, maximum=240), 240, True),
        (power.TimerCapability(minimum=1, maximum=240, step=2), 2, False),
        (power.TimerCapability(values=(1,)), True, False),
    ],
)
def test_capabilities_accept_only_advertised_integers(cap, value, accepted):
    assert cap.accepts(value) is accepted


def test_truncated_reply_is_not_parsed_as_partial_success(monkeypatch):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", CAPS)[:-5])
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings(TARGET)
    assert usb.released


def test_vendor_extended_integer_encodings_are_read_without_truncation(monkeypatch):
    caps = b"#SAVRANGi0000001i0000240#POFLISTx0000000x000003C#---"
    current = b"#SAVi0000010#POFx000003C#---"
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", caps), frame(b"RESA", current), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    snapshot = power.read_power_settings(TARGET)
    assert (snapshot.sleep_minutes, snapshot.power_off_minutes) == (10, 60)


def test_binary_unknown_values_cannot_inject_power_tokens(monkeypatch):
    caps = b"#XYZh008#SAVd999#POFLISTd000d060#---"
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", caps), frame(b"RESA", CURRENT), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    snapshot = power.read_power_settings(TARGET)
    assert snapshot.sleep_capability is None
    assert snapshot.sleep_minutes is None
    assert snapshot.power_off_minutes == 60
