"""The review lifecycle, kept separate from the scanner controller and Qt."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from fastfoto_linux.documents import DocumentSettings
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_store import save_draft
from fastfoto_linux.gui.docform import to_document_settings
from fastfoto_linux.gui.docreport import document_error_banner
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.review import ReviewState
from fastfoto_linux.gui.reviewdelete import SavedOriginals, capture_originals, delete_originals
from fastfoto_linux.gui.reviewjobs import PREVIEW_DIR, PreviewResult
from fastfoto_linux.gui.state import ActionBlockedError, Mode, State, transition
from fastfoto_linux.session import DocumentSessionResult, SessionResult

if TYPE_CHECKING:
    from fastfoto_linux.gui.controller import Controller

logger = logging.getLogger(__name__)
_OPENABLE = frozenset(
    {State.READY, State.NO_SCANNER, State.DONE, State.FAILED, State.CANCELLED, State.REVIEWING}
)


class ReviewSide:
    """A controller component; owns review jobs, their immutable snapshot and saved originals."""

    def __init__(self, controller: "Controller") -> None:
        self._controller = controller
        self.state: ReviewState | None = None
        self.dirty = False
        self._settings: DocumentSettings | None = None
        self._opening_settings: DocumentSettings | None = None
        self._pending = ""
        self._saved: DocumentDraft | None = None
        self._originals: SavedOriginals | None = None
        self._saving_originals: SavedOriginals | None = None
        self.preview_path: Path | None = None
        self.preview_number = 0
        self._preview_requested: tuple[DocumentDraft, int] | None = None

    @property
    def active(self) -> bool:
        c = self._controller
        return self.state is not None and c.mode is Mode.DOCUMENTS and c.state is State.REVIEWING

    @property
    def can_save(self) -> bool:
        return self.active and bool(self.state.draft.kept) and not self._worker_busy

    @property
    def can_delete_originals(self) -> bool:
        return self._originals is not None and self._controller.state is State.DONE

    @property
    def can_reopen(self) -> bool:
        return self._saved is not None and self._saved.raw_dir is not None and not self._worker_busy

    @property
    def _worker_busy(self) -> bool:
        return bool(getattr(self._controller._worker, "busy", False))

    def enable(self) -> None:
        self._controller._docs.review_enabled = True

    def leaving(self) -> bool:
        return not self.active or self.flush()

    def edit(self, operation: str, *args: object) -> bool:
        if not self.active:
            raise ActionBlockedError("there is no document review to edit")
        assert self.state is not None
        self.state = getattr(self.state, operation)(*args)
        if operation not in {"only_flagged", "focused"}:
            self.dirty = True
            self._originals = None
        self._controller._changed()
        return True

    def flush(self) -> bool:
        if not self.dirty or self.state is None:
            return True
        try:
            save_draft(self.state.draft, self._settings)
        except (OSError, ValueError) as error:
            logger.warning("could not save the document review: %s", error)
            self._controller._banner = Banner("error", "Could not save the review. " + str(error))
            self._controller._changed()
            return False
        self.dirty = False
        return True

    def _current_settings(self) -> DocumentSettings:
        c = self._controller
        settings = to_document_settings(
            c.document_form, Path(c.form.output_folder).expanduser(), ocr_available=c.ocr_available
        )
        return replace(settings, fallback_dpi=c.document_form.dpi)

    def open_folder(self, folder: Path) -> bool:
        c = self._controller
        if c.state not in _OPENABLE or self._worker_busy:
            raise ActionBlockedError("cannot open a past scan while another job is running")
        if not self.leaving():
            return False
        c.set_mode(Mode.DOCUMENTS)
        self._opening_settings = self._current_settings()
        c._worker.analyse_folder(folder, self._opening_settings)
        self._pending = "open"
        self._preview_requested = None
        self.preview_path = None
        self._set(State.PROCESSING)
        return True

    def save(self) -> None:
        if not self.can_save:
            raise ActionBlockedError("keep at least one page before saving the document")
        if not self.flush():
            return
        assert self.state is not None and self._settings is not None
        try:
            self._saving_originals = capture_originals(self.state.draft)
        except (OSError, ValueError):
            self._saving_originals = None
        self._controller._worker.write_draft(self.state.draft, self._settings)
        self._pending = "save"
        self._set(State.PROCESSING)

    def back(self) -> None:
        if not self.active or not self.flush():
            return
        if self._worker_busy:
            raise ActionBlockedError("wait for the page preview before going back")
        self._preview_requested = None
        self.preview_path = None
        self._controller.check_scanner()

    def reopen(self) -> None:
        if not self.can_reopen:
            raise ActionBlockedError("there are no saved original pages to review again")
        assert self._saved is not None and self._saved.raw_dir is not None
        self.open_folder(self._saved.raw_dir)

    def finished(self, result: SessionResult | DocumentSessionResult) -> bool:
        if not isinstance(result, DocumentSessionResult):
            return False
        if self._pending == "save":
            return self._finish_save(result)
        if result.draft is not None and result.error is None and not result.cancelled:
            self._accept(result.draft)
            return True
        if self._pending == "open" and self.state is not None:
            self._pending = ""
            self._set(
                State.REVIEWING, document_error_banner(result.error) if result.error else None
            )
            return True
        self._pending = ""
        return False

    def _finish_save(self, result: DocumentSessionResult) -> bool:
        self._pending = ""
        if result.error is not None or result.cancelled or result.document is None:
            self._set(
                State.REVIEWING,
                document_error_banner(result.error)
                if result.error
                else Banner("info", "Save cancelled. Your edits are kept."),
            )
            return True
        if not result.document.ok:
            self._originals = None
            self._set(State.REVIEWING, self._controller._docs.result_banner(State.DONE, result))
            return True
        assert self.state is not None
        self._saved, self._originals = self.state.draft, self._saving_originals
        return False

    def _accept(self, draft: DocumentDraft) -> None:
        if self._pending == "open":
            self._settings = self._opening_settings
        else:
            self._settings = self._controller._docs.review_settings or self._current_settings()
        assert self._settings is not None
        self._settings = replace(self._settings, duplex=draft.duplex, keep_blank=draft.keep_blank)
        self._pending = ""
        self.state = ReviewState(draft)
        self.dirty = True
        self.preview_path, self.preview_number = None, 0
        self._originals = None
        self._controller._result = DocumentSessionResult(draft=draft, raw_dir=draft.raw_dir)
        self._set(State.REVIEWING)

    def error(self, error: Exception) -> bool:
        if self._pending and self.state is not None:
            self._pending = ""
            self._set(State.REVIEWING, document_error_banner(error))
            return True
        return False

    def preview(self, number: int, view: str = "source") -> str:
        if view != "source":
            raise NotImplementedError("output preview snapshots are not implemented")
        if not self.active or self.state is None:
            raise ActionBlockedError("there is no page to preview")
        self.state.focused(number)  # validate the raw number before starting a job
        if self.preview_number == number and self.preview_path is not None:
            return self.preview_path.as_uri()
        self._preview_requested = self.state.draft, number
        self.preview_path, self.preview_number = None, 0
        self._controller._worker.preview_page(self.state.draft, number)
        return ""

    def preview_ready(self, answer: PreviewResult) -> None:
        source, number, path, error = answer
        if not self.active or self.state is None:
            return
        request = self._preview_requested
        if (
            source is not self.state.draft
            or request is None
            or request[0] is not source
            or request[1] != number
        ):
            return
        if path is not None and path != source.raw_dir / PREVIEW_DIR / f"page-{number:04d}.jpg":
            return
        self._preview_requested = None
        if error:
            self._controller._banner = Banner("error", "Could not preview the page. " + error)
        else:
            self.preview_path, self.preview_number = path, number
        self._controller._changed()

    def delete_originals(self, confirmed: bool = False) -> None:
        if not confirmed:
            raise ValueError("confirm deleting the original pages first")
        if not self.can_delete_originals or self._originals is None:
            raise ActionBlockedError("original pages can only be deleted after a successful Save")
        delete_originals(self._originals)
        self._saved, self._originals = None, None
        self.state = None
        self._controller._banner = Banner("info", "The original pages were deleted.")
        self._controller._changed()

    def _set(self, state: State, banner: Banner | None = None) -> None:
        c = self._controller
        c._state = transition(c.state, state)
        c._banner = banner
        c._changed()
