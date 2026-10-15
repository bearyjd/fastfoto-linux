"""Path rules that keep the library untouched: nothing is ever written inside it."""

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    """A path would put output inside the library, or a plan path leaves the library."""


class UnreadableLibraryError(UnsafePathError):
    """Folders of the library could not be listed, so a folder cannot be proven to be outside it."""


def same_directory(first: os.stat_result, second: os.stat_result) -> bool:
    """Whether two stat results are the same folder (bind mounts and case-folding included)."""
    return os.path.samestat(first, second)


FolderId = tuple[int, int]


def folder_id(info: os.stat_result) -> FolderId:
    """What names a folder on disk, whatever path or mount it was reached through."""
    return (info.st_dev, info.st_ino)


@dataclass(frozen=True)
class Library:
    """The library folder and the identity of every folder below it (see ``folder_id``).

    A bind mount of a library subfolder is another way to reach that folder, and walking ``..``
    from it leaves the library's tree; so being inside the library is judged by identity.

    ``unlisted_folders`` counts the folders the walk could not list: what is below them is missing
    from ``folders``, so a bind mount of it cannot be told from a new folder (``refuse_unproven``).
    """

    root: os.stat_result
    folders: frozenset[FolderId] = frozenset()
    unlisted_folders: int = 0

    def contains(self, info: os.stat_result) -> bool:
        """Whether the folder ``info`` is the library or any folder below it."""
        return same_directory(info, self.root) or folder_id(info) in self.folders

    @cached_property
    def devices(self) -> frozenset[int]:
        """The devices the library's folders are on (a bind mount shares its original's device)."""
        return frozenset({self.root.st_dev, *(device for device, _ in self.folders)})

    def refuse_unproven(self, info: os.stat_result) -> None:
        """UnreadableLibraryError if folders could not be listed and ``info`` is on the library's
        device: it might be a bind mount of one of them. A folder on another device cannot be."""
        if self.unlisted_folders and folder_id(info)[0] in self.devices:
            count = self.unlisted_folders
            raise UnreadableLibraryError(
                f"{count} {'folder' if count == 1 else 'folders'} in the library could not be "
                "read, so FastFoto can't prove the output folder is outside it; fix their "
                "permissions or pick an output folder on another drive"
            )


# A bare stat result stands for the library folder alone, without the folders below it.
LibraryRef = Library | os.stat_result


def as_library(library: LibraryRef) -> Library:
    return library if isinstance(library, Library) else Library(library)


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


def _existing_stats(path: Path) -> list[os.stat_result]:
    """Stat results of ``path`` and of each of its ancestors that exists (links followed)."""
    found = []
    for candidate in (path, *path.parents):
        try:
            found.append(os.stat(candidate))
        except OSError:
            continue
    return found


def _is_same_folder_or_below(inner: Path, outer: Path) -> bool:
    """Whether ``inner`` is ``outer`` or lies below it, judged by what the folders are on disk.

    Paths can name one folder in different ways (bind mounts, case-folding filesystems), so some
    existing ancestor-or-self of ``inner`` is compared with ``outer`` by device and inode.
    """
    try:
        outer_stat = os.stat(outer)
    except OSError:
        return False
    return any(same_directory(known, outer_stat) for known in _existing_stats(inner))


def check_roots(src: Path, dest: Path) -> tuple[Path, Path]:
    """Both folders resolved (symlinks followed); UnsafePathError if they overlap either way.

    Overlap is judged by path and, again, by identity on disk, so two spellings of one folder
    are caught too.
    """
    resolved_src, resolved_dest = src.resolve(), dest.resolve()
    if (
        resolved_src == resolved_dest
        or _is_inside(resolved_dest, resolved_src)
        or _is_inside(resolved_src, resolved_dest)
        or _is_same_folder_or_below(resolved_dest, resolved_src)
        or _is_same_folder_or_below(resolved_src, resolved_dest)
    ):
        raise UnsafePathError(
            f"the folders overlap ({resolved_src} and {resolved_dest}); "
            "choose a destination that is neither inside the library nor holds it"
        )
    return resolved_src, resolved_dest


def assert_outside(path: Path, root: Path) -> None:
    """Raise UnsafePathError if ``path`` (after resolving symlinks) is inside ``root``."""
    resolved, resolved_root = path.resolve(), root.resolve()
    if resolved == resolved_root or _is_inside(resolved, resolved_root):
        raise UnsafePathError(f"refusing to write {path}: it is inside the library {root}")
