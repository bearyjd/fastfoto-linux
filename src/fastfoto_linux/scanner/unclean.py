"""A note that our own last scan on a USB address ended in a way that may have cut a command short.

The pre-scan check may send filler to a scanner that stays silent after a hello, but only with
evidence that the silence is the stuck session of our own failed send: the scanner may just as
well be busy with another device over Wi-Fi, and filler would corrupt that session. The evidence
is this note, written when a scan ended with an I/O error, with a SIGKILL after the grace period or
with a crash of scanimage (a status reply such as busy or jammed is not evidence: the command
channel was in step), and cleared once a check finds the scanner answering. It names the bus and
address (they change when the scanner is switched off and on), the time in UTC and, when it can be
read, the boot id: a note from another boot, or older than ``MAX_NOTE_AGE``, is ignored, as the
scanner's session it speaks of is long gone.

It lives in ``$XDG_STATE_HOME/fastfoto-linux`` (``~/.local/state`` without it; inside the app's own
sandbox in the Flatpak). Writing it must never raise: it happens while a scan error is on its way.
"""

import contextlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_NAME = "scanner-unclean"
STATE_DIR_NAME = "fastfoto-linux"
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
MAX_NOTE_AGE = timedelta(hours=24)
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
# "BBB:AAA <UTC time>" and, when the boot id could be read, " <boot id>".
_NOTE = re.compile(r"([0-9]{3}):([0-9]{3}) (\S+)(?: (\S+))?\n?")


@dataclass(frozen=True)
class _Note:
    bus: int
    address: int
    written: datetime
    boot_id: str | None


def marker_path() -> Path:
    """Where the note is kept; a relative ``XDG_STATE_HOME`` is ignored, as the XDG rules say."""
    configured = os.environ.get("XDG_STATE_HOME", "")
    base = Path(configured) if configured and Path(configured).is_absolute() else None
    root = base if base is not None else Path.home() / ".local" / "state"
    return root / STATE_DIR_NAME / MARKER_NAME


def current_boot_id() -> str | None:
    """This boot's id, or None if it cannot be read (or does not look like one)."""
    try:
        text = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    return text if _BOOT_ID.fullmatch(text) else None


def mark(bus: int, address: int, *, now: datetime | None = None) -> None:
    """Record that the last scan on ``bus``:``address`` ended abnormally. Never raises."""
    when = (datetime.now(UTC) if now is None else now).astimezone(UTC)
    fields = [f"{bus:03d}:{address:03d}", f"{when:{_TIME_FORMAT}}", current_boot_id()]
    text = " ".join(field for field in fields if field) + "\n"
    path = marker_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="ascii")
        os.replace(temporary, path)
    except OSError as exc:
        logger.warning(
            "could not note that the scan on %03d:%03d ended badly: %s", bus, address, exc
        )
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def is_marked(bus: int, address: int, *, now: datetime | None = None) -> bool:
    """True if a note names ``bus``:``address`` and still counts: it is not from another boot,
    not in the future and not older than ``MAX_NOTE_AGE``. A missing, unreadable or malformed
    note is no evidence."""
    note = _read_note()
    if note is None or (note.bus, note.address) != (bus, address):
        return False
    current = (datetime.now(UTC) if now is None else now).astimezone(UTC)
    if not timedelta(0) <= current - note.written <= MAX_NOTE_AGE:
        return False
    here = current_boot_id()
    return note.boot_id is None or here is None or note.boot_id == here


def _read_note() -> _Note | None:
    try:
        text = marker_path().read_text(encoding="ascii")
    except (OSError, ValueError):
        return None
    match = _NOTE.fullmatch(text)
    if match is None:
        return None
    bus, address, stamp, boot_id = match.groups()
    try:
        written = datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    if boot_id is not None and not _BOOT_ID.fullmatch(boot_id):
        return None
    return _Note(int(bus), int(address), written, boot_id)


def clear() -> None:
    """Remove the note (nothing to do if there is none). Never raises."""
    try:
        marker_path().unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("could not remove the note about the scanner: %s", exc)
