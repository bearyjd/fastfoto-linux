"""The words of Documents mode: progress, results, failures, the offer to process kept pages."""

from pathlib import Path

from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.state import State
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult


def document_progress_text(  # noqa: PLR0913 - the facts of one progress line are the interface
    state: State,
    pages: int,
    *,
    pdf_page: int = 0,
    pdf_total: int = 0,
    ocr: bool = False,
    checking: bool = False,
) -> str:
    raise NotImplementedError


def document_result_banner(state: State, result: DocumentSessionResult) -> Banner | None:
    raise NotImplementedError


def document_error_banner(
    error: BaseException,
    raw_dir: Path | None = None,
    reason: DocumentRawReason | None = None,
) -> Banner:
    raise NotImplementedError


def offers_kept(result: DocumentSessionResult) -> bool:
    raise NotImplementedError


def document_kept_text(result: DocumentSessionResult) -> str:
    raise NotImplementedError
