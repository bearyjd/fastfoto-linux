"""When the raw pages of a document session stay on disk, and why."""

import pytest

from fastfoto_linux.documents import OcrMode
from fastfoto_linux.session import DocumentRawReason, RawPolicy
from fastfoto_linux.session.documents import _keep_reason, _Outcome
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import blank_scene, text_scene
from tests.session.conftest import STAMP, kept_names, raw_leftovers
from tests.session.doc_session_helpers import make_doc_request, run_doc

pytestmark = pytest.mark.usefixtures("no_real_ocr")

BOTH_PAGES = ["page-0001.png", "page-0002.png"]
THREE_PAGES = ["page-0001.png", "page-0002.png", "page-0003.png"]
KEEP, AUTO, DISCARD = RawPolicy.KEEP, RawPolicy.AUTO, RawPolicy.DISCARD
REASON = DocumentRawReason


def test_the_raw_reasons_are_these() -> None:
    assert {reason.value for reason in DocumentRawReason} == {
        "cancelled",
        "scan_error",
        "error",
        "ocr_failed",
        "requested",
        "pages_dropped",
        "review",
        "not_deleted",
    }


@pytest.mark.parametrize(
    ("policy", "kept", "reason"),
    [
        (AUTO, False, None),
        (DISCARD, False, None),
        (KEEP, True, REASON.REQUESTED),
    ],
    ids=["auto", "discard", "keep"],
)
def test_after_a_clean_run_the_raw_pages_stay_only_when_asked_for(
    out, doc_transport, policy, kept, reason
) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out, policy=policy), doc_transport)
    assert result.ok
    assert result.raw_reason is reason
    if kept:
        assert result.raw_dir == out / ".raw" / STAMP
        assert kept_names(result.raw_dir) == BOTH_PAGES
        assert [page.name for page in result.kept_pages] == BOTH_PAGES
    else:
        assert (result.raw_dir, result.kept_pages) == (None, ())
        assert raw_leftovers(out) == []


@pytest.mark.parametrize(
    ("policy", "kept", "reason"),
    [
        (AUTO, True, REASON.PAGES_DROPPED),
        (KEEP, True, REASON.REQUESTED),
        (DISCARD, False, None),
    ],
    ids=["auto", "keep", "discard"],
)
def test_a_dropped_page_keeps_the_raw_pages_unless_discarding(
    out, doc_transport, policy, kept, reason
) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2), text_scene(3)]
    result = run_doc(make_doc_request(out, policy=policy), doc_transport)
    assert result.ok  # the PDF is complete: a blank page left out is not a problem
    assert result.document is not None
    assert result.document.dropped == (2,)
    assert result.raw_reason is reason
    assert (result.raw_dir is not None) is kept
    if kept:
        assert kept_names(result.raw_dir) == THREE_PAGES
        assert [page.name for page in result.kept_pages] == THREE_PAGES
    else:
        assert raw_leftovers(out) == []
    assert (out / "Document_0001.pdf").is_file()


def test_keep_blank_means_nothing_was_dropped_so_the_raw_pages_go(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2)]
    result = run_doc(make_doc_request(out, keep_blank=True), doc_transport)
    assert (result.raw_dir, result.raw_reason) == (None, None)


@pytest.mark.parametrize("policy", [AUTO, KEEP, DISCARD])
@pytest.mark.parametrize("mode", ["fail", "hang"])
def test_a_pdf_without_its_searchable_text_keeps_the_raw_pages_whatever_the_policy(
    out, doc_transport, monkeypatch, policy, mode
) -> None:
    fake.put_on_path(out.parent / "bin", monkeypatch)
    fake.configure(monkeypatch, mode=mode)
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    request = make_doc_request(
        out, policy=policy, ocr=OcrMode.ON, ocr_timeout_s=0.5 if mode == "hang" else None
    )
    result = run_doc(request, doc_transport)
    assert result.document is not None
    assert not result.document.ok
    assert not result.ok
    assert (out / "Document_0001.pdf").is_file()  # the plain PDF is still written
    assert result.raw_reason is REASON.OCR_FAILED
    assert kept_names(result.raw_dir) == BOTH_PAGES


@pytest.mark.parametrize("ocr", [OcrMode.AUTO, OcrMode.OFF])
def test_a_pdf_without_ocrmypdf_installed_is_a_clean_run(out, doc_transport, ocr) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out, ocr=ocr), doc_transport)
    assert result.ok
    assert (result.raw_dir, result.raw_reason) == (None, None)


def test_a_pdf_with_its_searchable_text_is_a_clean_run(out, doc_transport, monkeypatch) -> None:
    fake.put_on_path(out.parent / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="mark")
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out, ocr=OcrMode.ON), doc_transport)
    assert result.ok
    assert (out / "Document_0001.pdf").read_bytes().endswith(fake.MARKER)
    assert (result.raw_dir, result.raw_reason) == (None, None)


def test_a_run_that_ended_without_a_result_or_a_cause_keeps_the_pages() -> None:
    assert _keep_reason(DISCARD, _Outcome()) is REASON.ERROR
