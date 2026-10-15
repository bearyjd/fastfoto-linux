"""The plan file: one row per JPEG saying what ``fix`` should do, written by ``check``."""

import csv
import errno
import io
import math
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.library import fdio
from fastfoto_linux.library.plan_format import PLAN_COLUMNS
from fastfoto_linux.library.planout import PlanTarget, open_plan_target, publish_plan
from fastfoto_linux.library.safety import resolve_inside
from fastfoto_linux.library.tags import (
    CLOCKWISE_BY_TAG,
    MAX_TAG,
    MIN_TAG,
    QUARTER_TURNS,
    compose_tag,
)

MAX_PLAN_BYTES = 64 * 1024 * 1024  # a plan has a few hundred bytes per photo
ENCODING = "utf-8"
ENCODING_ERRORS = "surrogateescape"  # file names that are not UTF-8 survive the round trip
SCORE_FORMAT = ".3f"
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _blank_if_none(value: int | None) -> str:
    return "" if value is None else str(value)


def write_plan(target: PlanTarget | Path, rows: tuple[PlanRow, ...]) -> None:
    """Write ``rows`` as CSV (relative POSIX paths only) through a staging file.

    ``target`` is the plan's open folder from ``open_plan_target`` (the way ``check`` writes, so
    that the folder cannot be swapped meanwhile) or a plain path, which is opened here. Only an
    older plan is replaced; a link, special file or other file at the path is refused.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(PLAN_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.path,
                row.action.value,
                row.rotate_cw,
                _blank_if_none(row.old_tag),
                _blank_if_none(row.new_tag),
                format(row.score, SCORE_FORMAT),
                row.reason,
                row.size,
                row.mtime_ns,
                row.sha256,
            ]
        )
    data = buffer.getvalue().encode(ENCODING, ENCODING_ERRORS)
    if isinstance(target, PlanTarget):
        publish_plan(target, data)
        return
    with open_plan_target(target) as opened:
        publish_plan(opened, data)


def _whole_number(fields: dict[str, str], name: str, low: int, high: int | None = None) -> int:
    try:
        value = int(fields[name])
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {fields[name]!r}") from None
    if value < low or (high is not None and value > high):
        raise ValueError(f"{name} is out of range: {value}")
    return value


def _optional_tag(fields: dict[str, str], name: str, allowed: Sequence[int]) -> int | None:
    if not fields[name]:
        return None
    value = _whole_number(fields, name, min(allowed), max(allowed))
    if value not in allowed:
        raise ValueError(f"{name} must be one of {tuple(allowed)}, got {value}")
    return value


def _score(fields: dict[str, str]) -> float:
    try:
        value = float(fields["score"])
    except ValueError:
        raise ValueError(f"score must be a number, got {fields['score']!r}") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"score must be a finite number of at least 0, got {fields['score']!r}")
    return value


def _action(text: str) -> Action:
    try:
        return Action(text)
    except ValueError:
        raise ValueError(f"unknown action {text!r}") from None


def _check_rotate(row: PlanRow) -> None:
    if row.rotate_cw == 0 or row.old_tag is None or row.new_tag is None:
        raise ValueError("a rotate row needs a turn, old_tag and new_tag")
    if not _SHA256.fullmatch(row.sha256):
        raise ValueError("a rotate row needs the sha256 of the file it was planned for")
    if compose_tag(row.old_tag, row.rotate_cw) != row.new_tag:
        raise ValueError(f"new_tag {row.new_tag} does not match old_tag and rotate_cw")


def _parse_row(record: list[str], root: Path) -> PlanRow:
    if len(record) != len(PLAN_COLUMNS):
        raise ValueError(f"expected {len(PLAN_COLUMNS)} columns, found {len(record)}")
    fields = dict(zip(PLAN_COLUMNS, record, strict=True))
    resolve_inside(root, fields["path"])
    if fields["sha256"] and not _SHA256.fullmatch(fields["sha256"]):
        raise ValueError("sha256 must be 64 lowercase hexadecimal digits")
    row = PlanRow(
        path=fields["path"],
        action=_action(fields["action"]),
        rotate_cw=_whole_number(fields, "rotate_cw", 0, max(QUARTER_TURNS)),
        old_tag=_optional_tag(fields, "old_tag", range(MIN_TAG, MAX_TAG + 1)),
        new_tag=_optional_tag(fields, "new_tag", tuple(sorted(CLOCKWISE_BY_TAG))),
        score=_score(fields),
        reason=fields["reason"],
        size=_whole_number(fields, "size", 0),
        mtime_ns=_whole_number(fields, "mtime_ns", 0),
        sha256=fields["sha256"],
    )
    if row.rotate_cw not in QUARTER_TURNS:
        raise ValueError(f"rotate_cw must be one of {QUARTER_TURNS}, got {row.rotate_cw}")
    if row.action is Action.ROTATE:
        _check_rotate(row)
    return row


def _read_plan_text(path: Path) -> str:
    """The text of the plan at ``path``, read through one descriptor opened without following
    a link or waiting for a writer; PlanError for a link, a pipe, a device or a huge file."""
    try:
        fd = os.open(path, fdio.READ_FLAGS)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise PlanError(f"plan {path} is a link; give the plan file itself") from error
        raise PlanError(f"cannot read plan {path}: {error.strerror or error}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PlanError(f"plan {path} is not a regular file")
        if info.st_size > MAX_PLAN_BYTES:
            raise PlanError(f"plan {path} is too large ({info.st_size} bytes)")
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as handle:
        try:
            data = handle.read(MAX_PLAN_BYTES + 1)
        except OSError as error:
            raise PlanError(f"cannot read plan {path}: {error.strerror or error}") from error
    if len(data) > MAX_PLAN_BYTES:
        raise PlanError(f"plan {path} is too large")
    return data.decode(ENCODING, ENCODING_ERRORS)


def read_plan(path: Path, src: Path) -> tuple[PlanRow, ...]:
    """Read a plan and validate it against the library folder ``src``; PlanError on a bad row."""
    text = _read_plan_text(path)
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None:
        raise PlanError(f"plan {path} is empty (it has no header line)")
    if tuple(header) != PLAN_COLUMNS:
        raise PlanError(f"line 1: the header must be {','.join(PLAN_COLUMNS)}")
    root, rows, seen = src.resolve(), [], set()
    for record in reader:
        if not record:
            continue
        try:
            row = _parse_row(record, root)
            if row.path in seen:
                raise ValueError(f"{row.path!r} appears twice")
        except ValueError as error:
            raise PlanError(f"line {reader.line_num}: {error}") from error
        seen.add(row.path)
        rows.append(row)
    return tuple(rows)
