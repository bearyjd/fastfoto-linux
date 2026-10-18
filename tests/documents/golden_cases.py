"""Page sets that pin what the document pipeline does: the pages dropped and the PDF bytes of
``build_document``, and the verdict of ``is_blank_beside`` on the synthetic fixtures.

The expected values are in ``golden_build.json`` and ``golden_verdicts.json``. They were taken
from the code as it was before ``build`` was split into analyse and write, and nothing here
reaches into ``fastfoto_linux.documents.build``'s internals: only the public entry points are
called, so a refactor cannot bend the oracle. Change a golden file only for a change that is
meant to alter verdicts or bytes.
"""

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pikepdf
import pytest

from fastfoto_linux.documents import (
    ColourMode,
    DocumentResult,
    DocumentSettings,
    OcrMode,
    build_document,
)
from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.trim import trim_page
from tests import _fake_ocrmypdf as fake
from tests.doc_synth import (
    Scene,
    paper_scene,
    to_bilevel,
    to_grey,
    with_show_through,
    with_signature,
    with_solid_block,
    with_specks,
    with_text,
    with_tinted_block,
    write_png,
)
from tests.doc_synth_band import banded_scene, scanner_page, with_glyphs
from tests.doc_synth_creases import (
    with_creases,
    with_dust_clear_of_creases,
    with_line,
    with_pencil_words,
    with_slanted_artefact,
)
from tests.doc_synth_faint import (
    softened,
    with_bowed_line,
    with_cursive_word,
    with_dust_on_creases,
    with_roman_two,
    with_seven,
    with_stem,
    with_wave,
    with_zigzag,
)
from tests.doc_synth_holes import (
    PUNCHES,
    SMALL_MM,
    STAPLES,
    disc,
    holes_painter,
    ring,
    sheet,
    slanted,
    with_number,
)
from tests.doc_synth_text import pale_text_page, paragraph, with_serif_text
from tests.documents.helpers import (
    FIXED_TIME,
    blank_scene,
    bw_page,
    colour_page,
    grey_page,
    image_object,
    reader,
    text_scene,
    write_pages,
)
from tests.documents.holes_helpers import ALIGNMENTS, mirrored, stapled_sheet, text

VERDICT_DPI = 200
HASH_CHARS = 16
PAGE_KINDS = {"colour": colour_page, "grey": grey_page, "bw": bw_page}
KINDS_BEYOND_COLOUR = ("grey", "bw")
KINDED_FAMILIES = ("blank", "text", "creases", "staples", "pencil", "faint bar", "dark bar")

Pair = tuple[Scene, Scene | None]


def _paper(seed: int = 0) -> Scene:
    return paper_scene(dpi=VERDICT_DPI, paper_mm=SMALL_MM, seed=seed)


def _written(seed: int) -> Scene:
    return with_text(_paper(seed), 12.0, 50.0, 14)


def _creased(seed: int, **kwargs: Any) -> Scene:
    return with_creases(_paper(seed), **kwargs)


def _basic_pairs() -> dict[str, Pair]:
    written, blank = _written(1), _paper(2)
    return {
        "blank alone": (blank, None),
        "text alone": (written, None),
        "blank beside text": (blank, written),
        "specks": (with_specks(_paper(3), 8), None),
        "signature": (with_signature(_paper(4), 20.0, 40.0), None),
        "solid block": (with_solid_block(_paper(5), 30.0, 40.0, 8.0, 90), None),
        "tinted block": (
            with_tinted_block(_paper(6), 20.0, 40.0, (30.0, 6.0), (200, 210, 240)),
            None,
        ),
        "show through": (with_show_through(_paper(7), written), written),
    }


def _crease_pairs() -> dict[str, Pair]:
    return {
        "creases": (_creased(10), None),
        "creases vertical": (_creased(11, vertical=True), None),
        "creases broken": (_creased(12, broken=True), None),
        "creases with dust": (with_dust_clear_of_creases(_creased(13), 6), None),
        "creases and dust on them": (with_dust_on_creases(_creased(14), 4), None),
        "slanted artefact": (with_slanted_artefact(_paper(15)), None),
        "pencil words": (with_pencil_words(_paper(16), 20.0, 40.0), None),
        "pencil words over creases": (with_pencil_words(_creased(17), 20.0, 40.0), None),
        "faint bar": (with_line(_paper(18), (30, 60), (70, 60), tone=160, thickness_mm=0.3), None),
        "dark bar": (with_line(_paper(19), (30, 60), (70, 60), tone=60, thickness_mm=0.5), None),
        "softened creases": (softened(_creased(20)), None),
        "creased beside text": (_creased(21), _written(22)),
    }


