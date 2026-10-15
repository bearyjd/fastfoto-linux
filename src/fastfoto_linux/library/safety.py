"""Path rules that keep the library untouched: nothing is ever written inside it."""

from pathlib import Path


class UnsafePathError(ValueError):
    """A path would put output inside the library, or a plan path leaves the library."""


def resolve_inside(root: Path, relative: str) -> Path:
    """``root / relative`` resolved; UnsafePathError unless it is a plain relative path inside."""
    raise NotImplementedError


def check_roots(src: Path, dest: Path) -> tuple[Path, Path]:
    """Both folders resolved (symlinks followed); UnsafePathError if they overlap either way."""
    raise NotImplementedError


def check_plan_output(plan: Path, src: Path) -> Path:
    """The plan path resolved; UnsafePathError if it is inside ``src`` or would replace a file
    that is not a plan."""
    raise NotImplementedError


def assert_outside(path: Path, root: Path) -> None:
    """Raise UnsafePathError if ``path`` (after resolving symlinks) is inside ``root``."""
    raise NotImplementedError
