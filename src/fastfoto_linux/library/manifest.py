"""The manifest of one ``fix`` run: which copies were written and which tags changed.

It is created once per run, with a name no earlier run used, exclusively and without following
links (so nothing planted at a fixed name is ever opened), through the destination's descriptor.
Rows are written with the csv module and flushed to disk one by one.
"""

import contextlib
import csv
import io
import os
from datetime import UTC, datetime

from fastfoto_linux.library.fdio import CREATE_FLAGS, PRIVATE_MODE
from fastfoto_linux.library.plan import ENCODING, ENCODING_ERRORS, PlanRow

MANIFEST_PREFIX = "fastfoto-reorient-manifest"
MANIFEST_COLUMNS = ("path", "old_tag", "new_tag")
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"  # no colons: they are not allowed in names on exFAT/FAT
MAX_NAME_ATTEMPTS = 1000


def utc_stamp() -> str:
    """The time a run started, fit for a file name."""
    return datetime.now(UTC).strftime(STAMP_FORMAT)


def _encoded(fields: tuple[object, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerow(fields)
    return buffer.getvalue().encode(ENCODING, ENCODING_ERRORS)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]
    os.fsync(fd)


class Manifest:
    """Created on the first row, so a run that writes nothing leaves no file behind.

    ``record`` raises OSError when the manifest cannot be created or written; the caller reports
    that for the row and goes on, and the next row tries again.
    """

    def __init__(self, folder_fd: int) -> None:
        self._folder_fd = folder_fd
        self._fd: int | None = None
        self._stamp = ""

    def record(self, row: PlanRow) -> None:
        if self._fd is None:
            self._fd = self._create()
        _write_all(self._fd, _encoded((row.path, row.old_tag, row.new_tag)))

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _create(self) -> int:
        self._stamp = self._stamp or utc_stamp()
        for attempt in range(MAX_NAME_ATTEMPTS):
            suffix = f"-{attempt}" if attempt else ""
            name = f"{MANIFEST_PREFIX}-{self._stamp}{suffix}.csv"
            try:
                fd = os.open(name, CREATE_FLAGS, PRIVATE_MODE, dir_fd=self._folder_fd)
            except FileExistsError:
                continue
            try:
                _write_all(fd, _encoded(MANIFEST_COLUMNS))
            except BaseException:
                os.close(fd)
                with contextlib.suppress(OSError):  # no empty manifest is left behind
                    os.unlink(name, dir_fd=self._folder_fd)
                raise
            return fd
        raise FileExistsError(f"every manifest name for {self._stamp} is already taken")
