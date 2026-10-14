"""Synthetic prints and image metrics shared by the colour-restoration tests (no private scans)."""

import math

import cv2
import numpy as np

DPI = 150
HEIGHT, WIDTH = 240, 360
RAMP_ROWS = slice(0, 80)
PATCH_ROWS = slice(80, 160)
NEUTRAL_ROWS = slice(160, 240)

COLOUR_PATCH_WIDTH = 60
COLOUR_PATCHES = (  # red, yellow, green, cyan, blue, magenta
    (200, 60, 60),
    (210, 200, 60),
    (60, 170, 70),
    (60, 180, 190),
    (60, 80, 200),
    (190, 60, 180),
)
NEUTRAL_PATCH_WIDTH = 90
NEUTRAL_PATCH_LEVELS = (40, 100, 160, 215)
TEXTURE_SIGMA = 8.0
SEED = 20261013

# A magenta/red cast with compressed range and lifted blacks, per channel (R, G, B).
FADE_LOW = (55.0, 30.0, 45.0)
FADE_HIGH = (215.0, 165.0, 190.0)
FULL_SCALE = 255
LAB_L_RANGE = 100.0

# Natural-looking photo: bell-shaped mid-tones, warm tint, texture, nearly (not quite) full range.
NATURAL_MEAN = 127.0
NATURAL_SPREAD = 38.0  # std of the Gaussian luminance; with the colour fields the span is ~90%
NATURAL_TINT = (2.0, 0.0, -2.0)
NATURAL_COLOUR_SPREAD = 17.0  # per-channel smooth colour variation: moderately colourful scene
NATURAL_TEXTURE_SIGMA = 4.0
NATURAL_TAIL_PCT = 0.5
NATURAL_LOW, NATURAL_HIGH = 8.0, 247.0  # 0.5% / 99.5% levels of every channel

SEPIA_TONE = (1.0, 0.86, 0.66)  # per-channel multipliers of a grey ramp
FADE_FLOOR, FADE_CEILING = 40.0, 200.0  # grey range of a faded monochrome print


def lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img.astype(np.float32) / FULL_SCALE, cv2.COLOR_RGB2LAB)


