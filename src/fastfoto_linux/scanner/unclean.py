"""A note that our own last scan on a USB address ended abnormally.

The pre-scan check may send filler to a scanner that stays silent after a hello, but only with
evidence that the silence is the stuck session of our own failed send: the scanner may just as
well be busy with another device over Wi-Fi, and filler would corrupt that session. The evidence
is this note, written when a scan ended abnormally (a scanimage error, a SIGKILL after the grace
period, a crash of scanimage) and cleared once a check finds the scanner answering. It names the
bus and address (they change when the scanner is switched off and on) and the time, in UTC.

It lives in ``$XDG_STATE_HOME/fastfoto-linux`` (``~/.local/state`` without it; inside the app's own
sandbox in the Flatpak). Writing it must never raise: it happens while a scan error is on its way.
"""

import contextlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_NAME = "scanner-unclean"
STATE_DIR_NAME = "fastfoto-linux"
_NOTE = re.compile(r"([0-9]{3}):([0-9]{3}) \S+\n?")


def marker_path() -> Path:
    """Where the note is kept; a relative ``XDG_STATE_HOME`` is ignored, as the XDG rules say."""
    configured = os.environ.get("XDG_STATE_HOME", "")
    base = Path(configured) if configured and Path(configured).is_absolute() else None
    root = base if base is not None else Path.home() / ".local" / "state"
    return root / STATE_DIR_NAME / MARKER_NAME


def mark(bus: int, address: int, *, now: datetime | None = None) -> None:
    """Record that the last scan on ``bus``:``address`` ended abnormally. Never raises."""
    when = (datetime.now(UTC) if now is None else now).astimezone(UTC)
    text = f"{bus:03d}:{address:03d} {when:%Y-%m-%dT%H:%M:%SZ}\n"
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


def is_marked(bus: int, address: int) -> bool:
    """True if the note names ``bus``:``address``; a missing or unreadable note is no evidence."""
    try:
        text = marker_path().read_text(encoding="ascii")
    except (OSError, ValueError):
        return False
    match = _NOTE.fullmatch(text)
    return match is not None and (int(match.group(1)), int(match.group(2))) == (bus, address)


def clear() -> None:
    """Remove the note (nothing to do if there is none). Never raises."""
    try:
        marker_path().unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("could not remove the note about the scanner: %s", exc)
