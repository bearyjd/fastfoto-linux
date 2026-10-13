"""Minimal ESC/I-2 USB probe for the FF-680W (diagnostics only).

Usage: esci2_probe.py <gap_s> [write_timeout_ms]
Flushes stale IN data, then runs LOCK, INFO, CAPA, INFO, FIN with a fixed
gap between commands, timing how long each OUT transfer blocks.
Needs pyusb (not a project dependency): pip install pyusb
"""

import sys
import time

import usb.core
import usb.util

VID, PID = 0x04B8, 0x016B
EP_OUT, EP_IN = 0x01, 0x82
READ_TIMEOUT_MS = 3000
DEFAULT_WRITE_TIMEOUT_MS = 10000


def flush(dev) -> None:
    for _ in range(10):
        try:
            data = bytes(dev.read(EP_IN, 65536, timeout=300))
            print(f"  flushed {len(data)} stale bytes: {data[:24]!r}")
        except usb.core.USBTimeoutError:
            return


def send(dev, data: bytes, timeout_ms: int) -> None:
    start = time.monotonic()
    dev.write(EP_OUT, data, timeout=timeout_ms)
    ms = (time.monotonic() - start) * 1000
    print(f"  -> {data[:12]!r} accepted after {ms:.0f} ms")


def recv(dev, size: int) -> bytes:
    return bytes(dev.read(EP_IN, size, timeout=READ_TIMEOUT_MS))


def command(dev, name: str, timeout_ms: int) -> None:
    send(dev, f"{name:<4}x0000000".encode(), timeout_ms)
    header = recv(dev, 64).decode("latin-1")
    length = int(header[5:12], 16) if header[4] == "x" else 0
    payload = recv(dev, length) if length else b""
    print(f"  <- {header[:12]} + {len(payload)} bytes")


def main() -> int:
    args = sys.argv[1:]
    gap = float(args[0]) if args else 0.0
    write_timeout = int(args[1]) if len(args) > 1 else DEFAULT_WRITE_TIMEOUT_MS
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("scanner not found")
        return 1
    usb.util.claim_interface(dev, 0)
    try:
        flush(dev)
        try:
            send(dev, b"FIN x0000000", 2000)
            print(f"  stale-session FIN reply: {recv(dev, 512)[:16]!r}")
        except usb.core.USBError as exc:
            print(f"  stale-session FIN: {exc}")
        flush(dev)
        print(f"gap={gap}s write_timeout={write_timeout}ms")
        send(dev, b"\x1cX", write_timeout)
        print(f"  <- lock ack {recv(dev, 512)!r}")
        for name in ("INFO", "CAPA", "INFO", "FIN "):
            time.sleep(gap)
            try:
                command(dev, name, write_timeout)
            except usb.core.USBError as exc:
                print(f"  {name} FAILED: {exc}")
                return 2
        print("RESULT: all commands OK")
    finally:
        usb.util.release_interface(dev, 0)
        usb.util.dispose_resources(dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
