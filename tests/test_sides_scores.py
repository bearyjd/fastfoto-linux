"""paper_score and handwriting detection on synthetic fronts and backs."""

import cv2
import numpy as np
import pytest

from fastfoto_linux.pipeline import sides
from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.sides import (
    HANDWRITING_MIN_CANDIDATES,
    HandwritingEvidence,
    handwriting_candidates,
    handwriting_evidence,
    has_handwriting,
    paper_score,
)
from tests.sides_helpers import cropped_back, region
from tests.synth import make_frame

SMALL_BACK_MM = (120, 80)


def _front(dpi: int, **kwargs) -> np.ndarray:
    frame, box = make_frame(dpi=dpi, side="front", **kwargs)
    return region(frame, box)


def _solid(rgb: tuple[int, int, int], size: int = 64) -> np.ndarray:
    return np.full((size, size, 3), rgb, dtype=np.uint8)


# --- paper_score ---------------------------------------------------------------------------


def test_pure_white_scores_one_and_black_scores_zero() -> None:
    assert paper_score(_solid((255, 255, 255))) == pytest.approx(1.0)
    assert paper_score(_solid((0, 0, 0))) == 0.0


def test_bright_but_saturated_colour_is_not_paper() -> None:
    assert paper_score(_solid((250, 255, 150))) == 0.0


def test_grey_just_below_the_paper_level_is_not_paper() -> None:
    assert paper_score(_solid((199, 199, 199))) == 0.0
    assert paper_score(_solid((201, 201, 201))) == pytest.approx(1.0)


def test_cream_and_aged_paper_count_as_paper() -> None:
    assert paper_score(_solid((235, 228, 210))) == pytest.approx(1.0)
    assert paper_score(_solid((225, 215, 190))) == pytest.approx(1.0)


def test_paper_chroma_limit_is_45() -> None:
    assert paper_score(_solid((205, 205, 250))) == pytest.approx(1.0)  # chroma 45
    assert paper_score(_solid((205, 205, 251))) == 0.0  # chroma 46


def test_score_is_the_paper_fraction() -> None:
    img = _solid((255, 255, 255), size=100)
    img[:, :30] = 0
    assert paper_score(img) == pytest.approx(0.7, abs=0.03)


@pytest.mark.parametrize("dpi", [150, 300])
def test_synthetic_back_scores_high_and_front_scores_low(dpi: int) -> None:
    assert paper_score(cropped_back(dpi)) > 0.9
    assert paper_score(cropped_back(dpi, writing=True)) > 0.85
    assert paper_score(_front(dpi)) < 0.05


def test_paper_score_does_not_modify_its_input() -> None:
    img = cropped_back(150, writing=True)
    before = img.copy()
    paper_score(img)
    assert np.array_equal(img, before)


@pytest.mark.parametrize(
    "bad",
    [np.zeros((10, 10), dtype=np.uint8), np.zeros((10, 10, 3), dtype=np.float32)],
)
def test_paper_score_rejects_malformed_images(bad: np.ndarray) -> None:
    with pytest.raises(ValueError, match="RGB"):
        paper_score(bad)


# --- handwriting ---------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_handwritten_back_has_far_more_candidates_than_the_threshold(dpi: int, seed: int) -> None:
    back = cropped_back(dpi, writing=True, rng_seed=seed)
    assert handwriting_candidates(back, dpi) >= HANDWRITING_MIN_CANDIDATES + 5
    assert has_handwriting(back, dpi)


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_imprint_only_back_has_no_candidates(dpi: int, seed: int) -> None:
    back = cropped_back(dpi, imprint=True, rng_seed=seed)
    assert handwriting_candidates(back, dpi) <= 1
    assert not has_handwriting(back, dpi)


def test_blank_back_has_no_writing() -> None:
    back = cropped_back(150, imprint=False)
    assert handwriting_candidates(back, 150) == 0
    assert not has_handwriting(back, 150)


def test_imprint_beside_handwriting_does_not_add_candidates() -> None:
    dpi = 300
    plain = cropped_back(dpi, writing=True, imprint=False, rng_seed=5)
    marked = plain.copy()  # the same writing plus a faint dot-matrix line below it
    dot, pitch = mm_to_px(0.6, dpi), mm_to_px(1.4, dpi)
    row = plain.shape[0] // 2
    for x in range(mm_to_px(15, dpi), mm_to_px(70, dpi), pitch):
        marked[row : row + dot, x : x + dot] = 200
    assert (marked != plain).any()
    assert handwriting_candidates(marked, dpi) == handwriting_candidates(plain, dpi)


