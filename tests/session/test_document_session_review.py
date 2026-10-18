"""A document session in review mode: scan, analyse, keep the raw pages private and hand back the
draft. No PDF is made and nothing is ever deleted; saving is a separate job."""

import stat
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentError,
    DocumentResult,
    OcrOutcome,
    OcrStatus,
    PartResult,
    UnsupportedPageError,
)
from fastfoto_linux.documents.draft_edit import set_included
from fastfoto_linux.documents.draft_store import REVIEW_FILE, THUMBS_DIR, load_draft
from fastfoto_linux.documents.write import write_document
from fastfoto_linux.scanner import ScanError
from fastfoto_linux.session import DocumentRawReason, RawPolicy, Stage
from tests.documents.helpers import blank_scene, reader, text_scene
from tests.session.conftest import STAMP, raw_leftovers
from tests.session.doc_session_helpers import make_doc_request, run_doc

pytestmark = pytest.mark.usefixtures("no_real_ocr")


def review_request(out: Path, **options):
    return replace(make_doc_request(out, **options), review=True)


def visible(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def test_review_keeps_the_pages_private_and_returns_the_draft(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2), text_scene(3), text_scene(4)]
    stages: list[Stage] = []
    result = run_doc(review_request(out), doc_transport, on_stage=stages.append)
    raw = out / ".raw" / STAMP
    assert result.ok
    assert (result.error, result.cancelled, result.document) == (None, False, None)
    assert (result.raw_dir, result.raw_reason) == (raw, DocumentRawReason.REVIEW)
    assert result.pages_scanned == 4
    assert [p.name for p in result.kept_pages] == [f"page-{n:04d}.png" for n in range(1, 5)]
    assert stat.S_IMODE(raw.stat().st_mode) == 0o700
    assert visible(out) == []  # no PDF
    assert Stage.PROCESSING in stages
    assert stages[-1] is Stage.DONE
    draft = result.draft
    assert draft is not None
    assert draft.raw_dir == raw
    assert [p.blank for p in draft.pages] == [False, True, False, False]
    assert all(p.encoded is None for p in draft.pages)
    assert (raw / THUMBS_DIR / "page-0001.jpg").is_file()
    assert stat.S_IMODE((raw / REVIEW_FILE).stat().st_mode) == 0o600


def test_the_sidecar_is_there_to_open_again(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    request = review_request(out)
    result = run_doc(request, doc_transport)
    assert result.draft is not None
    settings = replace(request.settings, fallback_dpi=request.dpi)
    again = load_draft(result.raw_dir, result.kept_pages, settings)
    assert again is not None
    assert again.pages == result.draft.pages


@pytest.mark.parametrize("policy", list(RawPolicy))
def test_review_keeps_the_pages_whatever_the_policy_was(out, doc_transport, policy) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    if policy is RawPolicy.DISCARD:
        with pytest.raises(ValueError, match="review"):
            review_request(out, policy=policy)
        return
    result = run_doc(review_request(out, policy=policy), doc_transport)
    assert (result.raw_reason, result.raw_dir is not None) == (DocumentRawReason.REVIEW, True)


def test_every_page_blank_is_a_draft_to_review_not_an_error(out, doc_transport) -> None:
    doc_transport.scenes = [blank_scene(1), blank_scene(2)]
    result = run_doc(review_request(out), doc_transport)
    assert result.error is None
    assert result.draft is not None
    assert result.draft.kept == ()


def test_saving_is_a_separate_job_and_the_pages_stay(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2), text_scene(3)]
    request = review_request(out, duplex=False)
    result = run_doc(request, doc_transport)
    assert result.draft is not None
    before = sorted(p.name for p in result.raw_dir.iterdir())
    draft = set_included(result.draft, 2, True)
    document = write_document(draft, replace(request.settings, fallback_dpi=request.dpi))
    assert len(reader(document.pdf.read_bytes()).pages) == 3
    assert sorted(p.name for p in result.raw_dir.iterdir()) == before


def test_a_cancel_during_the_analysis_keeps_the_pages(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    cancel = threading.Event()

    def stage(stage: Stage) -> None:
        if stage is Stage.PROCESSING:
            cancel.set()

    result = run_doc(review_request(out), doc_transport, cancel=cancel, on_stage=stage)
    assert result.cancelled
    assert result.draft is None
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert len(result.kept_pages) == 2
    assert visible(out) == []


def test_an_unusable_page_is_an_error_and_the_pages_stay(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    doc_transport.corrupt_page = 2
    result = run_doc(review_request(out), doc_transport)
    assert isinstance(result.error, UnsupportedPageError)
    assert (result.draft, result.raw_reason) == (None, DocumentRawReason.ERROR)
    assert not result.ok
    assert len(result.kept_pages) == 2


@pytest.mark.parametrize(
    ("failure", "cancelled"), [(DocumentError("boom"), False), (DocumentCancelledError("x"), True)]
)
def test_the_analyse_seam_maps_errors_and_cancels_as_the_build_does(
    out, doc_transport, failure, cancelled
) -> None:
    doc_transport.scenes = [text_scene(1)]

    def analyse(*_args, **_kwargs):
        raise failure

    result = run_doc(review_request(out), doc_transport, analyse=analyse)
    assert (result.cancelled, result.error is None) == (cancelled, cancelled)
    assert result.raw_dir == out / ".raw" / STAMP
    assert result.raw_reason is (
        DocumentRawReason.CANCELLED if cancelled else DocumentRawReason.ERROR
    )


def test_a_scan_that_stops_part_way_makes_no_draft(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    doc_transport.pages_before_failure = 1
    doc_transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    result = run_doc(review_request(out), doc_transport)
    assert result.draft is None
    assert result.raw_reason is DocumentRawReason.SCAN_ERROR


def test_without_review_a_clean_run_is_as_before(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out), doc_transport)
    assert (result.draft, result.raw_dir, result.raw_reason) == (None, None, None)
    assert raw_leftovers(out) == []


def _built(removed: tuple[int, ...]):
    def build(pages, settings, **_kwargs) -> DocumentResult:
        pdf = settings.output_root / "Document_0001.pdf"
        part = PartResult(pdf, "Document", 1, OcrOutcome(OcrStatus.SKIPPED))
        return DocumentResult(len(pages), (), (part,), removed)

    return build


def test_pages_removed_in_review_keep_the_raw_pages(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out), doc_transport, build=_built((2,)))
    assert result.raw_reason is DocumentRawReason.PAGES_DROPPED
    assert result.raw_dir is not None


def test_pages_removed_in_review_are_still_deleted_when_the_user_says_discard(
    out, doc_transport
) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    request = make_doc_request(out, policy=RawPolicy.DISCARD)
    result = run_doc(request, doc_transport, build=_built((2,)))
    assert (result.raw_dir, result.raw_reason) == (None, None)


def test_nothing_removed_nothing_dropped_leaves_no_raw_pages(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out), doc_transport, build=_built(()))
    assert (result.raw_dir, result.raw_reason) == (None, None)
