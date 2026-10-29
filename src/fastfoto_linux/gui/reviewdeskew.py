"""Straighten and Undo straighten for the page in focus, and the sentence when it is not done.

Kept out of ``reviewside`` (its size). One estimate runs at a time on the worker thread, for the
draft and page it was asked for. An answer for a draft that was edited, a page that is no longer
in focus or a review that is closed is dropped: the estimate is bounded, so it is not cancelled,
only ignored. Every sentence is a constant (no path, number or error text from the input).
"""

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.gui.reviewjobs import DESKEW_ERROR, DeskewAnswer
from fastfoto_linux.gui.state import ActionBlockedError

if TYPE_CHECKING:
    from fastfoto_linux.gui.reviewside import ReviewSide

logger = logging.getLogger(__name__)
_NO_RELIABLE_TILT = "No reliable tilt found on this page."
SENTENCES: Mapping[SkewStatus | str, str] = MappingProxyType(
    {
        SkewStatus.LEVEL: "This page is already straight (tilted less than 0.3°).",
        SkewStatus.UNSURE: _NO_RELIABLE_TILT,
        SkewStatus.EDGE: "This page may be tilted more than 10°, which is too much to straighten.",
        SkewStatus.LITTLE_INK: "There is too little text on this page to measure its tilt.",
        SkewStatus.NOT_TEXT: (
            "This page looks like a picture rather than text, so its tilt was not measured."
        ),
        SkewStatus.WOULD_CLIP: (
            "Straightening would cut off text at the page edge, so the page was left as scanned."
        ),
        SkewStatus.LOW_DPI: "The resolution is too low to measure this page's tilt.",
        SkewStatus.TOO_LARGE: "This page is too large to measure its tilt.",
        SkewStatus.NO_SOURCE: "The original page is not available, so its tilt cannot be measured.",
        SkewStatus.CROPPED: _NO_RELIABLE_TILT,  # not reachable from estimate_page
        DESKEW_ERROR: "Could not measure this page's tilt.",
    }
)


class ReviewDeskew:
    """A component of ``ReviewSide``: the per-page straighten action and its answer."""

    def __init__(self, side: "ReviewSide") -> None:
        self._side = side
        self.pending: tuple[DocumentDraft, int] | None = None
        self._message: tuple[DocumentDraft, int, str] | None = None

    @property
    def can_straighten(self) -> bool:
        """True when the page in focus may be measured now (it has no angle, nothing else runs)."""
        side = self._side
        if not side.active or side.state is None or side._worker_busy or self.pending is not None:
            return False
        edit = side.state.draft.edits.get(side.state.focus, PageEdit())
        return edit.deskew_tenths is None

    def straighten(self, number: int) -> None:
        side = self._side
        if not self.can_straighten:
            raise ActionBlockedError("wait for the current page job")
        assert side.state is not None
        if number != side.state.focus:
            raise ActionBlockedError("select the page first")
        draft = side.state.draft
        self._message = None
        side._controller._worker.estimate_page(draft, number)
        self.pending = (draft, number)
        side._controller._changed()

    def clear(self, number: int) -> None:
        """Take the angle off ``number``. The crop that straightening cleared stays cleared."""
        self._message = None
        self._side.edit("set_deskew", number, None)

    def ready(self, answer: DeskewAnswer) -> None:
        """The worker's answer (called on the GUI thread): apply it, say why not, or drop it."""
        side = self._side
        self.pending = None
        state = side.state
        if side.active and state is not None:
            if state.draft is answer.draft and state.focus == answer.number:
                self._apply(answer)
            else:
                logger.debug("dropped the tilt of page %d: the page was left", answer.number)
            side.resume_preview()
        side._controller._changed()

    def _apply(self, answer: DeskewAnswer) -> None:
        side = self._side
        if answer.status == SkewStatus.ESTIMATED:
            try:
                side.edit("set_deskew", answer.number, answer.tenths)
            except DocumentEditError:
                self._message = (answer.draft, answer.number, SENTENCES[DESKEW_ERROR])
            return
        sentence = SENTENCES.get(answer.status, SENTENCES[DESKEW_ERROR])
        self._message = (answer.draft, answer.number, sentence)
        logger.info("page %d tilt: %s", answer.number, answer.status)

    def message_text(self, number: int) -> str:
        """The sentence for ``number`` while its draft is the one asked about and it is in focus."""
        state, found = self._side.state, self._message
        if found is None or state is None:
            return ""
        draft, page, text = found
        return text if state.draft is draft and state.focus == page == number else ""
