"""``ffscan devices``: lists what the transport would use; reads sysfs only."""

import pytest

from fastfoto_linux.cli import main
from tests.cli.fakes import DEVICE, HOST, SCANNER, fake_usb


def test_lists_the_usb_scanner_and_the_shim(tmp_path, monkeypatch, capsys) -> None:
    shim = tmp_path / "ff680w_usb_gap.so"
    shim.write_bytes(b"")
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[tmp_path / "missing.so", shim])
    assert main(["devices"]) == 0
    out, err = capsys.readouterr()
    assert DEVICE in out
    assert "shim: found" in out
    assert err == ""


def test_a_scanner_without_the_shim_is_exit_3_with_the_build_command(
    tmp_path, monkeypatch, capsys
) -> None:
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[tmp_path / "missing.so"])
    assert main(["devices"]) == 3
    out, err = capsys.readouterr()
    assert DEVICE in out
    assert "shim: missing" in out
    assert "make -C tools/usb-gap-shim" in err
    assert len(err.strip().splitlines()) == 1


def test_no_scanner_is_exit_3(monkeypatch, capsys) -> None:
    fake_usb(monkeypatch)
    assert main(["devices"]) == 3
    out, err = capsys.readouterr()
    assert "USB scanners: 0" in out
    assert "no FF-680W" in err
    assert "Traceback" not in err


def test_a_network_host_is_listed_and_makes_the_listing_usable(monkeypatch, capsys) -> None:
    fake_usb(monkeypatch)
    assert main(["devices", "--net", HOST]) == 0
    assert f"epsonds:net:{HOST}" in capsys.readouterr().out


def test_a_bad_network_host_is_a_usage_error(monkeypatch, capsys) -> None:
    fake_usb(monkeypatch)
    assert main(["devices", "--net", "not a host"]) == 2
    assert "--net" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["-v", "--debug"])
def test_logging_flags_are_accepted(monkeypatch, flag) -> None:
    fake_usb(monkeypatch, scanners=[SCANNER], shims=[])
    assert main(["devices", flag]) == 3
