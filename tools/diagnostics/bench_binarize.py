"""Compare binarisation methods on synthetic pages with a known ink mask.

Run: ``uv run python tools/diagnostics/bench_binarize.py [--dpi 300] [--seeds 3]``.

Methods: ``current`` (``documents.bilevel.binarise``), ``adaptive_mean`` (the bare OpenCV
adaptive-mean rule it starts from), ``otsu`` (one global threshold) and ``sauvola`` (local mean
and spread over the same window, k = 0.34). Scores are foreground precision, recall and F1 against
the drawn ink, not pixel agreement alone, because agreement on a mostly-white page rewards
deleting thin strokes. Every page is synthetic: a result here says nothing about OCR quality or
real scans. Not used by the app or CI.
"""

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.bilevel import BELOW_LOCAL_MEAN, WINDOW_MM, binarise
from fastfoto_linux.documents.units import mm_to_px

LETTER_MM = (215.9, 279.4)
MM_PER_INCH = 25.4
PAPER = 235.0
WHITE = 255
SKIP_GLYPH = 0.15  # share of glyph slots left empty (word gaps)
SAUVOLA_K = 0.34
SAUVOLA_R = 128.0
STRONG_UNEVEN = 0.6  # paper at 40% of its tone at the dark edge
STROKE_MM = 0.35
GLYPH_MM = 2.4
LINE_PITCH_MM = 5.0
MARGIN_MM = 20.0
TIMING_REPEATS = 2

Method = Callable[[np.ndarray, int], np.ndarray]  # grey page, dpi -> True where white


@dataclass(frozen=True)
class Page:
    grey: np.ndarray
    ink: np.ndarray  # True where a stroke was drawn


def _px(mm: float, dpi: int) -> int:
    return round(mm / MM_PER_INCH * dpi)


