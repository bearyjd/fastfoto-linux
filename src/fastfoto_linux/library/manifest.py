"""The manifest of one ``fix`` run: which copies were written and which tags changed."""

from datetime import UTC, datetime

MANIFEST_PREFIX = "fastfoto-reorient-manifest"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"  # no colons: they are not allowed in names on exFAT/FAT


def utc_stamp() -> str:
    """The time a run started, fit for a file name."""
    return datetime.now(UTC).strftime(STAMP_FORMAT)
