"""The plan file: one row per JPEG saying what ``fix`` should do, written by ``check``."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

PLAN_COLUMNS = (
    "path",
    "action",
    "rotate_cw",
    "old_tag",
    "new_tag",
    "score",
    "reason",
    "size",
    "mtime_ns",
    "sha256",
)


class Action(StrEnum):
    ROTATE = "rotate"
    KEEP = "keep"
    SKIP = "skip"
    REVIEW = "review"


class PlanError(ValueError):
    """A plan file is malformed or unsafe; the message names the line."""


@dataclass(frozen=True)
class PlanRow:
    """What to do with one file; ``rotate_cw`` turns the displayed photo further clockwise."""

    path: str
    action: Action
    rotate_cw: int
    old_tag: int | None
    new_tag: int | None
    score: float
    reason: str
    size: int
    mtime_ns: int
    sha256: str


def write_plan(path: Path, rows: tuple[PlanRow, ...]) -> None:
    """Write ``rows`` as CSV (relative POSIX paths only)."""
    raise NotImplementedError


def read_plan(path: Path, src: Path) -> tuple[PlanRow, ...]:
    """Read a plan and validate it against the library folder ``src``; PlanError on a bad row."""
    raise NotImplementedError