def _faint_pairs() -> dict[str, Pair]:
    page = _paper(30)
    return {
        "cursive faint": (with_cursive_word(page, 20.0, 40.0, tone=200), None),
        "cursive darker": (with_cursive_word(page, 20.0, 40.0, tone=120), None),
        "cursive grain": (with_cursive_word(page, 20.0, 40.0, tone=200, grain_tone=150), None),
        "wave": (with_wave(page, 20.0, 40.0, tone=190, length_mm=40.0, amplitude_mm=3.0), None),
        "stem": (with_stem(page, 30.0, 40.0, 48.0, tone=190, stroke_mm=0.3), None),
        "seven": (with_seven(page, 30.0, 40.0, 3.0, tone=190, stroke_mm=0.3), None),
        "roman two": (with_roman_two(page, 30.0, 40.0, tone=190), None),
        "roman two joined": (with_roman_two(page, 30.0, 40.0, tone=190, joined=True), None),
        "zigzag": (
            with_zigzag(
                page, 20.0, 40.0, 30.0, tone=190, swing_mm=2.0, tooth_mm=1.5, stroke_mm=0.4
            ),
            None,
        ),
        "bowed line": (
            with_bowed_line(page, 30.0, 30.0, 40.0, 3.0, tone=190, stroke_mm=0.3),
            None,
        ),
        "serif text": (with_serif_text(page, 15.0, 40.0, 20, tone=190, rows=3), None),
    }


def _band_pairs() -> dict[str, Pair]:
    width = SMALL_MM[0]
    banded = banded_scene(dpi=VERDICT_DPI, width_mm=width, paper_mm=80.0)
    glyphed, _ = with_glyphs(banded, banded.paper_top + 60, 2.6, (120, 120, 150))
    frame = scanner_page(dpi=VERDICT_DPI, width_mm=width, paper_mm=80.0, tilt_deg=1.0)
    return {
        "band": (banded, None),
        "band with glyphs": (glyphed, None),
        "scanner frame": (frame, None),
    }


def _hole_pairs() -> dict[str, Pair]:
    pairs: dict[str, Pair] = {}
    pairs["staples"] = stapled_sheet(40)
    pairs["staples blank front"] = stapled_sheet(41, text_front=False)
    pairs["punches"] = sheet(
        VERDICT_DPI, [text, holes_painter(PUNCHES)], [holes_painter(mirrored(PUNCHES))], seed=42
    )
    pairs["staples on the front only"] = sheet(
        VERDICT_DPI, [text, holes_painter(STAPLES)], [], seed=43
    )
    pairs["staples not mirrored"] = sheet(
        VERDICT_DPI, [text, holes_painter(STAPLES)], [holes_painter(STAPLES)], seed=44
    )
    odd = (disc(50.0, 30.0, 6.0), ring(30.0, 20.0, 6.0, 0.8), slanted(60.0, 40.0, 4.0))
    pairs["odd shapes"] = sheet(
        VERDICT_DPI, [holes_painter(odd)], [holes_painter(mirrored(odd))], seed=45
    )
    pairs["number on the back"] = sheet(
        VERDICT_DPI,
        [text],
        [lambda scene: with_number(scene, "12", centre_x_mm=50.0, y_mm=110.0)],
        seed=46,
    )
    for name, (shift, tilt) in ALIGNMENTS.items():
        pairs[f"staples {name}"] = sheet(
            VERDICT_DPI,
            [text, holes_painter(STAPLES)],
            [holes_painter(mirrored(STAPLES))],
            shift_mm=shift,
            tilt_deg=tilt,
            seed=47,
        )
    return pairs


def scene_pairs() -> dict[str, Pair]:
    """Every synthetic fixture family: (a page, the other side of its sheet or None)."""
    return {
        **_basic_pairs(),
        **_crease_pairs(),
        **_faint_pairs(),
        **_band_pairs(),
        **_hole_pairs(),
    }


def _pale_pages() -> dict[str, LoadedPage]:
    lines = paragraph(10.0)
    return {
        f"pale text {darkest}": pale_text_page(
            VERDICT_DPI, lines, points=10.0, darkest=darkest, blur_mm=0.1
        )
        for darkest in (90, 150, 190)
    }


def _verdict(page: LoadedPage, other: LoadedPage | None) -> tuple[bool, bool | None]:
    first = trim_page(page)
    second = None if other is None else trim_page(other)
    return is_blank_beside(first, second), (
        None if second is None else is_blank_beside(second, first)
    )


def verdict_table() -> dict[str, bool]:
    """``is_blank_beside`` for each fixture, each side beside the other. Grey and 1-bit pages
    are judged for the families where the page kind matters."""
    table: dict[str, bool] = {}
    for label, (front, back) in scene_pairs().items():
        for kind, make in PAGE_KINDS.items():
            if kind in KINDS_BEYOND_COLOUR and not label.startswith(KINDED_FAMILIES):
                continue
            first, second = _verdict(make(front), None if back is None else make(back))
            table[f"{label} | {kind} | front"] = first
            if second is not None:
                table[f"{label} | {kind} | back"] = second
    for label, page in _pale_pages().items():
        table[f"{label} | colour | front"] = _verdict(page, None)[0]
    return table


# ---- whole documents: pages in, pages dropped and PDF bytes out ---------------------------


def _stack(*scenes: Scene) -> Callable[[Path], list[Path]]:
    return lambda folder: write_pages(folder, list(scenes))