def test_the_gate_is_two_candidates() -> None:
    assert HANDWRITING_MIN_CANDIDATES == 2


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_short_dated_note_counts_as_handwriting(dpi: int, seed: int) -> None:
    """Two connected words, 3 to 7 mm tall: all the writing a back may carry."""
    back = cropped_back(dpi, note=True, imprint=False, rng_seed=seed)
    assert handwriting_candidates(back, dpi) == 2
    assert has_handwriting(back, dpi)


def test_a_note_beside_the_faint_imprint_is_still_handwriting() -> None:
    back = cropped_back(150, note=True, imprint=True, rng_seed=3)
    assert has_handwriting(back, 150)


@pytest.mark.parametrize("dpi", [150, 300])
def test_dark_imprint_with_bars_is_a_known_false_positive_without_pen_strokes(dpi: int) -> None:
    """After enhancement the lab imprint is as dark as ink: kept as writing (harmless), but its
    grey is lighter than pen, which the pen-stroke count can tell apart later."""
    back = cropped_back(dpi, dark_imprint=True, imprint=False)
    evidence = handwriting_evidence(back, dpi)
    assert evidence.candidates >= HANDWRITING_MIN_CANDIDATES
    assert has_handwriting(back, dpi)
    assert evidence.pen_strokes == 0


@pytest.mark.parametrize("dpi", [150, 300, 450, 600])
def test_classification_is_stable_across_resolutions(dpi: int) -> None:
    written = cropped_back(dpi, writing=True, imprint=True, photo_mm=SMALL_BACK_MM)
    imprint = cropped_back(dpi, imprint=True, photo_mm=SMALL_BACK_MM)
    note = cropped_back(dpi, note=True, imprint=False, photo_mm=SMALL_BACK_MM)
    assert has_handwriting(written, dpi)
    assert has_handwriting(note, dpi)
    assert not has_handwriting(imprint, dpi)


def test_candidate_counts_agree_between_300_and_600_dpi() -> None:
    low = cropped_back(300, writing=True, photo_mm=SMALL_BACK_MM, rng_seed=2)
    high = cv2.resize(low, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    assert abs(handwriting_candidates(high, 600) - handwriting_candidates(low, 300)) <= 2


def _analysed_width(monkeypatch: pytest.MonkeyPatch, back: np.ndarray, dpi: int) -> int:
    """Width in pixels of the ink mask the blob counter actually receives."""
    seen: list[int] = []
    real = cv2.connectedComponentsWithStats

    def spy(mask: np.ndarray, *args, **kwargs):
        seen.append(mask.shape[1])
        return real(mask, *args, **kwargs)

    monkeypatch.setattr(sides.cv2, "connectedComponentsWithStats", spy)
    handwriting_candidates(back, dpi)
    return seen[0]


def test_sharp_backs_are_analysed_at_about_300_dpi(monkeypatch: pytest.MonkeyPatch) -> None:
    sharp = cropped_back(600, writing=True, photo_mm=SMALL_BACK_MM)
    plain = cropped_back(300, writing=True, photo_mm=SMALL_BACK_MM)
    inset = 2 * mm_to_px(4, 300)
    assert _analysed_width(monkeypatch, sharp, 600) == pytest.approx(
        sharp.shape[1] // 2 - inset, abs=2
    )
    assert _analysed_width(monkeypatch, plain, 300) == plain.shape[1] - inset  # not resampled


def _with_dark(back: np.ndarray, dpi: int, rows: slice, cols: slice) -> np.ndarray:
    out = back.copy()
    out[rows, cols] = 60
    return out


def test_long_dark_bars_are_lines_not_writing() -> None:
    dpi = 150
    back = cropped_back(dpi, imprint=False)
    top = mm_to_px(30, dpi)
    bar = slice(top, top + mm_to_px(2.5, dpi))
    marked = _with_dark(back, dpi, bar, slice(mm_to_px(20, dpi), mm_to_px(110, dpi)))
    assert handwriting_candidates(marked, dpi) == 0


def _with_ring(back: np.ndarray, dpi: int, gap_mm: float) -> np.ndarray:
    """Draw a 2 mm dark frame ``gap_mm`` in from the edge."""
    out = back.copy()
    gap, width = mm_to_px(gap_mm, dpi), mm_to_px(2.0, dpi)
    height, wide = out.shape[:2]
    out[gap : height - gap, gap : wide - gap] = 60
    inner = (slice(gap + width, height - gap - width), slice(gap + width, wide - gap - width))
    out[inner] = back[inner]
    return out


@pytest.mark.parametrize("gap_mm", [1.0, 6.0])
def test_a_dark_border_ring_is_not_writing_inside_or_outside_the_inset(gap_mm: float) -> None:
    back = cropped_back(150, imprint=False)
    assert handwriting_candidates(_with_ring(back, 150, gap_mm), 150) == 0


def test_tiny_or_huge_blobs_are_not_candidates() -> None:
    dpi = 150
    back = cropped_back(dpi, imprint=False)
    speck = _with_dark(back, dpi, slice(100, 103), slice(100, 103))  # a 0.5 mm speck
    block = _with_dark(back, dpi, slice(100, 100 + mm_to_px(40, dpi)), slice(100, 100 + 30))
    assert handwriting_candidates(speck, dpi) == 0
    assert handwriting_candidates(block, dpi) == 0  # 40 mm tall: a stain, not a letter


def test_image_smaller_than_the_inset_has_no_candidates() -> None:
    tiny = np.zeros((20, 20, 3), dtype=np.uint8)
    assert handwriting_candidates(tiny, 150) == 0
    assert not has_handwriting(tiny, 150)


def test_handwriting_does_not_modify_its_input() -> None:
    back = cropped_back(600, writing=True, photo_mm=SMALL_BACK_MM)
    before = back.copy()
    handwriting_candidates(back, 600)
    assert np.array_equal(back, before)


def test_handwriting_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="RGB"):
        handwriting_candidates(np.zeros((50, 50), dtype=np.uint8), 150)
    with pytest.raises(ValueError, match="dpi"):
        handwriting_candidates(cropped_back(150), 0)


