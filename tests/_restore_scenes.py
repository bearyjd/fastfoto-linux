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
TEXT_FRACTION = 0.08  # dense enough that no row of the page is mistaken for frame
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

WARM_SCENES = {  # kind: (per-channel tone multipliers, share of dark neutral blobs)
    "sand": ((1.0, 0.82, 0.64), 0.08),  # dark rocks
    "sunset": ((1.0, 0.58, 0.40), 0.40),  # black silhouettes
    "skin": ((1.0, 0.88, 0.78), 0.30),  # dark hair
    "lawn": ((0.55, 1.0, 0.25), 0.10),  # deep shadows
}
WARM_FLOOR, WARM_RANGE = 40.0, 200.0
WARM_JITTER = 0.10  # smooth +-10% variation per channel
WARM_BLOB_SIGMA = 30
WARM_DARK_BASE, WARM_DARK_SPAN = 25.0, 30.0
COLOURED_MIN_CHROMA = 10.0  # pixels with less chroma than this have no hue worth comparing


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


def make_warm_scene(kind: str) -> np.ndarray:
    """A scene that is mostly one hue and has no cast, with dark neutral parts but no white.

    Dark rocks on sand, a sunset with silhouettes, skin next to dark hair, a lawn with shadows:
    the shadows are neutral, the lights are tinted by the scene itself, as in real prints.
    """
    tone, dark_share = WARM_SCENES[kind]
    rng = np.random.default_rng(SEED + 10)
    shape = (HEIGHT, WIDTH)
    luminance = grey_of(make_natural()) / FULL_SCALE
    jitter = np.stack(
        [1 + WARM_JITTER * _smooth_field(rng, shape, WARM_BLOB_SIGMA) for _ in range(3)], axis=-1
    )
    img = (WARM_FLOOR + luminance * WARM_RANGE)[..., None] * np.array(tone, np.float32) * jitter
    blobs = _smooth_field(rng, shape, WARM_BLOB_SIGMA)
    dark = blobs < np.percentile(blobs, 100.0 * dark_share)
    img[dark] = WARM_DARK_BASE + luminance[dark][:, None] * WARM_DARK_SPAN
    return np.clip(np.rint(img), 0, FULL_SCALE).astype(np.uint8)


def colour_change(before: np.ndarray, after: np.ndarray) -> tuple[float, float]:
    """Median hue shift (degrees) and median chroma ratio over the coloured pixels of ``before``."""
    lab_before, lab_after = lab(before), lab(after)
    chroma_before = np.hypot(lab_before[..., 1], lab_before[..., 2])
    chroma_after = np.hypot(lab_after[..., 1], lab_after[..., 2])
    coloured = chroma_before > COLOURED_MIN_CHROMA
    turn = np.arctan2(lab_after[..., 2], lab_after[..., 1]) - np.arctan2(
        lab_before[..., 2], lab_before[..., 1]
    )
    shift = np.abs(np.angle(np.exp(1j * turn)))[coloured]
    return float(np.degrees(np.median(shift))), float(
        np.median(chroma_after[coloured] / chroma_before[coloured])
    )
