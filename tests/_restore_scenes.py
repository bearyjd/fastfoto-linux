"""More synthetic scenes for the colour-restoration tests: pages, tinted prints, dominant hues."""

import numpy as np

from tests._restore_synth import (
    FADE_CEILING,
    FADE_FLOOR,
    FULL_SCALE,
    HEIGHT,
    SEED,
    WIDTH,
    _smooth_field,
    grey_of,
    lab,
    make_faded_sepia,
    make_natural,
)

PAPER_LEVEL = 251  # a near-white print back: neutral paper, light scan noise
PAPER_NOISE = 1
TEXT_FRACTION = 0.03
TEXT_LEVELS = (60, 140)
SEPIA_INK = (40, 60, 170)  # blue ink pen: a different colour on a toned print

DOMINANT_TONES = {  # per-channel multipliers of a luminance ramp: one hue family fills the frame
    "lawn": (0.62, 1.0, 0.32),
    "skin": (1.0, 0.76, 0.62),
    "sea": (0.25, 0.62, 1.0),
}
DOMINANT_FLOOR, DOMINANT_RANGE = 20.0, 215.0
DOMINANT_JITTER = 0.10  # smooth +-10% variation per channel: real scenes are not one exact tone
PAPER_BRIGHT_PERCENTILE = 70.0


def make_near_white_page() -> np.ndarray:
    """A print back: pale, almost neutral paper with a few dark text strokes."""
    rng = np.random.default_rng(SEED + 8)
    paper = PAPER_LEVEL + rng.integers(-PAPER_NOISE, PAPER_NOISE + 1, (HEIGHT, WIDTH, 1))
    img = np.repeat(paper, 3, axis=2).astype(np.int16)
    text = rng.random((HEIGHT, WIDTH)) < TEXT_FRACTION
    img[text] = rng.integers(TEXT_LEVELS[0], TEXT_LEVELS[1], (int(text.sum()), 1))
    return np.clip(img, 0, FULL_SCALE).astype(np.uint8)


def make_tinted_black_and_white(tint: tuple[float, float, float]) -> np.ndarray:
    """A faded black-and-white print on tinted (yellowed, cooled) paper: grey plus a constant."""
    luminance = grey_of(make_natural()) / FULL_SCALE
    grey = FADE_FLOOR + luminance * (FADE_CEILING - FADE_FLOOR)
    tinted = grey[..., None] + np.array(tint, dtype=np.float32)
    return np.clip(np.rint(tinted), 0, FULL_SCALE).astype(np.uint8)


def make_sepia_with_ink(fraction: float) -> np.ndarray:
    """A faded sepia print with a little coloured ink (annotations) over it."""
    img = make_faded_sepia()
    ink = np.random.default_rng(SEED + 9).random(img.shape[:2]) < fraction
    img[ink] = SEPIA_INK
    return img


def make_dominant_hue(kind: str) -> np.ndarray:
    """A natural-textured scene that is mostly one hue (lawn, skin close-up, open sea)."""
    rng = np.random.default_rng(SEED + 7)
    luminance = grey_of(make_natural()) / FULL_SCALE
    base = DOMINANT_FLOOR + luminance * DOMINANT_RANGE
    channels = [
        base * tone * (1 + DOMINANT_JITTER * _smooth_field(rng, (HEIGHT, WIDTH), 30))
        for tone in DOMINANT_TONES[kind]
    ]
    return np.clip(np.rint(np.stack(channels, axis=-1)), 0, FULL_SCALE).astype(np.uint8)


def paper_level(img: np.ndarray) -> float:
    """Median level of the brightest pixels (the paper) over all channels."""
    brightest = lab(img)[..., 0] >= np.percentile(lab(img)[..., 0], PAPER_BRIGHT_PERCENTILE)
    return float(np.median(img[brightest]))


def paper_chroma(img: np.ndarray) -> float:
    """Chroma of the median colour of the brightest pixels (the tint of the paper)."""
    img_lab = lab(img)
    brightest = img_lab[..., 0] >= np.percentile(img_lab[..., 0], PAPER_BRIGHT_PERCENTILE)
    return float(
        np.hypot(np.median(img_lab[..., 1][brightest]), np.median(img_lab[..., 2][brightest]))
    )