# --- evidence (candidates plus pen strokes) -------------------------------------------------


def _stamped(grey_level: int, size_mm: tuple[float, float], dpi: int = 150) -> np.ndarray:
    """A blank back with one solid rectangle of ``grey_level`` (width, height in mm)."""
    back = cropped_back(dpi, imprint=False)
    x, y = mm_to_px(30, dpi), mm_to_px(30, dpi)
    back[y : y + mm_to_px(size_mm[1], dpi), x : x + mm_to_px(size_mm[0], dpi)] = grey_level
    return back


@pytest.mark.parametrize("dpi", [150, 300])
def test_evidence_counts_agree_with_the_candidate_function(dpi: int) -> None:
    for kwargs in ({"writing": True}, {"note": True}, {"imprint": True}, {"dark_imprint": True}):
        back = cropped_back(dpi, **kwargs)
        evidence = handwriting_evidence(back, dpi)
        assert isinstance(evidence, HandwritingEvidence)
        assert evidence.candidates == handwriting_candidates(back, dpi)


@pytest.mark.parametrize("dpi", [150, 300])
def test_a_note_has_pen_strokes_and_blank_or_faint_backs_have_none(dpi: int) -> None:
    note = handwriting_evidence(cropped_back(dpi, note=True, imprint=False), dpi)
    assert note.pen_strokes == 2
    assert handwriting_evidence(cropped_back(dpi, imprint=False), dpi) == HandwritingEvidence(0, 0)
    assert handwriting_evidence(cropped_back(dpi, imprint=True), dpi).pen_strokes == 0


def test_a_solid_dark_blob_is_a_candidate_but_not_a_pen_stroke() -> None:
    evidence = handwriting_evidence(_stamped(60, (4, 4)), 150)  # fill ratio 1.0
    assert evidence == HandwritingEvidence(candidates=1, pen_strokes=0)


def _diagonal_stroke(grey_level: int, dpi: int = 150) -> np.ndarray:
    """A blank back with one thin diagonal stroke, 6 mm tall, of a single grey level."""
    back = cropped_back(dpi, imprint=False)
    x, y = mm_to_px(30, dpi), mm_to_px(30, dpi)
    p0, p1 = (x, y + mm_to_px(6, dpi)), (x + mm_to_px(3, dpi), y)
    cv2.line(back, p0, p1, (grey_level,) * 3, mm_to_px(0.5, dpi), cv2.LINE_8)
    return back


@pytest.mark.parametrize(("grey_level", "pen"), [(100, 1), (110, 1), (120, 0)])
def test_only_ink_as_dark_as_pen_is_a_pen_stroke(grey_level: int, pen: int) -> None:
    evidence = handwriting_evidence(_diagonal_stroke(grey_level), 150)
    assert (evidence.candidates, evidence.pen_strokes) == (1, pen)


def test_evidence_does_not_modify_its_input_and_validates_it() -> None:
    back = cropped_back(600, note=True, photo_mm=SMALL_BACK_MM)
    before = back.copy()
    handwriting_evidence(back, 600)
    assert np.array_equal(back, before)
    with pytest.raises(ValueError, match="RGB"):
        handwriting_evidence(np.zeros((50, 50), dtype=np.uint8), 150)
    with pytest.raises(ValueError, match="dpi"):
        handwriting_evidence(cropped_back(150), 0)
    assert handwriting_evidence(np.zeros((20, 20, 3), dtype=np.uint8), 150) == HandwritingEvidence(
        0, 0
    )
