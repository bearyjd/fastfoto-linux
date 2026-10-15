"""Write the corrected copies listed in a plan, leaving the library itself untouched."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.library.plan import PlanRow

MANIFEST_NAME = "fastfoto-reorient-manifest.csv"
MANIFEST_COLUMNS = ("path", "old_tag", "new_tag")
STATUS_WRITTEN = "written"
STATUS_STALE = "stale"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    """What happened to one ``rotate`` row; ``reason`` explains anything but ``written``."""

    path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class ApplyResult:
    outcomes: tuple[Outcome, ...]

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


def apply_plan(rows: Sequence[PlanRow], src: Path, dest: Path) -> ApplyResult:
    """Write ``dest / path`` for every ``rotate`` row: the source with only its Orientation tag
    changed. A stale, unwritable or already existing target is reported; the other rows go on."""
    raise NotImplementedError