def draw_ink(dpi: int, seed: int) -> np.ndarray:
    """A boolean mask of text-like marks: small strokes in rows, like lines of letters."""
    rng = np.random.default_rng(seed)
    width, height = (_px(mm, dpi) for mm in LETTER_MM)
    ink = np.zeros((height, width), np.uint8)
    thick = max(2, _px(STROKE_MM, dpi))
    glyph, pitch = _px(GLYPH_MM, dpi), _px(LINE_PITCH_MM, dpi)
    margin = _px(MARGIN_MM, dpi)
    for y in range(margin, height - margin, pitch):
        for x in range(margin, width - margin - glyph, glyph + glyph // 2):
            if rng.random() < SKIP_GLYPH:
                continue
            a, b = rng.integers(0, glyph, 2)
            cv2.line(ink, (x, y), (x + int(a), y + glyph), 1, thick)
            cv2.line(ink, (x + glyph, y), (x + int(b), y + glyph), 1, thick)
            cv2.line(ink, (x, y + glyph // 2), (x + glyph, y + glyph // 2), 1, thick)
    return ink.astype(bool)


def _gradient(shape: tuple[int, int], strength: float) -> np.ndarray:
    ramp = np.linspace(1.0 - strength, 1.0, shape[1], dtype=np.float32)
    return np.broadcast_to(ramp, shape)


def _shadow_band(shape: tuple[int, int], dpi: int) -> np.ndarray:
    field = np.ones(shape, np.float32)
    x0, x1 = shape[1] // 3, shape[1] // 3 + _px(25, dpi)
    field[:, x0:x1] = 0.55
    return cv2.GaussianBlur(field, (0, 0), _px(6, dpi))


def _stains(shape: tuple[int, int], rng: np.random.Generator, dpi: int) -> np.ndarray:
    field = np.ones(shape, np.float32)
    for _ in range(6):
        centre = (int(rng.integers(0, shape[1])), int(rng.integers(0, shape[0])))
        cv2.circle(field, centre, _px(float(rng.uniform(6, 14)), dpi), 0.72, -1)
    return cv2.GaussianBlur(field, (0, 0), _px(2, dpi))


def render(ink: np.ndarray, kind: str, dpi: int, seed: int) -> Page:
    """Paper tone with ink and one degradation, as an ``HxW`` uint8 grey page."""
    rng = np.random.default_rng(seed + 1)
    ink_tone = 150.0 if kind == "low_contrast" else 30.0
    tone = np.where(ink, ink_tone, PAPER).astype(np.float32)
    tone = cv2.GaussianBlur(tone, (0, 0), 0.6)
    if kind == "uneven":
        tone *= _gradient(tone.shape, 0.45)
    elif kind == "strong_uneven":
        tone *= _gradient(tone.shape, STRONG_UNEVEN)
    elif kind == "shadow":
        tone *= _shadow_band(tone.shape, dpi)
    elif kind == "stains":
        tone *= _stains(tone.shape, rng, dpi)
    elif kind == "noise":
        tone += rng.normal(0.0, 9.0, tone.shape).astype(np.float32)
    elif kind == "uneven_noise":
        tone *= _gradient(tone.shape, 0.35)
        tone += rng.normal(0.0, 7.0, tone.shape).astype(np.float32)
    return Page(np.clip(tone, 0, 255).astype(np.uint8), ink)


KINDS = (
    "clean",
    "uneven",
    "strong_uneven",
    "shadow",
    "low_contrast",
    "noise",
    "stains",
    "uneven_noise",
)


def adaptive_mean(grey: np.ndarray, dpi: int) -> np.ndarray:
    window = max(3, mm_to_px(WINDOW_MM, dpi) | 1)
    white = cv2.adaptiveThreshold(
        grey, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, window, BELOW_LOCAL_MEAN
    )
    return white == WHITE


def otsu(grey: np.ndarray, _dpi: int) -> np.ndarray:
    _, white = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return white == WHITE


def sauvola(grey: np.ndarray, dpi: int) -> np.ndarray:
    """Sauvola: black where grey < mean * (1 + k * (std / R - 1)) over the local window."""
    window = max(3, mm_to_px(WINDOW_MM, dpi) | 1)
    mean, sq_mean = (
        cv2.boxFilter(plane, cv2.CV_32F, (window, window), borderType=cv2.BORDER_REPLICATE)
        for plane in (grey.astype(np.float32), np.square(grey, dtype=np.float32))
    )
    std = np.sqrt(np.maximum(sq_mean - mean * mean, 0.0))
    return grey >= mean * (1.0 + SAUVOLA_K * (std / SAUVOLA_R - 1.0))


METHODS: dict[str, Method] = {
    "current": binarise,
    "adaptive_mean": adaptive_mean,
    "otsu": otsu,
    "sauvola": sauvola,
}


def score(white: np.ndarray, ink: np.ndarray) -> tuple[float, float, float, float]:
    """Foreground precision, recall, F1 and pixel agreement of a result against the ink.

    Precision allows one pixel of slack round the ink (the blurred stroke edge is not an error);
    recall and agreement are exact.
    """
    black = ~white
    near_ink = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    precision = np.count_nonzero(black & near_ink) / max(1, np.count_nonzero(black))
    hit = np.count_nonzero(black & ink)
    recall = hit / max(1, np.count_nonzero(ink))
    f1 = 2 * precision * recall / (precision + recall) if hit else 0.0
    return precision, recall, f1, float(np.mean(black == ink))


def quality_table(dpi: int, seeds: int) -> dict[tuple[str, str], tuple[float, ...]]:
    results: dict[tuple[str, str], list[tuple[float, ...]]] = {}
    for seed in range(seeds):
        ink = draw_ink(dpi, seed)
        for kind in KINDS:
            page = render(ink, kind, dpi, seed)
            for name, method in METHODS.items():
                results.setdefault((kind, name), []).append(score(method(page.grey, dpi), ink))
    return {key: tuple(np.mean(rows, axis=0)) for key, rows in results.items()}


def runtime_ms(dpi: int) -> dict[str, float]:
    page = render(draw_ink(dpi, 0), "uneven_noise", dpi, 0)
    out = {}
    for name, method in METHODS.items():
        best = float("inf")
        for _ in range(TIMING_REPEATS):
            start = time.perf_counter()
            method(page.grey, dpi)
            best = min(best, time.perf_counter() - start)
        out[name] = best * 1000.0
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    print(f"OpenCV threads: {cv2.getNumThreads()}")
    names = list(METHODS)
    print(f"quality at {args.dpi} dpi, {args.seeds} seeds (precision/recall/F1/agreement)")
    table = quality_table(args.dpi, args.seeds)
    for kind in KINDS:
        for name in names:
            p, r, f, a = table[(kind, name)]
            print(f"{kind:13s} {name:14s} P={p:.3f} R={r:.3f} F1={f:.3f} agree={a:.4f}")
    for dpi in (300, 600):
        times = runtime_ms(dpi)
        print(
            f"runtime {dpi} dpi (ms, best of {TIMING_REPEATS}): "
            + ", ".join(f"{n}={t:.0f}" for n, t in times.items())
        )


if __name__ == "__main__":
    main()
