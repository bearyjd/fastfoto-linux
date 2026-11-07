"""``eval detail``: noise reduction and sharpening on annotated flat patches and edges.

Denoise and sharpen are rendered separately from the original: the flat patch sigma and the 10-90
edge width are read from the denoised image, the halo overshoot from the sharpened one. Per item
the sigma reduction and the edge-width growth are means over its boxes and the halo is the worst
of its edges.
"""

from dataclasses import dataclass
from threading import Event

import numpy as np

from fastfoto_linux.evaluation.calib_annotations import DetailNote, check_inside
from fastfoto_linux.evaluation.calib_metrics import (
    PERCENT,
    edge_width,
    flat_sigmas,
    halo_pct,
    luma,
)
from fastfoto_linux.evaluation.redeye_images import decode_image
from fastfoto_linux.evaluation.redeye_split import pixel_digest
from fastfoto_linux.evaluation.stats import nearest_rank
from fastfoto_linux.photo_edits.detail import apply_denoise, apply_sharpen
from fastfoto_linux.photo_edits.model import PhotoDetail

FEATURE = "detail"
KIND = "photo"
DEFAULT_STRENGTH = 50
MAX_STRENGTH = 100
MIN_SIGMA = 1e-6
MEDIAN, P90 = 50, 90


@dataclass(frozen=True)
class Strengths:
    """The 0 to 100 controls the evaluation runs at (the bench default is 50 each)."""

    denoise_luma: int = DEFAULT_STRENGTH
    denoise_chroma: int = DEFAULT_STRENGTH
    sharpen: int = DEFAULT_STRENGTH

    def __post_init__(self) -> None:
        for value in (self.denoise_luma, self.denoise_chroma, self.sharpen):
            if type(value) is not int or not 0 <= value <= MAX_STRENGTH:
                raise ValueError("a strength is a whole number from 0 to 100")


def digest(data: bytes, note: DetailNote) -> str:
    return pixel_digest(decode_image(data))


def render_denoise(rgb: np.ndarray, strengths: Strengths) -> np.ndarray:
    """A new image with noise reduction applied; the input is never changed."""
    out = rgb.copy()
    detail = PhotoDetail(
        denoise_luma=strengths.denoise_luma, denoise_chroma=strengths.denoise_chroma
    )
    apply_denoise(out, detail, Event())
    return out


def render_sharpen(rgb: np.ndarray, dpi: int, strengths: Strengths) -> np.ndarray:
    """A new image sharpened for ``dpi``; the input is never changed."""
    out = rgb.copy()
    apply_sharpen(out, PhotoDetail(sharpen=strengths.sharpen), float(dpi), Event())
    return out


def _sigma_reduction(before: np.ndarray, after: np.ndarray, note: DetailNote) -> float:
    pairs = zip(
        flat_sigmas(before, note.flat_boxes), flat_sigmas(after, note.flat_boxes), strict=True
    )
    drops = [PERCENT * (b - a) / b for b, a in pairs if b > MIN_SIGMA]
    if not drops:
        raise ValueError("the flat patches have no noise to measure")
    return sum(drops) / len(drops)


def _edge_growth(before: np.ndarray, after: np.ndarray, note: DetailNote) -> float:
    growth = []
    for edge in note.edge_boxes:
        was, now = edge_width(before, edge.box, edge.axis), edge_width(after, edge.box, edge.axis)
        if was is None or now is None or was <= 0:
            raise ValueError("an edge box has no measurable edge")
        growth.append(PERCENT * (now - was) / was)
    return sum(growth) / len(growth)


def _halo(before: np.ndarray, after: np.ndarray, note: DetailNote) -> float:
    halos = [halo_pct(before, after, edge.box, edge.axis) for edge in note.edge_boxes]
    if any(h is None for h in halos):
        raise ValueError("an edge box has no measurable edge")
    return max(h for h in halos if h is not None)


def measure(data: bytes, note: DetailNote, settings: object = None) -> dict[str, object]:
    strengths = settings if isinstance(settings, Strengths) else Strengths()
    rgb = decode_image(data)
    boxes = [*note.flat_boxes, *(edge.box for edge in note.edge_boxes)]
    check_inside(boxes, rgb.shape[1], rgb.shape[0])
    grey = luma(rgb)
    smooth = luma(render_denoise(rgb, strengths))
    sharp = luma(render_sharpen(rgb, note.dpi, strengths))
    return {
        "sigma": _sigma_reduction(grey, smooth, note),
        "growth": _edge_growth(grey, smooth, note),
        "halo": _halo(grey, sharp, note),
    }


def aggregate(rows: list[dict[str, object]], settings: object = None) -> dict[str, object]:
    strengths = settings if isinstance(settings, Strengths) else Strengths()
    column = {key: [float(r[key]) for r in rows] for key in ("sigma", "growth", "halo")}  # type: ignore[arg-type]
    return {
        "n": len(rows),
        "strengths": {
            "denoise_luma": strengths.denoise_luma,
            "denoise_chroma": strengths.denoise_chroma,
            "sharpen": strengths.sharpen,
        },
        "sigma_reduction_pct_median": nearest_rank(column["sigma"], MEDIAN),
        "edge_width_growth_pct_median": nearest_rank(column["growth"], MEDIAN),
        "halo_pct_p90": nearest_rank(column["halo"], P90),
    }
