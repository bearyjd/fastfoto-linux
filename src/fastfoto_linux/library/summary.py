"""Counting plan rows and apply outcomes for the command line summaries."""

from collections.abc import Sequence
from dataclasses import dataclass

from fastfoto_linux.library.apply import ApplyResult
from fastfoto_linux.library.plan import PlanRow
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


def summarize_check(walk: WalkResult, rows: Sequence[PlanRow]) -> CheckSummary:
    raise NotImplementedError


def format_check(summary: CheckSummary, plan_name: str) -> str:
    raise NotImplementedError


def format_fix(result: ApplyResult, dest_name: str) -> str:
    raise NotImplementedError
