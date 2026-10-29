"""Seed the tilt of the pages of a draft: read each page again, measure it, set its angle.

Opt-in (``DocumentSettings.deskew``) and per page: only a kept page with no angle and no crop is
measured, and a page the estimate abstains on is left as scanned. The pixels are read again from
the raw folder, as the writer reads them (load, trim), so the estimate sees the frame the angle
will be applied to. Nothing is saved; the new draft carries the angles.
"""

import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2

from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.deskew import SkewEstimate, SkewStatus, estimate_skew
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_edit import set_deskew
from fastfoto_linux.documents.errors import DocumentEditError, stop_if_cancelled
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.settings import DocumentSettings

logger = logging.getLogger(__name__)


def estimate_page(
    draft: DocumentDraft, number: int, *, cancel: threading.Event | None = None
) -> SkewEstimate:
    """The tilt of one raw page (counted from 1) whatever its edits are, measured on its trimmed
    pixels; ``NO_SOURCE`` when the draft has no folder to read the page from."""
    if not 1 <= number <= len(draft.pages):
        raise DocumentEditError(f"page {number} is not in the document")
    page = draft.pages[number - 1]
    if draft.raw_dir is None:
        return SkewEstimate(SkewStatus.NO_SOURCE)
    stop_if_cancelled(cancel, f"page {number} of {len(draft.pages)} was measured")
    loaded = load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi)
    try:
        return estimate_skew(page.trim.apply(loaded), cancel=cancel)
    except (ValueError, cv2.error):  # a trim box that leaves nothing, or a page OpenCV refuses
        logger.info("page %d deskew could not be measured", number)
        return SkewEstimate(SkewStatus.UNSURE)


def estimate_deskew(
    draft: DocumentDraft, *, cancel: threading.Event | None = None
) -> tuple[DocumentDraft, Mapping[int, SkewStatus]]:
    """``draft`` with an angle on each kept page that has none and no crop and whose tilt can be
    measured, and the outcome for every page that was looked at (a page with an angle is not;
    a cropped page is ``CROPPED``). Raises DocumentCancelledError when ``cancel`` is set."""
    statuses: dict[int, SkewStatus] = {}
    for page in draft.kept:
        edit = draft.edits.get(page.number, PageEdit())
        if edit.deskew_tenths is not None:
            continue
        if edit.crop is not None:
            statuses[page.number] = SkewStatus.CROPPED
            continue
        found = estimate_page(draft, page.number, cancel=cancel)
        statuses[page.number] = found.status
        logger.info("page %d deskew %s %d", page.number, found.status, found.tenths)
        if found.status is SkewStatus.ESTIMATED:
            draft = set_deskew(draft, page.number, found.tenths)
    return draft, statuses


def analyse_and_seed(
    pages: Sequence[Path], settings: DocumentSettings, **hooks: Any
) -> DocumentDraft:
    """``analyse_document`` and, when ``settings.deskew``, the angles (the ``analyse`` hook of a
    scan session that is reviewed, so the seeded angles are in the saved draft)."""
    draft = analyse_document(pages, settings, **hooks)
    if settings.deskew:
        draft, _ = estimate_deskew(draft, cancel=hooks.get("cancel"))
    return draft
