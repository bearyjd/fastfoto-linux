"""Delete only unchanged originals from the last successful save, after explicit confirmation."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_store import REVIEW_FILE, THUMBS_DIR
from fastfoto_linux.gui.reviewjobs import PREVIEW_DIR, output_preview_names

Stamp = tuple[int, int, int, int]


def _stamp(info: os.stat_result) -> Stamp:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("an original page is no longer a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


@dataclass(frozen=True)
class SavedOriginals:
    folder: Path
    identity: tuple[int, int]
    originals: tuple[tuple[str, Stamp], ...]
    artifacts: tuple[tuple[str, Stamp], ...]


def capture_originals(draft: DocumentDraft) -> SavedOriginals:
    if draft.raw_dir is None or draft.raw_dir.is_symlink():
        raise ValueError("the original folder cannot be a symbolic link")
    folder = draft.raw_dir.resolve(strict=True)
    info = folder.stat()
    originals = []
    for page in draft.pages:
        if Path(page.name).name != page.name:
            raise ValueError("an original page has an unsafe name")
        stamp = _stamp((folder / page.name).lstat())
        if stamp[2:] != (page.size, page.mtime_ns):
            raise ValueError("the original pages changed since they were analysed")
        originals.append((page.name, stamp))
    names = [REVIEW_FILE]
    for page in draft.pages:
        names.extend(
            (
                f"{THUMBS_DIR}/page-{page.number:04d}.jpg",
                f"{PREVIEW_DIR}/page-{page.number:04d}.jpg",
            )
        )
        names.extend(f"{PREVIEW_DIR}/{name}" for name in output_preview_names(page.number))
    artifacts = []
    for name in names:
        path = folder / name
        if path.parent.is_symlink():
            continue
        try:
            artifacts.append((name, _stamp(path.lstat())))
        except (OSError, ValueError):
            continue
    return SavedOriginals(folder, (info.st_dev, info.st_ino), tuple(originals), tuple(artifacts))


def delete_originals(saved: SavedOriginals) -> None:
    """No recursive removal and no traversal through links; unknown or newer files stay."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(saved.folder, flags)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != saved.identity:
            raise ValueError("the original folder was replaced; nothing was deleted")
        for name, stamp in saved.originals:
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if _stamp(current) != stamp:
                raise ValueError("the original pages changed; nothing was deleted")
        for name, _stamp_value in saved.originals:
            os.unlink(name, dir_fd=descriptor)
        for name, stamp in saved.artifacts:
            _delete_artifact(descriptor, name, stamp, flags)
    finally:
        os.close(descriptor)


def _delete_artifact(root: int, name: str, stamp: Stamp, flags: int) -> None:
    path = Path(name)
    descriptor = root
    try:
        if path.parent != Path("."):
            descriptor = os.open(str(path.parent), flags, dir_fd=root)
        info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if _stamp(info) == stamp:
            os.unlink(path.name, dir_fd=descriptor)
    except (OSError, ValueError):
        pass  # a missing or newer generated file stays; no unrelated file is touched
    finally:
        if descriptor != root:
            os.close(descriptor)
