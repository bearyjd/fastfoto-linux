"""What a missing or refused USB shim tells the user: build it natively, reinstall the Flatpak.

Inside the Flatpak the shim is built into the app (``/app/lib``): ``make`` and ``$FF680W_SHIM`` are
no use there (review round 2, item 4).
"""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import target
from fastfoto_linux.scanner.errors import ShimMissingError
from fastfoto_linux.scanner.target import resolve_target, shim_missing_message
from tests._fake_sysfs import add_usb_device
from tests.cli.fakes import DEVICE, SCANNER, fake_usb

NATIVE_HINT = "make -C tools/usb-gap-shim"


def flatpak(monkeypatch: pytest.MonkeyPatch, *, inside: bool) -> None:
    monkeypatch.setattr(target, "inside_flatpak", lambda: inside)


def test_the_native_message_says_to_build_the_shim_or_set_the_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flatpak(monkeypatch, inside=False)
    message = shim_missing_message([tmp_path / "nope.so"])
    assert f"Build it with `{NATIVE_HINT}` or set $FF680W_SHIM" in message
    assert "Flatpak" not in message


def test_the_native_message_for_a_refused_shim_keeps_the_reason_and_the_build_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flatpak(monkeypatch, inside=False)
    message = shim_missing_message([tmp_path / "x.so"], ["writable by group"])
    assert "refused as unsafe: writable by group" in message
    assert NATIVE_HINT in message
    assert "Flatpak" not in message


def test_inside_the_flatpak_a_missing_shim_says_the_bundled_one_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flatpak(monkeypatch, inside=True)
    searched = tmp_path / "app" / "ff680w_usb_gap.so"
    message = shim_missing_message([searched])
    assert "bundled" in message
    assert "missing" in message
    assert "reinstall or update the Flatpak" in message.lower()
    assert str(searched) in message
    assert "make -C" not in message
    assert "Build it" not in message
    assert "$FF680W_SHIM" not in message


def test_inside_the_flatpak_a_refused_shim_keeps_the_reason_and_says_to_reinstall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flatpak(monkeypatch, inside=True)
    message = shim_missing_message([tmp_path / "x.so"], ["owned by uid 1000"])
    assert "refused as unsafe: owned by uid 1000" in message
    assert "reinstall or update the Flatpak" in message.lower()
    assert NATIVE_HINT not in message


def test_resolving_a_target_inside_the_flatpak_without_the_shim_gives_that_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flatpak(monkeypatch, inside=True)
    sysfs = tmp_path / "devices"
    sysfs.mkdir()
    add_usb_device(sysfs, "1-1")
    with pytest.raises(ShimMissingError) as excinfo:
        resolve_target(sysfs_root=sysfs, shim_candidates=[tmp_path / "nope.so"])
    assert "reinstall or update the Flatpak" in str(excinfo.value).lower()
    assert NATIVE_HINT not in str(excinfo.value)


def test_ffscan_devices_inside_the_flatpak_does_not_tell_the_user_to_run_make(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flatpak(monkeypatch, inside=True)
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[tmp_path / "missing.so"])
    assert main(["devices"]) == 3
    out, err = capsys.readouterr()
    assert DEVICE in out
    assert "shim: missing" in out
    assert NATIVE_HINT not in out + err
    assert "reinstall or update the Flatpak" in err.lower()


def test_ffscan_devices_natively_still_says_to_build_the_shim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flatpak(monkeypatch, inside=False)
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[tmp_path / "missing.so"])
    assert main(["devices"]) == 3
    out, err = capsys.readouterr()
    assert NATIVE_HINT in out
    assert NATIVE_HINT in err
    assert "Flatpak" not in out + err
