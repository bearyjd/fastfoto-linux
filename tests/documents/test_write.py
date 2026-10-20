"""``write_document``: a draft in, one published PDF out. A draft made by hand (no analysis)
writes the golden PDFs, from the bytes it carries or by reading the raw pages again."""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentError,
    DocumentSettings,
    OcrMode,
    OutputFolderMissingError,
    build_document,
)
from fastfoto_linux.documents import write as write_module
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.write import write_document
from tests import _fake_ocrmypdf as fake
from tests.doc_synth import paper_scene, write_png
from tests.doc_synth_holes import SMALL_MM
from tests.documents.draft_helpers import LiveCounter, hand_draft
from tests.documents.golden_cases import build_cases, describe_result
from tests.documents.helpers import (
    FIXED_TIME,
    blank_scene,
    expected_points,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)
from tests.documents.test_analyse import _png_files

GOLDEN: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).parent / "golden_build.json").read_text(encoding="utf-8")
)
CASES = build_cases()
# The pages each golden case judges blank (the draft says so; the analysis is not run here).
BLANK_PAGES = {
    "simplex": {2, 4},
    "duplex blank backs": {2, 4},
    "duplex creased backs": {2, 4},
    "duplex staple-hole backs": {2, 4},
    "duplex faint marks": {4},
    "odd last page": {2},
    "keep blank": {2, 4},
    "grey": {2},
    "black and white": {2},
    "png kinds": {4},
    "png kinds in black and white": {4},
}
MEMORY_DPI = 300
MEMORY_PAGES = 12


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


def _four(raw: Path) -> list[Path]:
    return write_pages(raw, [text_scene(1), blank_scene(2), text_scene(3), blank_scene(4)])


# ---- a draft made by hand writes the golden PDF --------------------------------------------


def test_every_golden_case_but_the_ocr_one_is_covered() -> None:
    assert sorted(BLANK_PAGES) == sorted(name for name in CASES if not CASES[name].fake_ocr)


@pytest.mark.parametrize("with_bytes", [True, False], ids=["from the bytes", "from the raw pages"])
@pytest.mark.parametrize("name", sorted(BLANK_PAGES))
def test_a_hand_built_draft_writes_the_golden_pdf(
    name: str, with_bytes: bool, tmp_path: Path, out: Path
) -> None:
    case = CASES[name]
    used = settings(out, **case.settings)
    pages = case.pages(tmp_path / "raw")
    draft = hand_draft(pages, used, blank=BLANK_PAGES[name], with_bytes=with_bytes)
    result = write_document(draft, used, clock=lambda: FIXED_TIME)
    assert describe_result(result) == GOLDEN[name]


def test_analysing_then_writing_is_building(raw: Path, out: Path) -> None:
    pages = _four(raw)
    used = settings(out)
    result = write_document(analyse_document(pages, used), used, clock=lambda: FIXED_TIME)
    assert describe_result(result) == GOLDEN["duplex blank backs"]
    again = build_document(pages, used, clock=lambda: FIXED_TIME)
    assert describe_result(again) == describe_result(result)


def test_a_fake_ocrmypdf_makes_the_golden_searchable_pdf(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="mark")
    used = settings(out, ocr=OcrMode.AUTO)
    pages = CASES["fake ocrmypdf"].pages(tmp_path / "raw")
    ocr_calls: list[None] = []
    result = write_document(
        hand_draft(pages, used, blank={2}),
        used,
        clock=lambda: FIXED_TIME,
        on_ocr=lambda: ocr_calls.append(None),
    )
    assert describe_result(result) == GOLDEN["fake ocrmypdf"]
    assert len(ocr_calls) == 1


# ---- nothing to write, nothing to read ---------------------------------------------------------


def test_when_every_page_is_blank_nothing_is_written(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [blank_scene(1), blank_scene(2)])
    draft = hand_draft(pages, settings(out), blank={1, 2})
    with pytest.raises(AllPagesBlankError, match="all 2 pages look blank, so no PDF was written"):
        write_document(draft, settings(out))
    assert list(out.iterdir()) == []


def test_a_draft_without_bytes_or_a_raw_folder_cannot_be_written(raw: Path, out: Path) -> None:
    draft = hand_draft(_four(raw), settings(out), blank={2, 4}, with_bytes=False)
    with pytest.raises(DocumentError, match="raw pages"):
        write_document(replace(draft, raw_dir=None), settings(out))
    assert list(out.iterdir()) == []


