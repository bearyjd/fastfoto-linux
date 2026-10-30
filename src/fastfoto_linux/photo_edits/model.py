"""Typed contract for recoverable, source-bound photo edits."""

import math
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import numpy as np

from fastfoto_linux.photo_edits.results import PhotoPreview, SavedPhotoEdit  # noqa: F401
from fastfoto_linux.photo_edits.straighten import STRAIGHTEN_LIMIT_TENTHS, straightened_size
from fastfoto_linux.pipeline.geometry import mm_to_px

# SCHEMA_VERSION and ALGORITHM_VERSION are the CURRENT versions: what new drafts are written with.
# The legacy pair below is still readable and is kept for an unchanged older draft.
SCHEMA_VERSION = 2
ALGORITHM_VERSION = "photo-tone-v1"
LEGACY_SCHEMA_VERSION = 1
LEGACY_ALGORITHM_VERSION = "redeye-v1"
TONE_SCHEMA_VERSION = 2
TONE_ALGORITHM_VERSION = "photo-tone-v1"
GEOMETRY_SCHEMA_VERSION = 3
GEOMETRY_ALGORITHM_VERSION = "photo-geometry-v1"
STRAIGHTEN_SCHEMA_VERSION = 4
STRAIGHTEN_ALGORITHM_VERSION = "photo-geometry-v2"
WHITE_BALANCE_SCHEMA_VERSION = 5
WHITE_BALANCE_ALGORITHM_VERSION = "photo-color-v1"
DETAIL_SCHEMA_VERSION = 6
DETAIL_ALGORITHM_VERSION = "photo-detail-v1"
RECIPE_VERSIONS = {
    LEGACY_SCHEMA_VERSION: LEGACY_ALGORITHM_VERSION,
    TONE_SCHEMA_VERSION: TONE_ALGORITHM_VERSION,
    GEOMETRY_SCHEMA_VERSION: GEOMETRY_ALGORITHM_VERSION,
    STRAIGHTEN_SCHEMA_VERSION: STRAIGHTEN_ALGORITHM_VERSION,
    WHITE_BALANCE_SCHEMA_VERSION: WHITE_BALANCE_ALGORITHM_VERSION,
    DETAIL_SCHEMA_VERSION: DETAIL_ALGORITHM_VERSION,
}
MIN_CROP_MM = 5.0
CROP_COORDINATES = 4
TONE_CONTROL_LIMIT = 50
TONE_PERCENT_LIMIT = 100
WB_CONTROL_LIMIT = 100
DETAIL_CONTROL_LIMIT = 100
MAX_RECIPE_BYTES = 2_000_000
MAX_EYES = 128
MAX_MASK_PIXELS = 1_000_000
PREVIEW_MAX_PX = 1600
MAX_SOURCE_BYTES = 256_000_000
MAX_SOURCE_PIXELS = 89_000_000
MAX_METADATA_BYTES = 4_000_000
MAX_ID_CHARS = 128
SHA256_LENGTH = 64
ROI_COORDINATES = 4
POINT_COORDINATES = 2


