"""The review lifecycle, kept separate from the scanner controller and Qt."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from fastfoto_linux.documents import DocumentSettings
from fastfoto_linux.documents.cleanup import CleanupStatus
from fastfoto_linux.documents.despeckle import DespeckleStatus
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_store import save_draft
from fastfoto_linux.documents.modes import CleanupPolicy, ColourPolicy
from fastfoto_linux.gui.docform import to_document_settings
from fastfoto_linux.gui.docreport import document_error_banner
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.review import ReviewState
from fastfoto_linux.gui.reviewdelete import SavedOriginals, capture_originals, delete_originals
from fastfoto_linux.gui.reviewdeskew import ReviewDeskew
from fastfoto_linux.gui.reviewjobs import (
    PreviewCompletion,
    PreviewMeta,
    PreviewRequest,
    PreviewResult,
)
from fastfoto_linux.gui.reviewnames import PREVIEW_DIR, preview_name_allowed
from fastfoto_linux.gui.state import ActionBlockedError, Mode, State, transition
from fastfoto_linux.session import DocumentSessionResult, SessionResult

if TYPE_CHECKING:
    from fastfoto_linux.gui.controller import Controller

logger = logging.getLogger(__name__)
# Operations that can change a page's output pixels; each names its page number first.
PAGE_AFFECTING = frozenset(
    {"toggle", "rotate", "set_colour", "set_cleanup", "set_crop", "set_deskew"}
)
# Operations that can change every page's output pixels; they take no page number.
DOCUMENT_AFFECTING = frozenset({"set_document_cleanup", "set_document_despeckle"})
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
        self.preview_cleanup_status: CleanupStatus | None = None
        self.preview_despeckle_status: DespeckleStatus | None = None
        self.preview_number = 0
        self.preview_view = "source"
        self.preview_cleaned = True
        self.preview_crop: tuple[int, int] | None = None
        self.preview_size: tuple[int, int] | None = None  # the trimmed page, source view
        self.preview_dpi: int | None = None
        self._preview_requested: PreviewRequest | None = None
        self._preview_running: PreviewRequest | None = None
        self._preview_cached: PreviewRequest | None = None
        self.deskew = ReviewDeskew(self)

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
            # These operations name their page first; another page's edit leaves this preview alone.
            affects = operation in DOCUMENT_AFFECTING or (
                operation in PAGE_AFFECTING and bool(args) and args[0] == number
            )
            # A straightened page changes the source preview too (its pixels and its name).
            redo = self.preview_view == "output" or request is not None or operation == "set_deskew"
            if number and affects and redo:
                self._preview_requested = None
                self.preview(
                    number, self.preview_view, cleaned=self.preview_cleaned, crop=self.preview_crop
                )
            elif request is not None:
                # Re-point at the new draft so a stale in-flight result cannot be re-dispatched
                # forever; the next dispatch renders the current draft and then matches.
                self._preview_requested = replace(request, draft=self.state.draft)
        self._controller._changed()
        return True

    def report_error(self, text: str) -> None:
        """Show ``text`` as the error banner."""
        self._controller._banner = Banner("error", text)
        self._controller._changed()

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
        # A past scan starts with cleanup Off and Remove specks off: the form's choices only seed
        # new scans, and an old or missing sidecar would otherwise take them. Only a sidecar that
        # holds them (version 3 for cleanup, 5 for despeckle) can say otherwise. Straighten is off
        # too: stored angles are kept, none are measured.
        self._opening_settings = replace(
            self._current_settings(), cleanup=CleanupPolicy.OFF, despeckle=False, deskew=False
        )
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
        self.preview_cleanup_status = self.preview_despeckle_status = None
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

    def _preview_matches(
        self,
        request: PreviewRequest | None,
        number: int,
        view: str,
        cleaned: bool,
        crop: tuple[int, int] | None,
    ) -> bool:
        return bool(
            request is not None
            and self.state is not None
            and request.draft is self.state.draft
            and request.number == number
            and request.view == view
            and request.cleaned is cleaned
            and request.crop == crop
            and ColourPolicy(request.policy) is ColourPolicy(self._settings.colour)
        )

    @property
    def preview_target(self) -> int:
        """The page the preview is showing or being made for (0 when there is none)."""
        request = self._preview_requested
        return self.preview_number or (request.number if request else 0)

    def preview(
        self,
        number: int,
        view: str = "source",
        *,
        cleaned: bool = True,
        crop: tuple[int, int] | None = None,
    ) -> str:
        if not self.active or self.state is None:
            raise ActionBlockedError("there is no page to preview")
        if view == "source":
            cleaned, crop = True, None
        self.state.focused(number)
        request = PreviewRequest(
            self.state.draft, number, self._settings.colour, view, cleaned, crop
        )
        identity = (number, view, cleaned, crop)
        if self._preview_matches(self._preview_cached, *identity) and self.preview_path:
            return self.preview_path.as_uri()
        if self._preview_matches(self._preview_requested, *identity):
            return ""
        self._preview_requested = request
        self.preview_view, self.preview_cleaned, self.preview_crop = view, cleaned, crop
        self.preview_path, self.preview_number = None, 0
        self.preview_cleanup_status = self.preview_despeckle_status = None
        self.preview_size = self.preview_dpi = None
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
        source, number, path, error, *measured = answer
        request = self._preview_running
        if request is None or request.view != "source":
            return None
        if request.draft is not source or request.number != number:
            return None
        size = dpi = None
        if measured and isinstance(measured[0], PreviewMeta):
            size, dpi = (measured[0].width, measured[0].height), measured[0].dpi
        return PreviewCompletion(request, path, error, size=size, dpi=dpi)

    @staticmethod
    def _preview_path_valid(request: PreviewRequest, path: Path | None) -> bool:
        if path is None:
            return True
        return path.parent == request.draft.raw_dir / PREVIEW_DIR and preview_name_allowed(
            request.number, request.view, path.name
        )

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
            request, request.number, self.preview_view, self.preview_cleaned, self.preview_crop
        ):
            self._preview_requested = None
            if completion.error:
                self._controller._banner = Banner(
                    "error", "Could not preview the page. " + completion.error
                )
            else:
                self.preview_path, self.preview_number = completion.path, request.number
                self.preview_cleanup_status = completion.cleanup_status
                self.preview_despeckle_status = completion.despeckle_status
                self.preview_size, self.preview_dpi = completion.size, completion.dpi
                self._preview_cached = request
            self._controller._changed()
        self.resume_preview()

    def resume_preview(self) -> None:
        """Send the newest wanted preview if none runs and the worker is free."""
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
