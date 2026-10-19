"""Conservative per-page output choices, separate from source pixel kinds."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import cv2
import numpy as np

from fastfoto_linux.documents.bilevel import DARK_LEVEL
from fastfoto_linux.documents.errors import DocumentError
from fastfoto_linux.documents.loader import LoadedPage, inspect_page, load_page
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy, output_mode
from fastfoto_linux.documents.units import mm_to_px

if TYPE_CHECKING:
    from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis


CHROMA_NOISE = 5  # channel differences at or below this may be neutral scanner noise
STRONG_CHROMA = 12
COLOUR_MARK_MM = 0.25  # sufficient physical support for the stronger explanation
INK_MAX = 24  # only near-black and near-white pixels establish confident bilevel content
PAPER_MIN = 240
PAPER_FLOOR = 224  # only a light paper estimate can relax the near-white noise band
PAPER_QUANTILE = 0.9
PAPER_NOISE = 8
EDGE_RADIUS_MM = 0.20  # antialias tones must touch a dark stroke within this physical bound
WIDE_DARK_RADIUS_MM = 0.50  # nonblack fills wider than ordinary strokes retain their tones
FAINT_MIN = 160
CONTINUOUS_LEVELS = 16


class ColourReason(StrEnum):
    """Stable explanation codes, translated only by presentation code."""

    SOURCE_BW = "source_bw"
    COLOUR_MARKS = "colour_marks"
    COLOUR_UNCERTAIN = "colour_uncertain"
    CONTINUOUS_TONE = "continuous_tone"
    FAINT_MARKS = "faint_marks"
    THRESHOLD_RISK = "threshold_risk"
    BILEVEL = "bilevel"


@dataclass(frozen=True)
class ColourDecision:
    """The retained source representation and its content-based output choice."""

    source_kind: ColourMode
    mode: ColourMode
    reason: ColourReason

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, ColourMode) or not isinstance(self.mode, ColourMode):
            raise ValueError("colour decisions need actual source and output modes")
        if output_mode(self.source_kind, self.mode) is not self.mode:
            raise ValueError("a colour decision cannot be richer than its source")
        if not isinstance(self.reason, ColourReason):
            raise ValueError("a colour decision needs a known reason")


def _colour_reason(pixels: np.ndarray, dpi: int) -> ColourReason | None:
    """Inspect every source pixel; even an isolated ambiguous chromatic pixel retains colour."""
    red, green, blue = cv2.split(pixels)  # independent channel copies; source stays read-only
    spread = cv2.max(red, green)
    cv2.min(red, green, dst=red)
    cv2.max(spread, blue, dst=spread)
    cv2.min(red, blue, dst=red)
    cv2.subtract(spread, red, dst=spread)
    histogram = cv2.calcHist([spread], [0], None, [256], [0, 256]).ravel()
    if not histogram[CHROMA_NOISE + 1 :].any():
        return None
    strong = histogram[STRONG_CHROMA:].sum()
    if strong >= mm_to_px(COLOUR_MARK_MM, dpi) ** 2:
        return ColourReason.COLOUR_MARKS
    return ColourReason.COLOUR_UNCERTAIN


def _tone_label(grey: np.ndarray, mask: np.ndarray) -> ColourReason:
    histogram = cv2.calcHist([grey], [0], mask, [256], [0, 256]).ravel()
    tones = np.flatnonzero(histogram)
    if len(tones) > CONTINUOUS_LEVELS:
        return ColourReason.CONTINUOUS_TONE
    return ColourReason.FAINT_MARKS if tones[0] >= FAINT_MIN else ColourReason.THRESHOLD_RISK


def _physical_kernel(radius_mm: float, dpi: int) -> np.ndarray:
    side = 2 * mm_to_px(radius_mm, dpi) + 1
    return cv2.getStructuringElement(cv2.MORPH_RECT, (side, side))


def _tone_reason(grey: np.ndarray, dpi: int) -> ColourReason:
    """Admit bounded text-edge tones, retaining disconnected and shaded content.

    The current binarizer preserves every dark core through its absolute floor. Intermediate
    tones are only harmless when they hug those cores within EDGE_RADIUS_MM. Broad nonblack
    dark fills, and intermediate marks away from cores, cannot be justified as text edges.
    All masks retain source resolution; morphology uses physical bounds and linear page memory.
    """
    histogram = cv2.calcHist([grey], [0], None, [256], [0, 256]).ravel()
    paper = int(np.searchsorted(np.cumsum(histogram), grey.size * PAPER_QUANTILE))
    paper_limit = min(PAPER_MIN, max(PAPER_FLOOR, paper - PAPER_NOISE))
    relevant = cv2.inRange(grey, INK_MAX + 1, paper_limit - 1)
    if not cv2.countNonZero(relevant):
        return ColourReason.BILEVEL
    cores = cv2.inRange(grey, 0, DARK_LEVEL - 1)
    wide = cv2.erode(cores, _physical_kernel(WIDE_DARK_RADIUS_MM, dpi))
    cv2.bitwise_and(relevant, wide, dst=wide)
    if cv2.countNonZero(wide):
        return _tone_label(grey, relevant)
    del wide
    cv2.dilate(cores, _physical_kernel(EDGE_RADIUS_MM, dpi), dst=cores)
    cv2.bitwise_not(cores, dst=cores)
    cv2.bitwise_and(relevant, cores, dst=relevant)
    return _tone_label(grey, relevant) if cv2.countNonZero(relevant) else ColourReason.BILEVEL


def classify_colour(page: LoadedPage) -> ColourDecision:
    """Choose a conservative mode, with linear work and no arrays retained by the decision."""
    if page.kind is ColourMode.BW:
        return ColourDecision(page.kind, ColourMode.BW, ColourReason.SOURCE_BW)
    grey = page.pixels
    if page.kind is ColourMode.COLOUR:
        reason = _colour_reason(page.pixels, page.dpi)
        if reason is not None:
            return ColourDecision(page.kind, ColourMode.COLOUR, reason)
        grey = cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)
    reason = _tone_reason(grey, page.dpi)
    mode = ColourMode.BW if reason is ColourReason.BILEVEL else ColourMode.GREY
    return ColourDecision(page.kind, mode, reason)


def resolve_colour(decision: ColourDecision, requested: ColourPolicy | ColourMode) -> ColourMode:
    """Resolve Auto or an existing manual request without enriching the source."""
    policy = ColourPolicy(requested)
    return (
        decision.mode
        if policy is ColourPolicy.AUTO
        else output_mode(decision.source_kind, ColourMode(policy.value))
    )


def page_policy(
    draft: "DocumentDraft", page: "PageAnalysis", document_policy: ColourPolicy | ColourMode
) -> ColourPolicy:
    """The raw-number override, if one was set, otherwise the document policy."""
    edit = draft.edits.get(page.number)
    return ColourPolicy(
        edit.colour if edit is not None and edit.colour is not None else document_policy
    )


def page_colour(
    draft: "DocumentDraft", page: "PageAnalysis", document_policy: ColourPolicy | ColourMode
) -> ColourMode:
    """Resolve an override from stored analysis, or safely inspect a retained legacy source."""
    policy = page_policy(draft, page, document_policy)
    if page.colour is not None:
        return resolve_colour(page.colour, policy)
    if draft.raw_dir is not None and policy is not ColourPolicy.AUTO:
        source = inspect_page(draft.raw_dir / page.name, fallback_dpi=page.dpi)
        return output_mode(source.kind, ColourMode(policy.value))
    if draft.raw_dir is not None:
        loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
        return resolve_colour(classify_colour(loaded), policy)
    if policy is not ColourPolicy.AUTO and page.encoded is not None:
        mode = output_mode(page.encoded.mode, ColourMode(policy.value))
        edit = draft.edits.get(page.number)
        if edit is not None and edit.colour is not None and mode.value != policy.value:
            raise DocumentError(
                f"page {page.number} needs retained raw pages to verify source colour"
            )
        return mode
    raise DocumentError(
        f"page {page.number} needs retained raw pages to choose {policy.value} output"
    )