def test_the_settings_are_checked_again_before_any_page_is_read(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = hand_draft(_four(raw), settings(out), blank={2, 4}, with_bytes=False)
    counter = LiveCounter()
    monkeypatch.setattr(write_module, "load_page", counter)
    with pytest.raises(OutputFolderMissingError):
        write_document(draft, settings(out / "gone"))
    assert counter.loads == 0


# ---- the hooks --------------------------------------------------------------------------------


def test_on_page_is_not_called_for_pages_that_come_with_their_bytes(raw: Path, out: Path) -> None:
    calls: list[tuple[int, int]] = []
    draft = hand_draft(_four(raw), settings(out), blank={2, 4})
    write_document(draft, settings(out), on_page=lambda n, total: calls.append((n, total)))
    assert calls == []


def test_on_page_is_called_before_each_page_that_is_read_again(raw: Path, out: Path) -> None:
    calls: list[tuple[int, int]] = []
    draft = hand_draft(_four(raw), settings(out), blank={2, 4}, with_bytes=False)
    write_document(draft, settings(out), on_page=lambda n, total: calls.append((n, total)))
    assert calls == [(1, 4), (3, 4)]


# ---- memory: one decoded page while writing -----------------------------------------------------


def test_writing_from_the_raw_pages_holds_one_decoded_page(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenes = [
        text_scene(n, dpi=MEMORY_DPI, paper_mm=SMALL_MM)
        if n % 3
        else paper_scene(dpi=MEMORY_DPI, paper_mm=SMALL_MM, seed=n)
        for n in range(MEMORY_PAGES)
    ]
    pages = _png_files(raw, scenes)
    draft = hand_draft(pages, settings(out), blank={3, 6, 9, 12}, with_bytes=False)
    counter = LiveCounter()
    monkeypatch.setattr(write_module, "load_page", counter)
    result = write_document(draft, settings(out))
    assert result.pages_in_pdf == MEMORY_PAGES - 4
    assert counter.loads == MEMORY_PAGES - 4
    assert counter.peak == 1


# ---- a cancel publishes nothing ---------------------------------------------------------------


@pytest.mark.parametrize("stop_after", [1, 2, 3])
def test_a_cancel_while_pages_are_read_again_stops_before_the_next_page(
    stop_after: int, raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    pages = write_pages(raw, [text_scene(n) for n in range(1, 5)])
    draft = hand_draft(pages, settings(out), with_bytes=False)
    counter = LiveCounter(lambda loads: cancel.set() if loads == stop_after else None)
    monkeypatch.setattr(write_module, "load_page", counter)
    with pytest.raises(DocumentCancelledError):
        write_document(draft, settings(out), cancel=cancel)
    assert counter.loads == stop_after
    assert list(out.iterdir()) == []


def test_a_cancel_that_is_already_set_reads_and_writes_nothing(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    cancel.set()
    draft = hand_draft(_four(raw), settings(out), blank={2, 4}, with_bytes=False)
    counter = LiveCounter()
    monkeypatch.setattr(write_module, "load_page", counter)
    with pytest.raises(DocumentCancelledError):
        write_document(draft, settings(out), cancel=cancel)
    assert counter.loads == 0
    assert list(out.iterdir()) == []


def test_a_cancel_set_while_the_pdf_is_assembled_publishes_nothing(raw: Path, out: Path) -> None:
    cancel = threading.Event()

    def clock() -> Any:
        cancel.set()  # the PDF is being assembled: the last thing before the OCR and the publish
        return FIXED_TIME

    draft = hand_draft(_four(raw), settings(out), blank={2, 4})
    with pytest.raises(DocumentCancelledError, match="published"):
        write_document(draft, settings(out), cancel=cancel, clock=clock)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("with_bytes", [True, False], ids=["from the bytes", "from the raw pages"])
def test_a_png_without_dpi_is_written_at_the_dpi_the_analysis_used(
    raw: Path, out: Path, with_bytes: bool
) -> None:
    # The analysis fixes page.dpi from the fallback of that moment; the write must not look at
    # settings.fallback_dpi again, or the same draft would come out at another physical size.
    raw.mkdir()
    scene = text_scene(1)
    path = write_png(raw / "page-01.png", scene.image, dpi=None)
    analysed = settings(out, fallback_dpi=300, keep_blank=True)
    draft = analyse_document([path], analysed)
    assert draft.pages[0].dpi == 300
    if not with_bytes:
        draft = replace(draft, pages=(replace(draft.pages[0], encoded=None),))
    later = settings(out, fallback_dpi=150, keep_blank=True)
    result = write_document(draft, later, clock=lambda: FIXED_TIME)
    pdf = reader(result.pdf.read_bytes())
    height, width = scene.image.shape[:2]
    assert page_size_pt(pdf, 0) == pytest.approx(
        (expected_points(width, 300), expected_points(height, 300)), abs=0.5
    )
