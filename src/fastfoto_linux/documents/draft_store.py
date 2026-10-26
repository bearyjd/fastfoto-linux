"""The review sidecar: ``review.json`` and the thumbnails in a raw folder.

``DIR/.raw/<stamp>/review.json`` (owner-only, written atomically) holds a draft: the analysis of
every page (verdict, flags, marks, trim box, partner) and the reviewer's edits, so a scan can be
reviewed again later without analysing it again. ``DIR/.raw/<stamp>/thumbs/page-NNNN.jpg`` are
the thumbnails. ``list_pages`` finds neither. The raw pages themselves are never touched.

The file is untrusted input (see ``draft_json``): anything wrong with it is logged and the folder
is analysed afresh. Its analysis is used again only while it is the analysis that would be made
now: the same ``ANALYSIS_VERSION``, the same pairing and blank rule (``duplex``, ``keep_blank``)
and every page file the same (name, size, modification time). When it is not, the pages are
analysed again and the edits are put back by raw number (the page names must still be the same).
"""

import logging
import os
import stat
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from fastfoto_linux.documents.analyse import ANALYSIS_VERSION, analyse_document
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_json import (
    ReviewFormatError,
    StoredOptions,
    StoredReview,
    decode_review,
    encode_review,
)
from fastfoto_linux.documents.private_io import write_private_atomic
from fastfoto_linux.documents.settings import DocumentSettings
from fastfoto_linux.documents.thumbs import thumbnail_name

__all__ = [
    "ANALYSIS_VERSION",
    "MAX_REVIEW_BYTES",
    "REVIEW_FILE",
    "THUMBS_DIR",
    "StoredOptions",
    "StoredReview",
    "load_draft",
    "open_draft",
    "read_review",
    "restore_edits",
    "save_draft",
]

logger = logging.getLogger(__name__)

REVIEW_FILE = "review.json"
THUMBS_DIR = "thumbs"
MAX_REVIEW_BYTES = 8 * 1024 * 1024


def save_draft(draft: DocumentDraft, settings: DocumentSettings | None = None) -> None:
    """Write ``draft`` (and the options of ``settings``) as ``review.json`` in its raw folder,
    atomically and owner-only. Raises ValueError for a draft without a folder or too big to
    read back, OSError when it cannot be written (the old file is then as it was)."""
    folder = draft.raw_dir
    if folder is None:
        raise ValueError("a draft without a folder of raw pages cannot be saved")
    data = encode_review(draft, settings, ANALYSIS_VERSION)
    if len(data) > MAX_REVIEW_BYTES:
        raise ValueError(f"the review of {len(draft.pages)} pages is too big to save")
    write_private_atomic(folder / REVIEW_FILE, data)


def _read_file(path: Path) -> bytes | None:
    """The bytes of the sidecar, None when there is none. A link, a pipe or any file that is
    not a regular file of a sane size is refused (ReviewFormatError)."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:  # a link (ELOOP) or a folder that cannot be read
        raise ReviewFormatError(f"cannot be opened ({error.strerror})") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):  # a folder, a pipe, a device: before anything reads it
            raise ReviewFormatError("is not a regular file")
        if info.st_size > MAX_REVIEW_BYTES:
            raise ReviewFormatError(f"is bigger than {MAX_REVIEW_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            data = file.read(MAX_REVIEW_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_REVIEW_BYTES:
        raise ReviewFormatError(f"is bigger than {MAX_REVIEW_BYTES} bytes")
    return data


def _with_thumbs(draft: DocumentDraft, folder: Path) -> DocumentDraft:
    """``draft`` in ``folder``, each page naming its thumbnail if the file is there."""
    pages = []
    for page in draft.pages:
        name = thumbnail_name(page.number)
        has = (folder / THUMBS_DIR / name).is_file()
        pages.append(replace(page, thumb=name if has else None))
    return replace(draft, pages=tuple(pages), raw_dir=folder)


def read_review(folder: Path, pages: Sequence[Path]) -> StoredReview | None:
    """The checked sidecar of ``folder`` for these page files (``list_pages(folder)``), or None
    when there is none or it is unusable (that is logged as a warning)."""
    path = folder / REVIEW_FILE
    try:
        data = _read_file(path)
        if data is None:
            return None
        stored = decode_review(data, [page.name for page in pages])
    except (ReviewFormatError, OSError) as error:
        logger.warning("%s %s and is ignored; the pages are analysed afresh", path, error)
        return None
    return replace(stored, draft=_with_thumbs(stored.draft, folder))


def _is_fresh(
    stored: StoredReview, pages: Sequence[Path], settings: DocumentSettings | None
) -> bool:
    """Whether the stored analysis is the one that would be made now."""
    if stored.analysis_version != ANALYSIS_VERSION or any(
        page.colour is None for page in stored.draft.pages
    ):
        return False
    if settings is not None and (
        stored.draft.duplex != settings.duplex
        or stored.draft.keep_blank != settings.keep_blank
        or not stored.fallback_dpi_known
        or stored.fallback_dpi != settings.fallback_dpi
    ):
        return False
    try:
        return all(
            (page.name, info.st_size, info.st_mtime_ns) == (saved.name, saved.size, saved.mtime_ns)
            for page, saved in zip(pages, stored.draft.pages, strict=True)
            for info in (page.stat(),)
        )
    except OSError:
        return False


def load_draft(
    folder: Path, pages: Sequence[Path], settings: DocumentSettings | None = None
) -> DocumentDraft | None:
    """The saved draft of ``folder``, only if its analysis is still good (see the module's
    text); None otherwise. ``settings`` (when given) must pair the pages as the draft does."""
    stored = read_review(folder, pages)
    if stored is None or not _is_fresh(stored, pages, settings):
        return None
    return stored.draft


def restore_edits(draft: DocumentDraft, stored: StoredReview) -> DocumentDraft:
    """``draft`` (a new analysis of the same pages) with the edits, order, splits, part names and
    paper cleanup level and despeckle switch of ``stored``, put back by raw number (a stale
    analysis never takes up the values the settings now hold)."""
    saved = stored.draft
    return replace(
        draft,
        edits=saved.edits,
        order=saved.order,
        splits=saved.splits,
        part_names=saved.part_names,
        cleanup=saved.cleanup,
        despeckle=stored.despeckle,
    )


def open_draft(  # noqa: PLR0913 - the hooks of the analysis, passed through
    folder: Path,
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    fresh: bool = False,
    thumbs: Path | None = None,
    cancel: threading.Event | None = None,
    on_page: Callable[[int, int], None] | None = None,
) -> DocumentDraft:
    """The draft of the raw pages in ``folder``: the saved one when its analysis is good, else
    the pages analysed again (writing thumbnails to ``thumbs`` if given) with the saved edits
    put back. With ``fresh`` the sidecar is ignored. Nothing is written to ``folder``."""
    stored = None if fresh else read_review(folder, pages)
    if stored is not None and _is_fresh(stored, pages, settings):
        return stored.draft
    draft = analyse_document(
        pages, settings, cancel=cancel, on_page=on_page, encode=False, thumbs=thumbs
    )
    return draft if stored is None else restore_edits(draft, stored)
