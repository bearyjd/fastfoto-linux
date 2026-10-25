"""Names of the generated review previews: built here from server-side values only.

A cropped output preview is ``page-NNNN-output-{mode}-{cleanup}-r{turns}-c{hash}{ext}`` where
``hash`` is 12 hex digits of a digest of the crop edges and turns. Nothing a user or a file
supplies is in a name, so a name can neither climb out of the previews folder nor name another
page. ``is_output_preview_name`` is the one test for accepting and for deleting such a file.
"""

import hashlib
import os
import re
from pathlib import Path

from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.page_crop import PageCrop

PREVIEW_DIR = "previews"
MAX_PAGE_NUMBER = 9999  # the four digits of a name
MAX_CROP_PREVIEWS = 8  # cropped output previews kept per page; the oldest go first
_EXTENSIONS = (".jpg", "-crop.png")


def output_suffix(mode: ColourMode, cleanup: CleanupPolicy, turns: int) -> str:
    return f"-output-{mode.value}-{cleanup.value}-r{turns}"


def crop_tag(crop: PageCrop, turns: int) -> str:
    """12 hex digits naming a crop and the turns applied after it."""
    text = f"{crop.left}.{crop.top}.{crop.right}.{crop.bottom}.r{turns}"
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:12]


def output_preview_names(number: int) -> tuple[str, ...]:
    """The uncropped output names, a fixed whitelist to accept or remove with the originals.

    The legacy names (made before paper cleanup existed) stay, so old previews are still removed.
    """
    legacy = tuple(
        f"page-{number:04d}-output-{mode.value}{suffix}.jpg"
        for mode in ColourMode
        for suffix in ("", "-r0", "-r1", "-r2", "-r3")
    )
    current = tuple(
        f"page-{number:04d}{output_suffix(mode, level, turns)}{extension}"
        for mode in ColourMode
        for level in CleanupPolicy
        for turns in range(4)
        for extension in _EXTENSIONS
    )
    return legacy + current


def _cropped_pattern(number: int) -> re.Pattern[str]:
    modes = "|".join(re.escape(mode.value) for mode in ColourMode)
    levels = "|".join(re.escape(level.value) for level in CleanupPolicy)
    extensions = "|".join(re.escape(extension) for extension in _EXTENSIONS)
    return re.compile(
        rf"page-{number:04d}-output-(?:{modes})-(?:{levels})-r[0-3]-c[0-9a-f]{{12}}(?:{extensions})"
    )


def is_output_preview_name(number: int, name: object) -> bool:
    """True for a cropped output preview name of page ``number``; no path, no other shape."""
    if type(number) is not int or not 1 <= number <= MAX_PAGE_NUMBER or not isinstance(name, str):
        return False
    return _cropped_pattern(number).fullmatch(name) is not None


def checked_preview_path(folder: Path, name: str) -> Path:
    """Where to write ``name`` in the previews ``folder``: never through a link, never outside.

    ``ensure_private_dir`` (``O_NOFOLLOW``) must have run on ``folder`` first: it refuses a
    ``folder`` that is itself a link. The containment is judged on resolved paths, but the path
    returned is ``folder / name`` as the caller spelled it, so callers that compare it with their
    own ``folder`` still match when an ancestor of ``folder`` is a link (``/home -> /var/home``).
    A link planted at the name is removed (not followed), so the write replaces the link itself.
    """
    root = folder.resolve(strict=True)
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("the preview would be written outside its folder")
    if (root / name).is_symlink():
        (root / name).unlink()
    resolved = (root / name).resolve()
    if resolved.parent != root or not resolved.is_relative_to(root):
        raise ValueError("the preview would be written outside its folder")
    return folder / name


def cropped_previews(folder: Path, number: int) -> list[Path]:
    """The regular files in ``folder`` named like a cropped output preview of page ``number``,
    oldest first. Links, folders and everything else are left out."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    found = []
    for entry in entries:
        if not is_output_preview_name(number, entry.name):
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if entry.is_file(follow_symlinks=False):
            found.append((info.st_mtime_ns, entry.name))
    return [folder / name for _stamp, name in sorted(found)]


def prune_crop_previews(folder: Path, number: int, keep: int = MAX_CROP_PREVIEWS) -> None:
    """Remove the oldest cropped previews of the page beyond ``keep``."""
    root = folder.resolve(strict=True)
    for path in cropped_previews(root, number)[:-keep] if keep else cropped_previews(root, number):
        if path.parent == root and path.resolve().is_relative_to(root):
            try:
                path.unlink()
            except OSError:
                continue  # a file that cannot go stays; the bound is best effort
