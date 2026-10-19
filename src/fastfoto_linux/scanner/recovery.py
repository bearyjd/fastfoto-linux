"""Durable maintenance notes: no new USB OUT after a crash until verified recovery.

Only metadata is read here. Notes have no age or process-lifetime expiry. A verified FIN or
an explicitly checked new enumeration at the same physical port is required to remove one.
"""

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path

from fastfoto_linux.scanner.power_types import PowerSettingsError
from fastfoto_linux.scanner.usb import UsbScanner, find_usb_scanners

MAX_NOTE_BYTES = 1024
MAX_NOTES = 64
MAX_USB_NUMBER = 999
NOTE_VERSION = 1
RESTART_MESSAGE = (
    "A previous scanner settings session did not finish safely. Turn the scanner off and on, "
    "then check USB reconnection before reading settings or scanning."
)
STATE_ERROR = (
    "Saved scanner recovery state cannot be read or updated safely. Keep the scanner off "
    "and repair the app's recovery state before continuing; its previous connection is unknown."
)


def _directory() -> Path:
    configured = os.environ.get("XDG_STATE_HOME", "")
    root = (
        Path(configured)
        if configured and Path(configured).is_absolute()
        else Path.home() / ".local/state"
    )
    return root / "fastfoto-linux" / "scanner-maintenance-recovery"


def marker_path(scanner: UsbScanner) -> Path:
    digest = hashlib.sha256(str(scanner.sysfs_path).encode()).hexdigest()
    return _directory() / f"{digest}.json"


def _error(
    message: str = STATE_ERROR, scanner: UsbScanner | None = None, *, path: Path | None = None
) -> PowerSettingsError:
    if path is not None or message == STATE_ERROR:
        message = f"{message} Recovery state: {path or _directory()}."
    return PowerSettingsError(message, scanner=scanner, reconnect_required=True)


def _read(path: Path) -> UsbScanner:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "r", encoding="ascii") as stream:
            text = stream.read(MAX_NOTE_BYTES + 1)
        if len(text) > MAX_NOTE_BYTES:
            raise ValueError("oversized note")
        note = json.loads(text)
        if (
            set(note) != {"version", "bus", "address", "sysfs_path"}
            or note["version"] != NOTE_VERSION
        ):
            raise ValueError("unknown note format")
        if any(
            type(note[key]) is not int or not 1 <= note[key] <= MAX_USB_NUMBER
            for key in ("bus", "address")
        ):
            raise ValueError("invalid enumeration")
        path_text = note["sysfs_path"]
        if not isinstance(path_text, str) or not Path(path_text).is_absolute() or "\0" in path_text:
            raise ValueError("invalid physical port")
        scanner = UsbScanner(note["bus"], note["address"], Path(path_text))
        if marker_path(scanner).name != path.name:
            raise ValueError("misplaced note")
        return scanner
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise _error(path=path) from exc


def pending_targets() -> tuple[UsbScanner, ...]:
    """Load durable notes without accessing a device; malformed/unreadable state fails closed."""
    try:
        with os.scandir(_directory()) as entries:
            paths = sorted(Path(entry.path) for entry in entries if entry.name.endswith(".json"))
        if len(paths) > MAX_NOTES:
            raise ValueError("too many recovery notes")
        return tuple(_read(path) for path in paths)
    except FileNotFoundError:
        return ()
    except (OSError, ValueError) as exc:
        raise _error() from exc


def require_ready(scanner: UsbScanner | None = None) -> None:
    """Refuse an unresolved target, or any unresolved target before broad discovery."""
    for pending in pending_targets():
        if (
            scanner is None
            or scanner.sysfs_path == pending.sysfs_path
            or (scanner.bus, scanner.device) == (pending.bus, pending.device)
        ):
            raise _error(RESTART_MESSAGE, pending)


def require_address_ready(bus: int, address: int) -> None:
    pending = pending_targets()
    if any((target.bus, target.device) == (bus, address) for target in pending):
        raise _error(
            RESTART_MESSAGE, next(t for t in pending if (t.bus, t.device) == (bus, address))
        )
    if pending:
        for scanner in find_usb_scanners():
            if (scanner.bus, scanner.device) == (bus, address):
                require_ready(scanner)
                return
        raise _error(RESTART_MESSAGE, pending[0])


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _make_directory(directory: Path) -> None:
    missing: list[Path] = []
    parent = directory
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for created in reversed(missing):
        _sync_directory(created.parent)


def begin(scanner: UsbScanner) -> None:
    """Persist BEFORE first maintenance I/O, after exclusive claim. Failure permits no OUT."""
    require_ready(scanner)
    path = marker_path(scanner)
    temporary: Path | None = None
    try:
        _make_directory(path.parent)
        note = {
            "version": NOTE_VERSION,
            "bus": scanner.bus,
            "address": scanner.device,
            "sysfs_path": str(scanner.sysfs_path),
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="ascii", prefix=".pending-", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(note, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except (OSError, ValueError) as exc:
        raise _error(
            "Recovery state could not be saved. No scanner commands were sent.", scanner, path=path
        ) from exc
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def complete(scanner: UsbScanner) -> None:
    """Remove only after verified FIN, no attempted I/O, or verified new enumeration."""
    path = marker_path(scanner)
    try:
        if _read(path) != scanner:
            raise _error()
        path.unlink()
        _sync_directory(path.parent)
    except OSError as exc:
        raise _error(
            "The scanner recovery note could not be cleared safely.", scanner, path=path
        ) from exc


def check_reconnection(scanners: tuple[UsbScanner, ...] | None = None) -> UsbScanner | None:
    """Explicit metadata-only check; absence or a different physical port is insufficient."""
    pending = pending_targets()
    visible = find_usb_scanners() if scanners is None else scanners
    replacements: list[UsbScanner] = []
    for original in pending:
        candidates = [
            candidate for candidate in visible if candidate.sysfs_path == original.sysfs_path
        ]
        if len(candidates) != 1 or (candidates[0].bus, candidates[0].device) == (
            original.bus,
            original.device,
        ):
            raise _error(RESTART_MESSAGE, original)
        replacements.append(candidates[0])
    for original in pending:
        complete(original)
    return replacements[0] if replacements else None