def _kinds_of_file(folder: Path) -> list[Path]:
    """RGB, 8-bit grey and 1-bit PNGs, a blank grey one last."""
    folder.mkdir(exist_ok=True)
    written, blank = text_scene(1), blank_scene(2)
    return [
        write_png(folder / "page-01.png", written.image, dpi=written.dpi),
        write_png(folder / "page-02.png", to_grey(written.image), dpi=written.dpi),
        write_png(folder / "page-03.png", to_bilevel(written.image), dpi=written.dpi, mode="1"),
        write_png(folder / "page-04.png", to_grey(blank.image), dpi=blank.dpi),
    ]


def _stapled_stack(folder: Path) -> list[Path]:
    first, second = stapled_sheet(50), stapled_sheet(51)
    return write_pages(folder, [first[0], first[1], second[0], second[1]])


@dataclass(frozen=True)
class BuildCase:
    pages: Callable[[Path], list[Path]]
    settings: dict[str, Any] = field(default_factory=dict)
    fake_ocr: bool = False


def _creases(seed: int) -> Scene:
    return with_creases(blank_scene(seed))


def build_cases() -> dict[str, BuildCase]:
    four = (text_scene(1), blank_scene(2), text_scene(3), blank_scene(4))
    creased = (
        text_scene(1),
        _creases(2),
        text_scene(3),
        with_dust_clear_of_creases(with_creases(blank_scene(4), broken=True), 5),
    )
    faint = (
        text_scene(1),
        with_pencil_words(blank_scene(2), 20.0, 40.0),
        text_scene(3),
        with_line(blank_scene(4), (30, 60), (70, 60), tone=160, thickness_mm=0.3),
    )
    return {
        "simplex": BuildCase(_stack(*four), {"duplex": False}),
        "duplex blank backs": BuildCase(_stack(*four)),
        "duplex creased backs": BuildCase(_stack(*creased)),
        "duplex staple-hole backs": BuildCase(_stapled_stack),
        "duplex faint marks": BuildCase(_stack(*faint)),
        "odd last page": BuildCase(_stack(*four[:3])),
        "keep blank": BuildCase(_stack(*four), {"keep_blank": True}),
        "grey": BuildCase(_stack(*four[:3]), {"colour": ColourMode.GREY}),
        "black and white": BuildCase(_stack(*four[:3]), {"colour": ColourMode.BW}),
        "png kinds": BuildCase(_kinds_of_file),
        "png kinds in black and white": BuildCase(_kinds_of_file, {"colour": ColourMode.BW}),
        "fake ocrmypdf": BuildCase(_stack(*four[:3]), {"ocr": OcrMode.AUTO}, fake_ocr=True),
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:HASH_CHARS]


def _unparsed(obj: pikepdf.Object | None) -> str:
    return "" if obj is None else obj.unparse().decode("ascii")


def _describe_page(page: pikepdf.Page) -> dict[str, Any]:
    image = next(iter(page.Resources.XObject.values()))
    return {
        "box": [round(float(side), 3) for side in page.MediaBox],
        "content": _sha(page.Contents.read_bytes()),
        "width": int(image.Width),
        "height": int(image.Height),
        "bits": int(image.BitsPerComponent),
        "space": _unparsed(image.get("/ColorSpace")),
        "filter": _unparsed(image.get("/Filter")),
        "parms": _unparsed(image.get("/DecodeParms")),
        "image": _sha(image.read_raw_bytes()),
    }


def _describe_pdf(data: bytes) -> dict[str, Any]:
    """The PDF by what it says, not by its bytes: the bytes of one document differ between
    machines (the compression of its small streams, the time-based ``/ID``), what it says does
    not."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return {
            "info": {str(key): str(value) for key, value in sorted(pdf.docinfo.items())},
            "pages": [_describe_page(page) for page in pdf.pages],
            "after_eof": _sha(data.rsplit(b"%%EOF", 1)[1]),
        }


def run_build_case(case: BuildCase, root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build the case's document with the clock pinned and OCR off (or the fake one on) and
    describe the outcome by hashes: each page's embedded image stream and the whole PDF."""
    if case.fake_ocr:
        fake.put_on_path(root / "bin", monkeypatch)
        fake.configure(monkeypatch, mode="mark")
    out = root / "out"
    out.mkdir()
    pages = case.pages(root / "raw")
    base = DocumentSettings(output_root=out, ocr=OcrMode.OFF)
    result = build_document(pages, replace(base, **case.settings), clock=lambda: FIXED_TIME)
    return describe_result(result)


def describe_result(result: DocumentResult) -> dict[str, Any]:
    """What the golden records of a published document: counts, the dropped pages and the
    hashes of each page's embedded image stream and of the PDF."""
    data = result.pdf.read_bytes()
    pdf = reader(data)
    return {
        "pages_read": result.pages_read,
        "dropped": list(result.dropped),
        "pages_in_pdf": result.pages_in_pdf,
        "ocr": result.ocr.status.name,
        "page_streams": [_sha(image_object(pdf, n)._data) for n in range(len(pdf.pages))],
        "pdf": _describe_pdf(data),
    }
