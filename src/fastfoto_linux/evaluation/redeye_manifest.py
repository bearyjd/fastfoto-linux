"""The red-eye evaluation manifest: a versioned JSON file, validated strictly."""

from dataclasses import dataclass
from pathlib import Path

FORMAT = "fastfoto-redeye-eval"
VERSION = 1
MAX_MANIFEST_BYTES = 8_000_000
MAX_IMAGES = 10_000
MAX_FACES_PER_IMAGE = 64
MAX_NEGATIVES_PER_IMAGE = 64
CATEGORIES = (
    "red_clothing",
    "lips",
    "jewelry",
    "signs",
    "flowers",
    "printed_text",
    "spectacles",
    "non_red_pupils",
    "reflections",
    "other",
)
SPLITS = ("tuning", "heldout")


class ManifestError(ValueError):
    """The manifest or one of its paths is not acceptable."""


@dataclass(frozen=True)
class Rights:
    licence: str
    source: str
    consent_scope: str | None
    redistributable: bool


@dataclass(frozen=True)
class GtEye:
    x: float
    y: float
    r: float
    red: bool


@dataclass(frozen=True)
class GtFace:
    id: str
    eyes: tuple[GtEye, GtEye]


@dataclass(frozen=True)
class Region:
    category: str
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class ManifestImage:
    id: str
    path: str
    sha256: str
    dpi: int
    split: str
    rights: Rights
    faces: tuple[GtFace, ...]
    negatives: tuple[Region, ...]
    group: str | None = None


@dataclass(frozen=True)
class Manifest:
    split_salt: str
    images: tuple[ManifestImage, ...]
    sha256: str
    root: Path


def check_relpath(rel: str) -> None:
    """Refuse an unsafe image path (absolute, backslash, NUL, empty or ``.``/``..`` segment)."""
    raise NotImplementedError


def parse_manifest(data: bytes, root: Path) -> Manifest:
    """Validate manifest bytes; every problem is a ``ManifestError``."""
    raise NotImplementedError


def load_manifest(path: Path) -> Manifest:
    """Read (at most ``MAX_MANIFEST_BYTES``) and validate the manifest at ``path``."""
    raise NotImplementedError
