"""Conservative per-page output choices, separate from source pixel kinds."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy

if TYPE_CHECKING:
    from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis


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


def classify_colour(page: LoadedPage) -> ColourDecision:
    """Choose a conservative output from full-resolution trimmed original pixels."""
    raise NotImplementedError("document Auto classification is not implemented")


def resolve_colour(decision: ColourDecision, requested: ColourPolicy | ColourMode) -> ColourMode:
    """Resolve Auto or an existing manual request without enriching the source."""
    raise NotImplementedError("document colour policy resolution is not implemented")


def page_colour(
    draft: "DocumentDraft", page: "PageAnalysis", document_policy: ColourPolicy | ColourMode
) -> ColourMode:
    """Resolve a raw-number override before the document policy."""
    raise NotImplementedError("document page colour overrides are not implemented")
