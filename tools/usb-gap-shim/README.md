# FF-680W USB gap shim

An `LD_PRELOAD` shim that makes the Epson FastFoto FF-680W (USB `04b8:016b`) usable with SANE's
`epsonds` backend until the backend itself is fixed.

## Root cause

The FF-680W firmware ignores a bulk OUT transfer that arrives back-to-back with the end of its
previous bulk IN reply. It NAKs the OUT forever, and SANE reports "Error during device I/O".
Measured on the real scanner: a gap of 0.5 ms or more between the end of the IN and the start of
the OUT always works, a gap of 0 always fails.

The shim wraps `libusb_bulk_transfer` and, before an OUT transfer, waits until the configured
gap has passed since the last IN transfer on the same device handle finished.

Status: with this shim preloaded, `scanimage -d epsonds:libusb:BBB:DDD -A` (open plus the option
query, i.e. the INFO and CAPA exchanges) succeeds on a real FF-680W; without it the same command
fails with "Error during device I/O". A full scan has not been tried with the shim yet.

## Build and use

From the repository root:

    make -C tools/usb-gap-shim             # builds ff680w_usb_gap.so with gcc -Wall -Wextra
    LD_PRELOAD=$PWD/tools/usb-gap-shim/ff680w_usb_gap.so scanimage -L

Needs only gcc and glibc; no libusb headers. `make -C tools/usb-gap-shim clean` removes the
library.

To address the scanner directly, find its bus and device numbers (BBB:DDD) with
`lsusb -d 04b8:016b`; they change every time the scanner is re-plugged:

    LD_PRELOAD=$PWD/tools/usb-gap-shim/ff680w_usb_gap.so scanimage -d epsonds:libusb:BBB:DDD -A

`LD_PRELOAD` has to be set in the environment of the process that actually loads libsane and talks
to the scanner: `scanimage` itself, but also `saned`, a GUI front end (XSane, Simple Scan, ...) or
the front end inside a Flatpak sandbox. Setting it in a different shell does not help.

## Environment

| Variable | Meaning |
| --- | --- |
| `FF680W_USB_GAP_US` | Gap in microseconds: an integer from `0` to `10000000` (10 s), default `2000`. `0` turns the shim into a pass-through. Anything else (not a number, negative, or above 10 s) falls back to the default. Read once, when the first transfer happens. |

## Behaviour

- Only bulk OUT endpoints (bit 7 clear) are delayed. IN transfers, and an OUT that follows another
  OUT, are never delayed. An OUT on a handle that has not had an IN yet is not delayed.
- The time of each IN completion is remembered per device handle, so several devices or handles in
  one process do not influence each other. The state is guarded by a mutex that is never held
  while sleeping or inside the real transfer, so threads do not block each other.
- The gap is applied only to the FF-680W. The handle's VID/PID is read once through
  `libusb_get_device` and `libusb_get_device_descriptor`. If those symbols cannot be found, or
  the call fails, the gap is applied anyway: a 2 ms delay on another device is harmless, a missing
  delay wedges this scanner.
- `libusb_close` is wrapped to forget the handle, so a device opened later at a recycled handle
  address is identified afresh.
- At most 16 handles are tracked at once. A 17th evicts the handle whose last IN is oldest (or that
  never had one), so busy handles keep their timestamps; an evicted handle loses its last-IN time.
- If the real `libusb_bulk_transfer` cannot be found the shim returns `LIBUSB_ERROR_NOT_FOUND`
  instead of crashing.

## Tests

`tests/test_usb_gap_shim.py` builds the shim, a stub libusb and a small driver with `gcc`, replays
IN/OUT sequences (including 8 concurrent threads) with the shim preloaded and checks the logged
timestamps (it is skipped when `gcc` is missing). Run it with `uv run pytest tests/test_usb_gap_shim.py`.

## The proper fix

This is a workaround. The real fix is a small delay (a `usleep` of about a millisecond) before
`eds_send` on USB in the sane-backends `epsonds` driver, to be upstreamed. See also
`tools/diagnostics/esci2_probe.py`, a pyusb script that exercises the same OUT-after-IN sequence
directly against the scanner with an adjustable gap.
