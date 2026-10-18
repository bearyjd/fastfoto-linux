"""``DocumentResult`` with parts: the old fields are derived from them."""

from pathlib import Path

from fastfoto_linux.documents import DocumentResult, OcrOutcome, OcrStatus, PartResult


def _part(
    name: str, pages: int, status: OcrStatus = OcrStatus.DONE, detail: str = ""
) -> PartResult:
    return PartResult(Path(f"/out/{name}_0001.pdf"), name, pages, OcrOutcome(status, detail))


def test_one_part_gives_the_old_fields() -> None:
    result = DocumentResult(pages_read=4, dropped=(2,), parts=(_part("Doc", 3),))
    assert result.pdf == Path("/out/Doc_0001.pdf")
    assert (result.pages_in_pdf, result.ocr.status, result.ok) == (3, OcrStatus.DONE, True)
    assert result.removed == ()


def test_several_parts_add_up_and_the_first_is_the_pdf() -> None:
    result = DocumentResult(5, (), (_part("A", 2), _part("B", 3)), removed=(4,))
    assert (result.pdf.name, result.pages_in_pdf, result.removed) == ("A_0001.pdf", 5, (4,))
    assert result.ok


def test_the_worst_ocr_outcome_is_the_documents_and_any_failure_is_not_ok() -> None:
    parts = (_part("A", 1), _part("B", 1, OcrStatus.TIMED_OUT, "slow"), _part("C", 1))
    result = DocumentResult(3, (), parts)
    assert (result.ocr.status, result.ocr.detail, result.ok) == (OcrStatus.TIMED_OUT, "slow", False)
    failed = DocumentResult(2, (), (_part("A", 1, OcrStatus.FAILED, "x"), _part("B", 1)))
    assert (failed.ocr.status, failed.ok) == (OcrStatus.FAILED, False)


def test_unavailable_or_skipped_outranks_done_but_not_failures() -> None:
    mixed = DocumentResult(2, (), (_part("A", 1), _part("B", 1, OcrStatus.UNAVAILABLE)))
    assert (mixed.ocr.status, mixed.ok) == (OcrStatus.UNAVAILABLE, True)
    skipped = DocumentResult(1, (), (_part("A", 1, OcrStatus.SKIPPED),))
    assert skipped.ocr.status is OcrStatus.SKIPPED