def mean_abs_change(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


def make_reference() -> np.ndarray:
    """Well-balanced test card: grey ramp, six colour patches, textured neutral patches."""
    rng = np.random.default_rng(SEED)
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    ramp = np.rint(np.linspace(0, FULL_SCALE, WIDTH)).astype(np.uint8)
    img[RAMP_ROWS] = ramp[None, :, None]
    for i, colour in enumerate(COLOUR_PATCHES):
        x0 = i * COLOUR_PATCH_WIDTH
        img[PATCH_ROWS, x0 : x0 + COLOUR_PATCH_WIDTH] = colour
    for i, level in enumerate(NEUTRAL_PATCH_LEVELS):
        x0 = i * NEUTRAL_PATCH_WIDTH
        rows = NEUTRAL_ROWS.stop - NEUTRAL_ROWS.start
        noise = rng.normal(0.0, TEXTURE_SIGMA, (rows, NEUTRAL_PATCH_WIDTH, 1))
        patch = np.clip(np.rint(level + noise), 0, FULL_SCALE).astype(np.uint8)
        img[NEUTRAL_ROWS, x0 : x0 + NEUTRAL_PATCH_WIDTH] = patch
    return img


def fade_with_cast(img: np.ndarray, gammas: tuple[float, ...] = (1.0, 1.0, 1.0)) -> np.ndarray:
    low = np.array(FADE_LOW, dtype=np.float32)
    high = np.array(FADE_HIGH, dtype=np.float32)
    tone = (img.astype(np.float32) / FULL_SCALE) ** np.array(gammas, dtype=np.float32)
    return np.rint(low + tone * (high - low)).astype(np.uint8)


def _smooth_field(rng: np.random.Generator, shape: tuple[int, int], sigma: float) -> np.ndarray:
    field = cv2.GaussianBlur(rng.normal(size=shape).astype(np.float32), (0, 0), sigma)
    return field / field.std()


def _gaussianise(rng: np.random.Generator, field: np.ndarray) -> np.ndarray:
    """Re-map a field's values to exact standard-normal quantiles, keeping its spatial layout."""
    ranks = np.argsort(np.argsort(field.ravel()))
    return np.sort(rng.normal(size=field.size))[ranks].reshape(field.shape)


def make_natural(
    height: int = HEIGHT,
    width: int = WIDTH,
    texture: float = NATURAL_TEXTURE_SIGMA,
) -> np.ndarray:
    """A balanced, photo-like image: correlated channels, mid-tones, texture, no ramp."""
    rng = np.random.default_rng(SEED + 1)
    shape = (height, width)
    layout = _smooth_field(rng, shape, 40) + 0.6 * _smooth_field(rng, shape, 9)
    luminance = NATURAL_MEAN + NATURAL_SPREAD * _gaussianise(rng, layout)
    channels = np.stack(
        [
            luminance
            + tint
            + NATURAL_COLOUR_SPREAD * _smooth_field(rng, shape, 25)
            + texture * rng.normal(size=shape)
            for tint in NATURAL_TINT
        ],
        axis=-1,
    )
    # A well-balanced print: every channel spans the same (nearly full) range.
    low = np.percentile(channels, NATURAL_TAIL_PCT, axis=(0, 1))
    high = np.percentile(channels, 100.0 - NATURAL_TAIL_PCT, axis=(0, 1))
    scaled = NATURAL_LOW + (channels - low) * (NATURAL_HIGH - NATURAL_LOW) / (high - low)
    return np.clip(np.rint(scaled), 0, FULL_SCALE).astype(np.uint8)


def grey_of(img: np.ndarray) -> np.ndarray:
    return img.astype(np.float32).mean(axis=2)


def faded_monochrome(tone: tuple[float, float, float]) -> np.ndarray:
    """Natural luminance squeezed into the faded range, then multiplied by a per-channel tone."""
    luminance = grey_of(make_natural()) / FULL_SCALE
    faded = FADE_FLOOR + luminance * (FADE_CEILING - FADE_FLOOR)
    return np.clip(
        np.rint(faded[..., None] * np.array(tone, dtype=np.float32)), 0, FULL_SCALE
    ).astype(np.uint8)


def make_faded_sepia() -> np.ndarray:
    return faded_monochrome(SEPIA_TONE)


def make_faded_black_and_white(noise: int = 0) -> np.ndarray:
    img = faded_monochrome((1.0, 1.0, 1.0))
    if noise:
        rng = np.random.default_rng(SEED + 2)
        jitter = rng.integers(-noise, noise + 1, img.shape, dtype=np.int16)
        img = np.clip(img.astype(np.int16) + jitter, 0, FULL_SCALE).astype(np.uint8)
    return img


SUNSET_BANDS = ((170, 50, 30), (225, 120, 40), (250, 190, 70))  # red-orange to yellow-orange
SUNSET_SILHOUETTE = (35, 18, 12)
SUNSET_BAND_WIDTH = WIDTH // 3


def make_sunset() -> np.ndarray:
    """Dominant single hue family, no neutral anywhere (sky bands over a dark silhouette)."""
    rng = np.random.default_rng(SEED + 3)
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for i, colour in enumerate(SUNSET_BANDS):
        img[: HEIGHT * 2 // 3, i * SUNSET_BAND_WIDTH : (i + 1) * SUNSET_BAND_WIDTH] = colour
    img[HEIGHT * 2 // 3 :] = SUNSET_SILHOUETTE
    noise = rng.normal(0.0, 3.0, img.shape)
    return np.clip(np.rint(img + noise), 0, FULL_SCALE).astype(np.uint8)


BEACH_BANDS = (  # sky, sea, sand: three hue families, with white foam and dark rocks
    (150, 190, 230),
    (35, 105, 150),
    (225, 200, 160),
)
BEACH_FOAM = (248, 248, 244)
BEACH_ROCKS = (45, 40, 38)


def make_beach() -> np.ndarray:
    rng = np.random.default_rng(SEED + 4)
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    rows = HEIGHT // 4
    for i, colour in enumerate(BEACH_BANDS):
        img[i * rows : (i + 1) * rows] = colour
    img[3 * rows : 3 * rows + rows // 2] = BEACH_FOAM
    img[3 * rows + rows // 2 :] = BEACH_ROCKS
    noise = rng.normal(0.0, 3.0, img.shape)
    return np.clip(np.rint(img + noise), 0, FULL_SCALE).astype(np.uint8)


NIGHT_BACKGROUND = (44, 46, 54)
NIGHT_LIGHTS_FRACTION = 0.02
NIGHT_LIGHT_LEVEL = 170  # street lights and windows: bright, but nothing is white


def make_night_scene() -> np.ndarray:
    """Dark, slightly lifted blacks (p1 above 30), a few bright lights, no real white."""
    rng = np.random.default_rng(SEED + 5)
    shape = (HEIGHT, WIDTH)
    base = (
        np.array(NIGHT_BACKGROUND, dtype=np.float32)
        + 6.0 * _smooth_field(rng, shape, 30)[..., None]
    )
    img = base + 3.0 * rng.normal(size=(*shape, 3))
    lights = rng.random(shape) < NIGHT_LIGHTS_FRACTION
    img[lights] = NIGHT_LIGHT_LEVEL + rng.integers(0, 30, (int(lights.sum()), 1))
    return np.clip(np.rint(img), 0, FULL_SCALE).astype(np.uint8)


def desaturate(img: np.ndarray, keep: float) -> np.ndarray:
    """Blend towards each pixel's grey: chroma scales by ``keep`` (hue and lightness stay)."""
    grey = grey_of(img)[..., None]
    return np.clip(np.rint(grey + keep * (img.astype(np.float32) - grey)), 0, FULL_SCALE).astype(
        np.uint8
    )


def uniform_with_chroma(
    chroma: float, hue_deg: float = 60.0, lightness: float = 60.0
) -> np.ndarray:
    """A flat 60x80 image whose LAB chroma is exactly ``chroma`` (to within rounding)."""
    a = chroma * math.cos(math.radians(hue_deg))
    b = chroma * math.sin(math.radians(hue_deg))
    pixel = np.array([[[lightness, a, b]]], dtype=np.float32)
    rgb = np.clip(np.rint(cv2.cvtColor(pixel, cv2.COLOR_LAB2RGB) * FULL_SCALE), 0, FULL_SCALE)
    return np.broadcast_to(rgb.astype(np.uint8), (60, 80, 3)).copy()


def patch_mean_ab(img: np.ndarray, rows: slice, x0: int, width: int) -> tuple[float, float]:
    margin = width // 4
    region = lab(img)[rows, x0 + margin : x0 + width - margin]
    return float(region[..., 1].mean()), float(region[..., 2].mean())


def hue_of(a: float, b: float) -> float:
    return math.degrees(math.atan2(b, a)) % 360.0


def colour_hues(img: np.ndarray) -> list[float]:
    return [
        hue_of(*patch_mean_ab(img, PATCH_ROWS, i * COLOUR_PATCH_WIDTH, COLOUR_PATCH_WIDTH))
        for i in range(len(COLOUR_PATCHES))
    ]


def cyclic_order(hues: list[float]) -> tuple[int, ...]:
    """Patch indices sorted by hue angle, rotated to start at patch 0 (hue wraps at 360)."""
    order = sorted(range(len(hues)), key=hues.__getitem__)
    start = order.index(0)
    return tuple(order[start:] + order[:start])


def hue_error(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def l_contrast(img: np.ndarray) -> float:
    lightness = lab(img)[..., 0]
    return float(np.percentile(lightness, 99) - np.percentile(lightness, 1))


def local_contrast(img: np.ndarray) -> float:
    lightness = lab(img)[..., 0]
    return float(np.std(lightness - cv2.blur(lightness, (9, 9))))


def mean_chroma(img: np.ndarray) -> float:
    img_lab = lab(img)
    return float(np.mean(np.hypot(img_lab[..., 1], img_lab[..., 2])))


def mean_hue(img: np.ndarray) -> float:
    img_lab = lab(img)
    return hue_of(float(img_lab[..., 1].mean()), float(img_lab[..., 2].mean()))


def clipped_fractions(img: np.ndarray) -> tuple[float, float]:
    """Worst per-channel fraction of values at 0 and at 255."""
    return (
        float(max((img[..., c] == 0).mean() for c in range(img.shape[2]))),
        float(max((img[..., c] == FULL_SCALE).mean() for c in range(img.shape[2]))),
    )
