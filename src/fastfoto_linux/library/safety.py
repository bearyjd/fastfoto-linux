"""Path rules that keep the library untouched: nothing is ever written inside it."""

import os
from pathlib import Path, PurePosixPath

from fastfoto_linux.library.plan_format import PLAN_COLUMNS


class UnsafePathError(ValueError):
    """A path would put output inside the library, or a plan path leaves the library."""


def same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    """Whether two stat results are the same folder (bind mounts and case-folding included)."""
    return os.path.samestat(first, second)


def _plain_relative(relative: str) -> PurePosixPath:
    pure = PurePosixPath(relative)
    if not pure.parts or "\x00" in relative or pure.is_absolute() or ".." in pure.parts:
        raise UnsafePathError(f"{relative!r} is not a plain relative path (no '..', not absolute)")
    return pure


def _is_inside(path: Path, root: Path) -> bool:
    return root in path.parents


def resolve_inside(root: Path, relative: str) -> Path:
    """``root / relative`` resolved; UnsafePathError unless it is a plain relative path inside."""
    pure = _plain_relative(relative)
    resolved_root = root.resolve()
    resolved = (resolved_root / pure).resolve()
    if not _is_inside(resolved, resolved_root):
        raise UnsafePathError(f"{relative!r} leads outside {root}")
    return resolved


def locate_inside(root: Path, relative: str) -> Path:
    """Where ``relative`` is inside ``root``, with its folder resolved but its name left alone.

    The folder is resolved (symlinks followed) and must stay inside ``root``. The last part is not
    resolved, so a link standing in for a file is still seen as a link.
    """
    pure = _plain_relative(relative)
    resolved_root = root.resolve()
    folder = (resolved_root / pure.parent).resolve()
    if folder != resolved_root and not _is_inside(folder, resolved_root):
        raise UnsafePathError(f"{relative!r} leads outside {root}")
    return folder / pure.name


def check_roots(src: Path, dest: Path) -> tuple[Path, Path]:
    """Both folders resolved (symlinks followed); UnsafePathError if they overlap either way."""
    resolved_src, resolved_dest = src.resolve(), dest.resolve()
    if (
        resolved_src == resolved_dest
        or _is_inside(resolved_dest, resolved_src)
        or _is_inside(resolved_src, resolved_dest)
    ):
        raise UnsafePathError(
            f"the folders overlap ({resolved_src} and {resolved_dest}); "
            "choose a destination that is neither inside the library nor holds it"
        )
    return resolved_src, resolved_dest


def _is_plan_file(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", errors="replace") as handle:
        return handle.readline().rstrip("\r\n") == ",".join(PLAN_COLUMNS)


def check_plan_output(plan: Path, src: Path) -> Path:
    """The plan path resolved; UnsafePathError if it is inside ``src`` or would replace a file
    that is not a plan."""
    target = plan.resolve()
    if _is_inside(target, src.resolve()):
        raise UnsafePathError(f"the plan file {plan} would be inside the library")
    if not target.parent.is_dir():
        raise UnsafePathError(f"the folder for the plan file {plan} does not exist")
    if target.exists() and not _is_plan_file(target):
        raise UnsafePathError(f"{plan} exists and is not a plan file; not overwriting it")
    return target


def assert_outside(path: Path, root: Path) -> None:
    """Raise UnsafePathError if ``path`` (after resolving symlinks) is inside ``root``."""
    resolved, resolved_root = path.resolve(), root.resolve()
    if resolved == resolved_root or _is_inside(resolved, resolved_root):
        raise UnsafePathError(f"refusing to write {path}: it is inside the library {root}")
