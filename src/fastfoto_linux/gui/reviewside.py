"""The review lifecycle, kept separate from the scanner controller and Qt."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from fastfoto_linux.documents import DocumentSettings
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_store import save_draft
from fastfoto_linux.documents.modes import ColourPolicy
from fastfoto_linux.gui.docform import to_document_settings
from fastfoto_linux.gui.docreport import document_error_banner
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.review import ReviewState
from fastfoto_linux.gui.reviewdelete import SavedOriginals, capture_originals, delete_originals
from fastfoto_linux.gui.reviewjobs import (
    PREVIEW_DIR,
    PreviewCompletion,
    PreviewRequest,
    PreviewResult,
    output_preview_names,
)
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
        self.preview_view = "source"
        self._preview_requested: PreviewRequest | None = None
        self._preview_running: PreviewRequest | None = None
        self._preview_cached: PreviewRequest | None = None

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
            request = self._preview_requested
            number = self.preview_number or (request.number if request else 0)
            if number and (self.preview_view == "output" or request is not None):
                self._preview_requested = None
                self.preview(number, self.preview_view)
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
        self.preview_view = "source"
        self._preview_requested = self._preview_running = self._preview_cached = None
        self._originals = None
        self._controller._result = DocumentSessionResult(draft=draft, raw_dir=draft.raw_dir)
        self._set(State.REVIEWING)

    def error(self, error: Exception) -> bool:
        if self._pending and self.state is not None:
            self._pending = ""
            self._set(State.REVIEWING, document_error_banner(error))
            return True
        return False

    def _preview_matches(self, request: PreviewRequest | None, number: int, view: str) -> bool:
        return bool(
            request is not None
            and self.state is not None
            and request.draft is self.state.draft
            and request.number == number
            and request.view == view
            and ColourPolicy(request.policy) is ColourPolicy(self._settings.colour)
        )

    def preview(self, number: int, view: str = "source") -> str:
        if not self.active or self.state is None:
            raise ActionBlockedError("there is no page to preview")
        self.state.focused(number)
        request = PreviewRequest(self.state.draft, number, self._settings.colour, view)
        if self._preview_matches(self._preview_cached, number, view) and self.preview_path:
            return self.preview_path.as_uri()
        if self._preview_matches(self._preview_requested, number, view):
            return ""
        self._preview_requested = request
        self.preview_view = view
        self.preview_path, self.preview_number = None, 0
        self._preview_cached = None
        if not self._worker_busy:
            self._dispatch_preview(request)
        self._controller._changed()
        return ""

    def _dispatch_preview(self, request: PreviewRequest) -> None:
        self._preview_running = request
        try:
            if request.view == "source":
                self._controller._worker.preview_page(request.draft, request.number)
            else:
                self._controller._worker.preview_page(request)
        except Exception:
            self._preview_requested = self._preview_running = None
            raise

    def _preview_completion(self, answer: PreviewResult) -> PreviewCompletion | None:
        if isinstance(answer, PreviewCompletion):
            return answer
        source, number, path, error = answer
        request = self._preview_running
        if request is None or request.view != "source":
            return None
        if request.draft is not source or request.number != number:
            return None
        return PreviewCompletion(request, path, error)

    @staticmethod
    def _preview_path_valid(request: PreviewRequest, path: Path | None) -> bool:
        if path is None:
            return True
        names = (
            (f"page-{request.number:04d}.jpg",)
            if request.view == "source"
            else output_preview_names(request.number)
        )
        return path.parent == request.draft.raw_dir / PREVIEW_DIR and path.name in names

    def preview_ready(self, answer: PreviewResult) -> None:
        if not self.active or self.state is None:
            return
        completion = self._preview_completion(answer)
        if completion is None or not self._preview_path_valid(completion.request, completion.path):
            return
        request = completion.request
        if request is self._preview_running:
            self._preview_running = None
        if request is self._preview_requested and self._preview_matches(
            request, request.number, self.preview_view
        ):
            self._preview_requested = None
            if completion.error:
                self._controller._banner = Banner(
                    "error", "Could not preview the page. " + completion.error
                )
            else:
                self.preview_path, self.preview_number = completion.path, request.number
                self._preview_cached = request
            self._controller._changed()
        pending = self._preview_requested
        if pending and self._preview_running is None and not self._worker_busy:
            self._dispatch_preview(pending)

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
