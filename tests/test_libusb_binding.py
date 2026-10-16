"""The libusb binding, against a Python fake of the library: nothing here may reach USB."""

import ctypes
from collections.abc import Callable

import pytest

from fastfoto_linux.scanner import libusb
from fastfoto_linux.scanner.errors import ScannerInUseError
from fastfoto_linux.scanner.libusb import (
    CheckUnavailableError,
    LibusbUnavailableError,
    open_scanner,
)
from fastfoto_linux.scanner.unstick import DeviceGoneError, TransportError
from tests.libusb_fake import (
    LIBUSB_ERROR_ACCESS,
    LIBUSB_ERROR_BUSY,
    LIBUSB_ERROR_IO,
    LIBUSB_ERROR_NO_DEVICE,
    LIBUSB_ERROR_TIMEOUT,
    UNSET,
    FakeDevice,
    FakeLibusb,
)
from tests.unstick_fakes import FakeClock

DEFAULT_LIBRARY_NAMES = libusb._LIBRARY_NAMES  # read before the tests' own lock empties it
BUS, ADDRESS = 1, 4
OUT_AFTER_IN_GAP_S = 0.003


def opened(lib: FakeLibusb, **options):
    return open_scanner(BUS, ADDRESS, lib=lib, **options)


# --- loading the library -----------------------------------------------------------------------


def test_libusb_cannot_be_loaded_while_the_tests_run() -> None:
    """The tripwire in conftest: no test may reach a scanner that happens to be plugged in."""
    with pytest.raises(LibusbUnavailableError):
        libusb.load_libusb()


def test_every_library_name_is_tried_and_all_failing_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tried: list[str] = []

    def refuse(name: str):
        tried.append(name)
        raise OSError(f"{name}: cannot open shared object file")

    monkeypatch.setattr(libusb, "_LIBRARY_NAMES", ("libone.so.0", "libtwo.so"))
    monkeypatch.setattr(ctypes, "CDLL", refuse)

    with pytest.raises(LibusbUnavailableError, match="libusb"):
        libusb.load_libusb()

    assert tried == ["libone.so.0", "libtwo.so"]


def test_the_first_library_that_loads_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = object()

    def first_fails(name: str):
        if name == "libone.so.0":
            raise OSError("missing")
        return loaded

    monkeypatch.setattr(libusb, "_LIBRARY_NAMES", ("libone.so.0", "libtwo.so"))
    monkeypatch.setattr(ctypes, "CDLL", first_fails)

    assert libusb.load_libusb() is loaded


def test_the_default_names_start_with_the_soname() -> None:
    assert DEFAULT_LIBRARY_NAMES[0] == "libusb-1.0.so.0"  # what the Flatpak runtime ships


# --- opening the scanner -----------------------------------------------------------------------


def test_the_scanner_is_claimed_on_interface_0_and_released_closed_and_exited_in_order() -> None:
    lib = FakeLibusb()

    with opened(lib):
        assert "libusb_claim_interface" in lib.calls
        assert "libusb_release_interface" not in lib.calls

    assert lib.calls[0] == "libusb_init"
    assert lib.calls[-3:] == ["libusb_release_interface", "libusb_close", "libusb_exit"]
    assert lib.calls.index("libusb_open") < lib.calls.index("libusb_free_device_list")


def test_the_device_is_found_by_bus_and_address_not_by_vid_and_pid_alone() -> None:
    lib = FakeLibusb(
        (FakeDevice(1, 3), FakeDevice(2, 4), FakeDevice(BUS, ADDRESS), FakeDevice(1, 5))
    )

    with opened(lib):
        pass

    assert lib.opened == [3]  # the third entry of the list


def test_a_device_with_other_ids_at_the_address_is_never_opened() -> None:
    lib = FakeLibusb((FakeDevice(BUS, ADDRESS, ids=(0x04B8, 0x0001)),))

    with pytest.raises(CheckUnavailableError, match="FF-680W"), opened(lib):
        pytest.fail("the body must not run")

    assert lib.opened == []
    assert lib.calls[-1] == "libusb_exit"


def test_no_device_at_the_address_is_unavailable() -> None:
    lib = FakeLibusb((FakeDevice(2, 9),))

    with pytest.raises(CheckUnavailableError), opened(lib):
        pytest.fail("the body must not run")

    assert lib.opened == []
    assert lib.calls[-1] == "libusb_exit"


def test_a_busy_interface_stops_without_sending_anything() -> None:
    lib = FakeLibusb(claim_rc=LIBUSB_ERROR_BUSY)

    with pytest.raises(ScannerInUseError, match="in use by another program"), opened(lib):
        pytest.fail("the body must not run")

    assert "libusb_bulk_transfer" not in lib.calls
    assert "libusb_release_interface" not in lib.calls  # it was never claimed
    assert lib.calls[-2:] == ["libusb_close", "libusb_exit"]


def test_another_claim_failure_means_the_check_cannot_be_done() -> None:
    lib = FakeLibusb(claim_rc=LIBUSB_ERROR_ACCESS)

    with pytest.raises(CheckUnavailableError), opened(lib):
        pytest.fail("the body must not run")

    assert lib.calls[-2:] == ["libusb_close", "libusb_exit"]