def integer(value: object, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PhotoEditError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def validate_version(schema: object, algorithm: object) -> None:
    integer(schema, min(RECIPE_VERSIONS), max(RECIPE_VERSIONS), "recipe schema version")
    if not isinstance(algorithm, str) or algorithm != RECIPE_VERSIONS[schema]:
        raise PhotoEditError("unsupported photo correction algorithm version")


def finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoEditError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as error:
        raise PhotoEditError(f"{label} must be a finite number") from error
    if not math.isfinite(result):
        raise PhotoEditError(f"{label} must be a finite number")
    return result


def digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        raise PhotoEditError("invalid SHA-256 hash")
    if any(char not in "0123456789abcdef" for char in value):
        raise PhotoEditError("invalid SHA-256 hash")
    return value


def sibling_name(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise PhotoEditError("source and output names must be sibling basenames")
    if any(char in value for char in ("/", "\\", "\x00")) or Path(value).name != value:
        raise PhotoEditError("source and output names must be sibling basenames")
    return value


def _readonly(array: np.ndarray) -> np.ndarray:
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


class PhotoEditError(ValueError):
    """A source or recipe cannot safely be edited."""


class PhotoEditCancelledError(PhotoEditError):
    """The caller cancelled before publication."""


def check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise PhotoEditCancelledError("photo edit cancelled")


@dataclass(frozen=True, eq=False)
class PhotoSource:
    """One retained original, decoded into canonical upright RGB pixel coordinates."""

    path: Path
    sha256: str
    byte_size: int
    width: int
    height: int
    dpi_x: float
    dpi_y: float
    effective_dpi: float
    pixels: np.ndarray = field(repr=False)
    orientation: int = 1
    exif: bytes = field(default=b"", repr=False)
    xmp: bytes = field(default=b"", repr=False)
    icc_profile: bytes | None = field(default=None, repr=False)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise PhotoEditError("source path must be absolute")
        sibling_name(self.path.name)
        digest(self.sha256)
        integer(self.byte_size, 1, MAX_SOURCE_BYTES, "source byte size")
        integer(self.width, 1, MAX_SOURCE_PIXELS, "source width")
        integer(self.height, 1, MAX_SOURCE_PIXELS, "source height")
        if self.width * self.height > MAX_SOURCE_PIXELS:
            raise PhotoEditError("source has too many pixels")
        integer(self.orientation, 1, 8, "source orientation")
        resolutions = (self.dpi_x, self.dpi_y, self.effective_dpi)
        if any(finite(value, "source DPI") <= 0 for value in resolutions):
            raise PhotoEditError("source DPI must be positive")
        if self.effective_dpi != max(self.dpi_x, self.dpi_y):
            raise PhotoEditError("effective source DPI must be the larger axis DPI")
        if not isinstance(self.pixels, np.ndarray) or self.pixels.dtype != np.uint8:
            raise PhotoEditError("source pixels must be uint8 RGB")
        if self.pixels.shape != (self.height, self.width, 3):
            raise PhotoEditError("source pixel dimensions do not match its identity")
        for blob in (self.exif, self.xmp, self.icc_profile):
            if blob is not None and (not isinstance(blob, bytes) or len(blob) > MAX_METADATA_BYTES):
                raise PhotoEditError("invalid or oversized source metadata")
        object.__setattr__(self, "pixels", _readonly(self.pixels))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, eq=False)
class EyeEdit:
    """Exact full-resolution local mask and the user's decision for one pupil."""

    id: str
    origin: str
    roi: tuple[int, int, int, int]
    center: tuple[float, float]
    mask: np.ndarray = field(repr=False)
    accepted: bool = False
    strength: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not 1 <= len(self.id) <= MAX_ID_CHARS:
            raise PhotoEditError("eye ID must be a short nonempty string")
        if not isinstance(self.origin, str) or self.origin not in {"detected", "manual"}:
            raise PhotoEditError("unknown eye origin")
        if type(self.accepted) is not bool:
            raise PhotoEditError("eye acceptance must be boolean")
        integer(self.strength, 0, 100, "eye strength")
        if not isinstance(self.roi, tuple) or len(self.roi) != ROI_COORDINATES:
            raise PhotoEditError("eye ROI must have four integer coordinates")
        for value in self.roi:
            integer(value, 0, MAX_SOURCE_PIXELS, "eye ROI coordinate")
        x0, y0, x1, y1 = self.roi
        area = (x1 - x0) * (y1 - y0)
        if x1 <= x0 or y1 <= y0 or area > MAX_MASK_PIXELS:
            raise PhotoEditError("eye mask dimensions are empty or too large")
        if not isinstance(self.mask, np.ndarray) or self.mask.dtype != bool:
            raise PhotoEditError("eye mask must be boolean")
        if self.mask.shape != (y1 - y0, x1 - x0) or not self.mask.any():
            raise PhotoEditError("eye mask must match its ROI and contain a pupil")
        if not isinstance(self.center, tuple) or len(self.center) != POINT_COORDINATES:
            raise PhotoEditError("eye center must have two coordinates")
        cx, cy = (finite(value, "eye center") for value in self.center)
        if not x0 <= cx < x1 or not y0 <= cy < y1:
            raise PhotoEditError("eye center lies outside its ROI")
        object.__setattr__(self, "mask", _readonly(self.mask))


@dataclass(frozen=True)
class PhotoTone:
    """Immutable integer controls for the versioned encoded-RGB tone transform."""

    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    strength: int = 100

    def __post_init__(self) -> None:
        integer(self.brightness, -TONE_CONTROL_LIMIT, TONE_CONTROL_LIMIT, "brightness")
        integer(self.contrast, -TONE_CONTROL_LIMIT, TONE_CONTROL_LIMIT, "contrast")
        integer(self.saturation, -TONE_PERCENT_LIMIT, TONE_PERCENT_LIMIT, "saturation")
        integer(self.strength, 0, TONE_PERCENT_LIMIT, "adjustment strength")


@dataclass(frozen=True)
class PhotoWhiteBalance:
    """Immutable integer temperature (+ warmer) and tint (+ magenta) for the linear-light gains."""

    temperature: int = 0
    tint: int = 0

    def __post_init__(self) -> None:
        integer(self.temperature, -WB_CONTROL_LIMIT, WB_CONTROL_LIMIT, "temperature")
        integer(self.tint, -WB_CONTROL_LIMIT, WB_CONTROL_LIMIT, "tint")


@dataclass(frozen=True)
class PhotoDetail:
    """Immutable integer luma and chroma noise reduction and sharpening, each 0 (off) to 100."""

    denoise_luma: int = 0
    denoise_chroma: int = 0
    sharpen: int = 0

    def __post_init__(self) -> None:
        integer(self.denoise_luma, 0, DETAIL_CONTROL_LIMIT, "luma noise reduction")
        integer(self.denoise_chroma, 0, DETAIL_CONTROL_LIMIT, "chroma noise reduction")
        integer(self.sharpen, 0, DETAIL_CONTROL_LIMIT, "sharpen")


@dataclass(frozen=True)
class PhotoGeometry:
    """Straighten (tenths of a degree, clockwise), then a crop in that frame, then quarter turns.

    The crop is half-open pixel edges inside the straightened frame; at angle 0 that frame is
    the source itself.
    """

    quarter_turns: int = 0
    crop: tuple[int, int, int, int] | None = None
    straighten_tenths: int = 0

    def __post_init__(self) -> None:
        integer(self.quarter_turns, 0, 3, "quarter turns")
        integer(
            self.straighten_tenths,
            -STRAIGHTEN_LIMIT_TENTHS,
            STRAIGHTEN_LIMIT_TENTHS,
            "straighten angle",
        )
        if self.crop is None:
            return
        if not isinstance(self.crop, tuple) or len(self.crop) != CROP_COORDINATES:
            raise PhotoEditError("crop must have four integer coordinates")
        for value in self.crop:
            integer(value, 0, MAX_SOURCE_PIXELS, "crop coordinate")
        left, top, right, bottom = self.crop
        if left >= right or top >= bottom:
            raise PhotoEditError("crop edges must enclose a nonempty area")


def frame_size(source: PhotoSource, geometry: PhotoGeometry) -> tuple[int, int]:
    """The straightened frame (width, height) a crop is measured in."""
    return straightened_size(source.width, source.height, geometry.straighten_tenths)


def min_crop_size(
    source: PhotoSource,
    geometry: PhotoGeometry = PhotoGeometry(),  # noqa: B008 - frozen value
) -> tuple[int, int]:
    """The smallest allowed crop (width, height): 5 mm at the effective DPI, within the frame."""
    frame_w, frame_h = frame_size(source, geometry)
    try:
        pixels = max(1, mm_to_px(MIN_CROP_MM, source.effective_dpi))
    except OverflowError:  # an absurd DPI: the minimum exceeds any source, so clamp to its extent
        return frame_w, frame_h
    return min(pixels, frame_w), min(pixels, frame_h)


def _check_crop(source: PhotoSource, geometry: PhotoGeometry) -> None:
    left, top, right, bottom = geometry.crop
    frame_w, frame_h = frame_size(source, geometry)
    if right > frame_w or bottom > frame_h:
        raise PhotoEditError("crop lies outside the retained source")
    if (left, top, right, bottom) == (0, 0, frame_w, frame_h):
        raise PhotoEditError("full-frame crop must be stored as no crop")
    min_width, min_height = min_crop_size(source, geometry)
    if right - left < min_width or bottom - top < min_height:
        raise PhotoEditError(f"crop is smaller than the {MIN_CROP_MM:g} mm minimum")


def _check_straighten(recipe: "PhotoEditRecipe") -> None:
    source = recipe.source
    if recipe.schema_version < STRAIGHTEN_SCHEMA_VERSION:
        raise PhotoEditError("recipe version cannot contain straighten")
    if source.dpi_x != source.dpi_y:
        raise PhotoEditError("straighten needs square pixels")
    min_w, min_h = min_crop_size(source)
    frame_w, frame_h = frame_size(source, recipe.geometry)
    if frame_w < min_w or frame_h < min_h:
        raise PhotoEditError(f"straighten angle leaves less than the {MIN_CROP_MM:g} mm minimum")


def _check_white_balance(recipe: "PhotoEditRecipe") -> None:
    if not isinstance(recipe.white_balance, PhotoWhiteBalance):
        raise PhotoEditError("recipe white balance requires validated temperature and tint")
    if (
        recipe.schema_version < WHITE_BALANCE_SCHEMA_VERSION
        and recipe.white_balance != PhotoWhiteBalance()
    ):
        raise PhotoEditError("recipe version cannot contain white balance")


def _check_detail(recipe: "PhotoEditRecipe") -> None:
    if not isinstance(recipe.detail, PhotoDetail):
        raise PhotoEditError("recipe detail requires validated noise reduction and sharpening")
    if recipe.schema_version < DETAIL_SCHEMA_VERSION and recipe.detail != PhotoDetail():
        raise PhotoEditError("recipe version cannot contain detail adjustments")


@dataclass(frozen=True, eq=False)
class PhotoEditRecipe:
    """Replay from source, never from a previously encoded derivative."""

    source: PhotoSource
    eyes: tuple[EyeEdit, ...] = ()
    schema_version: int = SCHEMA_VERSION
    algorithm_version: str = ALGORITHM_VERSION
    quality: int = 95
    tone: PhotoTone = field(default_factory=PhotoTone, kw_only=True)
    geometry: PhotoGeometry = field(default_factory=PhotoGeometry, kw_only=True)
    white_balance: PhotoWhiteBalance = field(default_factory=PhotoWhiteBalance, kw_only=True)
    detail: PhotoDetail = field(default_factory=PhotoDetail, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.source, PhotoSource):
            raise PhotoEditError("recipe requires a retained source")
        validate_version(self.schema_version, self.algorithm_version)
        if not isinstance(self.tone, PhotoTone):
            raise PhotoEditError("recipe tone requires validated photo adjustments")
        if self.schema_version == LEGACY_SCHEMA_VERSION and self.tone != PhotoTone():
            raise PhotoEditError("legacy recipes cannot contain tone adjustments")
        _check_white_balance(self)
        _check_detail(self)
        if not isinstance(self.geometry, PhotoGeometry):
            raise PhotoEditError("recipe geometry requires a validated crop and rotation")
        if self.geometry.straighten_tenths:
            _check_straighten(self)
        if self.schema_version < GEOMETRY_SCHEMA_VERSION and self.geometry != PhotoGeometry():
            raise PhotoEditError("recipe version cannot contain geometry")
        if self.geometry.crop is not None:
            _check_crop(self.source, self.geometry)
        integer(self.quality, 1, 100, "JPEG quality")
        if not isinstance(self.eyes, tuple) or len(self.eyes) > MAX_EYES:
            raise PhotoEditError("too many eye corrections")
        ids: set[str] = set()
        pixels = 0
        for eye in self.eyes:
            if not isinstance(eye, EyeEdit) or eye.id in ids:
                raise PhotoEditError("duplicate or invalid eye ID")
            ids.add(eye.id)
            pixels += eye.mask.size
            if pixels > MAX_MASK_PIXELS:
                raise PhotoEditError("total eye mask pixels exceed the recipe limit")
            if eye.roi[2] > self.source.width or eye.roi[3] > self.source.height:
                raise PhotoEditError("eye ROI lies outside the retained source")
