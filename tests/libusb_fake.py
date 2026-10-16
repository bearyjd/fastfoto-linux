"""A Python stand-in for the libusb-1.0 library, to test the ctypes binding without USB."""

import ctypes
from collections import deque
from dataclasses import dataclass

LIBUSB_ERROR_IO = -1
LIBUSB_ERROR_ACCESS = -3
LIBUSB_ERROR_BUSY = -6
LIBUSB_ERROR_TIMEOUT = -7
UNSET = object()
DESCRIPTOR_BYTES = 18
VENDOR_OFFSET = 8
PRODUCT_OFFSET = 10
FF680W = (0x04B8, 0x016B)
FUNCTION_NAMES = (
    "init",
    "exit",
    "get_device_list",
    "free_device_list",
    "get_bus_number",
    "get_device_address",
    "get_device_descriptor",
    "open",
    "close",
    "claim_interface",
    "release_interface",
    "set_auto_detach_kernel_driver",
    "bulk_transfer",
)


@dataclass(frozen=True)
class FakeDevice:
    bus: int
    address: int
    ids: tuple[int, int] = FF680W


class Function:
    """Records its calls; ``argtypes`` and ``restype`` are set by the binding, like on ctypes."""

    def __init__(self, name: str, calls: list[str], impl) -> None:
        self.name = name
        self.calls = calls
        self.impl = impl
        self.argtypes: object = UNSET
        self.restype: object = UNSET

    def __call__(self, *args):
        self.calls.append(self.name)
        return self.impl(*args)


class FakeLibusb:
    """The functions of libusb the binding uses. ``in_data`` is what the IN endpoint yields."""

    def __init__(  # noqa: PLR0913 - one knob per thing a test makes go wrong
        self,
        devices: tuple[FakeDevice, ...] = (FakeDevice(1, 4),),
        *,
        init_rc: int = 0,
        open_rc: int = 0,
        claim_rc: int = 0,
        in_rc: int = 0,
        out_rc: int = 0,
        out_short_by: int = 0,
    ) -> None:
        self.devices = devices
        self.rc = {"init": init_rc, "open": open_rc, "claim": claim_rc}
        self.in_rc, self.out_rc, self.out_short_by = in_rc, out_rc, out_short_by
        self.calls: list[str] = []
        self.opened: list[int] = []
        self.sent: list[bytes] = []
        self.in_data: deque[bytes] = deque()
        self.timeouts: list[tuple[int, int]] = []  # (endpoint, timeout_ms) of each transfer
        self._list = (ctypes.c_void_p * (len(devices) + 1))(*range(1, len(devices) + 1), None)
        for name in FUNCTION_NAMES:
            impl = getattr(self, f"_{name}")
            setattr(self, f"libusb_{name}", Function(f"libusb_{name}", self.calls, impl))

    def functions(self) -> list[Function]:
        return [v for v in vars(self).values() if isinstance(v, Function)]

    def _init(self, ctx_ptr) -> int:
        ctx_ptr.contents.value = 1
        return self.rc["init"]

    def _exit(self, ctx) -> None:
        return None

    def _get_device_list(self, ctx, list_ptr) -> int:
        list_ptr.contents.value = ctypes.addressof(self._list)
        return len(self.devices)

    def _free_device_list(self, devices, unref) -> None:
        return None

    def _get_bus_number(self, dev) -> int:
        return self.devices[int(dev) - 1].bus

    def _get_device_address(self, dev) -> int:
        return self.devices[int(dev) - 1].address

    def _get_device_descriptor(self, dev, buffer) -> int:
        vendor, product = self.devices[int(dev) - 1].ids
        buffer[VENDOR_OFFSET : VENDOR_OFFSET + 2] = list(vendor.to_bytes(2, "little"))
        buffer[PRODUCT_OFFSET : PRODUCT_OFFSET + 2] = list(product.to_bytes(2, "little"))
        return 0

    def _open(self, dev, handle_ptr) -> int:
        self.opened.append(int(dev))
        handle_ptr.contents.value = 100 + int(dev)
        return self.rc["open"]

    def _close(self, handle) -> None:
        return None

    def _claim_interface(self, handle, interface) -> int:
        return self.rc["claim"]

    def _release_interface(self, handle, interface) -> int:
        return 0

    def _set_auto_detach_kernel_driver(self, handle, enable) -> int:
        return 0

    def _bulk_transfer(  # noqa: PLR0913, PLR0917 - libusb_bulk_transfer's own signature
        self, handle, endpoint, buffer, length, transferred_ptr, timeout
    ) -> int:
        self.timeouts.append((int(endpoint), int(timeout)))
        if endpoint & 0x80:
            return self._bulk_in(buffer, length, transferred_ptr)
        self.sent.append(ctypes.string_at(buffer, length))
        transferred_ptr.contents.value = length - self.out_short_by
        return self.out_rc

    def _bulk_in(self, buffer, length, transferred_ptr) -> int:
        if self.in_rc:
            transferred_ptr.contents.value = 0
            return self.in_rc
        if not self.in_data:
            transferred_ptr.contents.value = 0
            return LIBUSB_ERROR_TIMEOUT
        data = self.in_data.popleft()[:length]
        ctypes.memmove(buffer, data, len(data))
        transferred_ptr.contents.value = len(data)
        return 0