def test_a_device_that_cannot_be_opened_means_the_check_cannot_be_done() -> None:
    lib = FakeLibusb(open_rc=LIBUSB_ERROR_ACCESS)

    with pytest.raises(CheckUnavailableError, match="open"), opened(lib):
        pytest.fail("the body must not run")

    assert "libusb_claim_interface" not in lib.calls
    assert lib.calls[-1] == "libusb_exit"


def test_a_library_that_does_not_start_means_the_check_cannot_be_done() -> None:
    lib = FakeLibusb(init_rc=LIBUSB_ERROR_IO)

    with pytest.raises(CheckUnavailableError), opened(lib):
        pytest.fail("the body must not run")

    assert "libusb_get_device_list" not in lib.calls


def test_an_exception_in_the_body_still_releases_closes_and_exits() -> None:
    lib = FakeLibusb()

    with pytest.raises(KeyboardInterrupt), opened(lib):
        raise KeyboardInterrupt

    assert lib.calls[-3:] == ["libusb_release_interface", "libusb_close", "libusb_exit"]


def test_every_function_has_its_argument_and_result_types_declared() -> None:
    """Without them ctypes passes pointers as 32-bit ints and returns a truncated handle."""
    lib = FakeLibusb()

    with opened(lib) as transport:
        transport.write(b"x", 250)
        transport.read(8, 10)

    used = [fn for fn in lib.functions() if fn.name in set(lib.calls)]
    assert used
    for fn in used:
        assert fn.argtypes is not UNSET, fn.name
        assert fn.restype is not UNSET, fn.name


# --- the bulk endpoints ------------------------------------------------------------------------


def test_read_gives_what_came_in_and_nothing_on_a_timeout() -> None:
    lib = FakeLibusb()
    lib.in_data.append(b"\x06")

    with opened(lib) as transport:
        assert transport.read(512, 100) == b"\x06"
        assert transport.read(512, 100) == b""

    assert [t for ep, t in lib.timeouts if ep == 0x82] == [100, 100]


def test_read_error_is_a_transport_error() -> None:
    lib = FakeLibusb(in_rc=LIBUSB_ERROR_IO)

    with opened(lib) as transport, pytest.raises(TransportError):
        transport.read(512, 100)


def test_write_sends_all_of_it_in_one_transfer_on_the_out_endpoint_with_the_timeout_asked() -> None:
    lib = FakeLibusb()

    with opened(lib) as transport:
        assert transport.write(b"\x1cX", 250) == 2

    assert lib.sent == [b"\x1cX"]
    assert lib.timeouts == [(0x01, 250)]


def test_write_error_is_a_transport_error_but_not_a_vanished_device() -> None:
    lib = FakeLibusb(out_rc=LIBUSB_ERROR_IO)

    with opened(lib) as transport, pytest.raises(TransportError) as excinfo:
        transport.write(b"\x1cX", 250)

    assert not isinstance(excinfo.value, DeviceGoneError)


@pytest.mark.parametrize(
    ("short_by", "went"), [(0, 2), (1, 1), (2, 0)], ids=["all", "part", "nothing"]
)
def test_a_timed_out_write_is_not_an_error_it_says_how_much_went(short_by: int, went: int) -> None:
    lib = FakeLibusb(out_rc=LIBUSB_ERROR_TIMEOUT, out_short_by=short_by)

    with opened(lib) as transport:
        assert transport.write(b"\x1cX", 250) == went


def test_a_write_that_went_short_without_an_error_says_how_much_went() -> None:
    lib = FakeLibusb(out_short_by=1)

    with opened(lib) as transport:
        assert transport.write(b"\x1cX", 250) == 1


def test_a_scanner_that_is_no_longer_there_is_a_device_gone_error_on_a_read() -> None:
    lib = FakeLibusb(in_rc=LIBUSB_ERROR_NO_DEVICE)

    with opened(lib) as transport, pytest.raises(DeviceGoneError):
        transport.read(512, 100)


def test_a_scanner_that_is_no_longer_there_is_a_device_gone_error_on_a_write() -> None:
    lib = FakeLibusb(out_rc=LIBUSB_ERROR_NO_DEVICE)

    with opened(lib) as transport, pytest.raises(DeviceGoneError):
        transport.write(b"\x1cX", 250)


def timed_transport(lib: FakeLibusb, clock: FakeClock) -> tuple[Callable, list[float]]:
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    return opened(lib, clock=clock, sleep=sleep), sleeps


def test_an_out_right_after_an_in_waits_for_the_gap_the_scanner_needs() -> None:
    clock = FakeClock()
    lib = FakeLibusb()
    lib.in_data.append(b"\x06")
    manager, sleeps = timed_transport(lib, clock)

    with manager as transport:
        transport.read(512, 100)
        clock.now += 0.001  # the next command comes 1 ms after the reply
        transport.write(b"\x1cX", 250)

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(OUT_AFTER_IN_GAP_S - 0.001)


def test_an_out_after_a_long_pause_or_another_out_does_not_wait() -> None:
    clock = FakeClock()
    lib = FakeLibusb()
    lib.in_data.append(b"\x06")
    manager, sleeps = timed_transport(lib, clock)

    with manager as transport:
        transport.write(b"first", 250)  # no IN yet
        transport.read(512, 100)
        clock.now += 1.0
        transport.write(b"second", 250)  # long after the IN
        transport.write(b"third", 250)  # after an OUT

    assert sleeps == []
