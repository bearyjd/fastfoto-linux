"""Counting plan rows and apply outcomes for the command line summaries."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from fastfoto_linux.library.apply import (
    STATUS_DONE,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_STALE,
    STATUS_UNLOGGED,
    STATUS_WRITTEN,
    ApplyResult,
)
from fastfoto_linux.library.decide import (
    REASON_BACK_LOOKS_LIKE_FRONT,
    REASON_UNDECIDED,
    REASON_UPRIGHT,
)
from fastfoto_linux.library.plan import Action, PlanRow
from fastfoto_linux.library.tags import QUARTER_TURNS
from fastfoto_linux.library.walk import WalkResult


@dataclass(frozen=True)
class CheckSummary:
    jpegs: int
    other_formats: int
    symlinks: int
    unreadable_folders: int
    rotate_by_angle: dict[int, int]
    upright: int
    undecided: int
    skipped_by_reason: dict[str, int]
    backs_like_fronts: int
    skipped_folders: int = 0


def summarize_check(walk: WalkResult, rows: Sequence[PlanRow]) -> CheckSummary:
    angles = Counter(row.rotate_cw for row in rows if row.action is Action.ROTATE)
    keeps = Counter(row.reason for row in rows if row.action is Action.KEEP)
    skips = Counter(row.reason for row in rows if row.action is Action.SKIP)
    return CheckSummary(
        jpegs=len(walk.jpegs),
        other_formats=walk.other_formats,
        symlinks=walk.symlinks,
        unreadable_folders=walk.unreadable_folders,
        rotate_by_angle={angle: angles[angle] for angle in QUARTER_TURNS if angle},
        upright=keeps[REASON_UPRIGHT],
        undecided=keeps[REASON_UNDECIDED],
        skipped_by_reason=dict(sorted(skips.items())),
        backs_like_fronts=skips[REASON_BACK_LOOKS_LIKE_FRONT],
        skipped_folders=walk.skipped_folders,
    )


def _breakdown(counts: dict[int, int] | dict[str, int]) -> str:
    return ", ".join(f"{key}: {count}" for key, count in counts.items())


def format_check(summary: CheckSummary, plan_name: str) -> str:
    """The text ``check`` prints; lines for symlinks and unreadable folders only when needed."""
    rotate = sum(summary.rotate_by_angle.values())
    skipped = sum(summary.skipped_by_reason.values())
    lines = [
        f"files seen: {summary.jpegs + summary.other_formats} "
        f"(JPEG: {summary.jpegs}, other formats ignored: {summary.other_formats})"
    ]
    if summary.symlinks:
        lines.append(f"symlinks ignored: {summary.symlinks}")
    if summary.unreadable_folders:
        lines.append(f"folders that could not be read: {summary.unreadable_folders}")
    if summary.skipped_folders:
        lines.append(f"folders skipped (hidden or @eaDir): {summary.skipped_folders}")
    lines += [
        f"to rotate: {rotate} ({_breakdown(summary.rotate_by_angle)})",
        f"already upright: {summary.upright}",
        f"undecided: {summary.undecided}",
        f"skipped: {skipped}" + (f" ({_breakdown(summary.skipped_by_reason)})" if skipped else ""),
        f"backs that look like fronts: {summary.backs_like_fronts}",
        f"plan: {plan_name}",
    ]
    return "\n".join(lines)


def format_fix(result: ApplyResult, dest_name: str) -> str:
    """The counts ``fix`` prints on stdout; the manifest line only when a row is missing from it."""
    lines = [
        f"written: {result.count(STATUS_WRITTEN)}",
        f"already done: {result.count(STATUS_DONE)}",
        f"stale: {result.count(STATUS_STALE)}",
        f"already there: {result.count(STATUS_EXISTS)}",
        f"failed: {result.count(STATUS_FAILED)}",
    ]
    if result.count(STATUS_UNLOGGED):
        lines.append(f"written but not in the manifest: {result.count(STATUS_UNLOGGED)}")
    if result.leftover_staging:
        lines.append(
            f"leftover staging files: {result.leftover_staging} "
            "(from an interrupted run; delete them yourself)"
        )
    return "\n".join([*lines, f"output: {dest_name}"])


def fix_problems(result: ApplyResult) -> tuple[str, ...]:
    """One line per row that needs attention, for stderr; names are shown as ``repr`` so that
    nothing in a file name can drive the terminal."""
    return tuple(
        f"  {outcome.path!r}: {outcome.status} ({outcome.reason})"
        for outcome in result.outcomes
        if outcome.status not in (STATUS_WRITTEN, STATUS_DONE)
    )
