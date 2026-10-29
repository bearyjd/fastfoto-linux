"""Names of the generated review previews: built here from server-side values only.

A cropped output preview is ``page-NNNN-output-{mode}-{cleanup}-r{turns}-c{hash}{ext}`` where
``hash`` is 12 hex digits of a digest of the crop edges and turns. Nothing a user or a file
supplies is in a name, so a name can neither climb out of the previews folder nor name another
page. ``is_output_preview_name`` is the one test for accepting and for deleting such a file.

A black and white preview with Remove specks applied has ``-s`` after the turns
(``...-bw-off-r{turns}-s...``); black and white has no cleanup level, so its name says ``off``.
Only black and white has the tag.

A source preview of a page with a tilt correction is ``page-NNNN-straight-{p|m}NNN.jpg`` (``p``
clockwise, ``m`` the other way, tenths of a degree in three digits, 001 to 100). An output
preview of such a page has ``-c{hash}`` too, the hash covering the angle.
"""

import hashlib
import os
import re
from pathlib import Path

from fastfoto_linux.documents.encode import effective_cleanup
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.page_crop import PageCrop

PREVIEW_DIR = "previews"
MAX_PAGE_NUMBER = 9999  # the four digits of a name
MAX_CROP_PREVIEWS = 8  # cropped output previews kept per page; the oldest go first
_EXTENSIONS = (".jpg", "-crop.png")


SPECKS_TAG = "-s"  # Remove specks was applied: only on a black and white name


def output_suffix(
    mode: ColourMode, cleanup: CleanupPolicy, turns: int, *, despeckle: bool = False
) -> str:
    """The name part of an output preview; ``despeckle`` must be the effective switch."""
    if despeckle:
        return f"-output-{mode.value}-{effective_cleanup(cleanup, mode).value}-r{turns}{SPECKS_TAG}"
    return f"-output-{mode.value}-{cleanup.value}-r{turns}"


def straight_suffix(tenths: int) -> str:
    """The name part of a straightened source preview: ``-straight-p041`` or ``-straight-m041``."""
    return f"-straight-{'p' if tenths > 0 else 'm'}{abs(tenths):03d}"


def crop_tag(crop: PageCrop | None, turns: int, deskew: int | None = None) -> str:
    """12 hex digits naming a crop, the turns applied after it and the tilt taken out first.

    Without a tilt the text is the one the tag always had. ``crop`` None means the whole page.
    """
    if deskew is None:
        assert crop is not None
        text = f"{crop.left}.{crop.top}.{crop.right}.{crop.bottom}.r{turns}"
    else:
        edges = "full" if crop is None else f"{crop.left}.{crop.top}.{crop.right}.{crop.bottom}"
        text = f"{edges}.r{turns}.d{deskew}"
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
    despeckled = tuple(
        f"page-{number:04d}{output_suffix(ColourMode.BW, CleanupPolicy.OFF, turns, despeckle=True)}"
        f"{extension}"
        for turns in range(4)
        for extension in _EXTENSIONS
    )
    return legacy + current + despeckled


def _cropped_pattern(number: int) -> re.Pattern[str]:
    modes = "|".join(re.escape(mode.value) for mode in ColourMode)
    levels = "|".join(re.escape(level.value) for level in CleanupPolicy)
    extensions = "|".join(re.escape(extension) for extension in _EXTENSIONS)
    tag = re.escape(SPECKS_TAG)
    bw = re.escape(ColourMode.BW.value)
    return re.compile(
        rf"page-{number:04d}-output-(?:(?:{modes})-(?:{levels})-r[0-3]|{bw}-(?:{levels})-r[0-3]{tag})"
        rf"-c[0-9a-f]{{12}}(?:{extensions})"
    )


def is_output_preview_name(number: int, name: object) -> bool:
    """True for a cropped output preview name of page ``number``; no path, no other shape."""
    if not _page_number_ok(number) or not isinstance(name, str):
        return False
    return _cropped_pattern(number).fullmatch(name) is not None


def _straight_pattern(number: int) -> re.Pattern[str]:
    return re.compile(rf"page-{number:04d}-straight-[pm](?:0(?:0[1-9]|[1-9][0-9])|100)\.jpg")


def _page_number_ok(number: object) -> bool:
    return type(number) is int and 1 <= number <= MAX_PAGE_NUMBER


def is_source_preview_name(number: int, name: object) -> bool:
    """True for ``page-NNNN.jpg`` or a straightened source preview name of page ``number``."""
    if not _page_number_ok(number) or not isinstance(name, str):
        return False
    return name == f"page-{number:04d}.jpg" or _straight_pattern(number).fullmatch(name) is not None


def preview_name_allowed(number: int, view: str, name: str) -> bool:
    """Whether ``name`` is a file name the preview of page ``number`` in ``view`` may have."""
    if view == "source":
        return is_source_preview_name(number, name)
    return name in output_preview_names(number) or is_output_preview_name(number, name)


def checked_preview_path(folder: Path, name: str) -> Path:
    """Where to write ``name`` in the previews ``folder``: never through a link, never outside.

    ``ensure_private_dir`` (``O_NOFOLLOW``) must have run on ``folder`` first: it refuses a
    ``folder`` that is itself a link. The containment is judged on resolved paths, but the path
    returned is ``folder / name`` as the caller spelled it, so callers that compare it with their
    own ``folder`` still match when an ancestor of ``folder`` is a link (common on immutable
    distributions).
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
    """The regular files in ``folder`` named like a cropped output preview or a straightened
    source preview of page ``number``, oldest first. Links, folders and the rest are left out."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    found = []
    for entry in entries:
        if not (is_output_preview_name(number, entry.name) or _straight_name(number, entry.name)):
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if entry.is_file(follow_symlinks=False):
            found.append((info.st_mtime_ns, entry.name))
    return [folder / name for _stamp, name in sorted(found)]


def _straight_name(number: int, name: str) -> bool:
    return is_source_preview_name(number, name) and name != f"page-{number:04d}.jpg"


def prune_crop_previews(folder: Path, number: int, keep: int = MAX_CROP_PREVIEWS) -> None:
    """Remove the oldest cropped previews of the page beyond ``keep``."""
    root = folder.resolve(strict=True)
    for path in cropped_previews(root, number)[:-keep] if keep else cropped_previews(root, number):
        if path.parent == root and path.resolve().is_relative_to(root):
            try:
                path.unlink()
            except OSError:
                continue  # a file that cannot go stays; the bound is best effort
