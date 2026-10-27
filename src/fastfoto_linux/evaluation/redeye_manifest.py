"""The red-eye evaluation manifest: a versioned JSON file, validated strictly."""

import hashlib
import json
import math
import os
import re
import stat
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
MIN_DPI, MAX_DPI = 50, 2400
_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SHA = re.compile(r"[0-9a-f]{64}")
_SALT = re.compile(r"[0-9a-f]{16,64}")
_TOP_KEYS = {"format", "version", "split_salt", "images"}
_IMAGE_REQUIRED = {
    "id",
    "path",
    "sha256",
    "dpi",
    "upright",
    "split",
    "rights",
    "faces",
    "negatives",
}
_RIGHTS_KEYS = {"licence", "source", "consent_scope", "redistributable"}
MAX_COORD = 1e7
MAX_RADIUS = 10_000.0
EYES_PER_FACE = 2
BOX_VALUES = 4
_EYE_KEYS = {"x", "y", "r", "red"}


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


def _fail(message: str) -> ManifestError:
    return ManifestError(message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _fail("duplicate JSON key in manifest")
    return dict(pairs)


def _invalid_constant(name: str) -> object:
    raise _fail(f"{name} is not allowed in the manifest")


def check_relpath(rel: str) -> None:
    """Refuse an unsafe image path (absolute, backslash, NUL, empty or ``.``/``..`` segment)."""
    if not rel or "\0" in rel or "\\" in rel or rel.startswith("/"):
        raise _fail("image path must be a relative POSIX path")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise _fail("image path has an empty, '.' or '..' segment")


def _dict(value: object, keys: set[str], what: str, required: set[str] | None = None) -> dict:
    if type(value) is not dict:
        raise _fail(f"{what} must be an object")
    missing = (keys if required is None else required) - value.keys()
    if missing or value.keys() - keys:
        raise _fail(f"{what} has missing or unknown keys")
    return value


def _text(value: object, what: str, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or (pattern and not pattern.fullmatch(value)):
        raise _fail(f"{what} is not valid")
    return value


def _number(value: object, what: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):  # type: ignore[arg-type]
        raise _fail(f"{what} must be a finite number")
    return float(value)  # type: ignore[arg-type]


def _int(value: object, what: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise _fail(f"{what} must be an integer from {low} to {high}")
    return value


def _bool(value: object, what: str) -> bool:
    if type(value) is not bool:
        raise _fail(f"{what} must be true or false")
    return value


def _list(value: object, what: str, limit: int) -> list:
    if type(value) is not list or len(value) > limit:
        raise _fail(f"{what} must be a list of at most {limit} items")
    return value


def _rights(value: object) -> Rights:
    raw = _dict(value, _RIGHTS_KEYS, "rights")
    consent = raw["consent_scope"]
    if consent is not None and type(consent) is not str:
        raise _fail("consent_scope must be text or null")
    source = raw["source"]
    if type(source) is not str:
        raise _fail("rights source must be text")
    return Rights(
        _text(raw["licence"], "licence"),
        source,
        consent,
        _bool(raw["redistributable"], "redistributable"),
    )


def _eye(value: object) -> GtEye:
    raw = _dict(value, _EYE_KEYS, "eye")
    radius = _number(raw["r"], "eye radius")
    if not 0 < radius <= MAX_RADIUS:
        raise _fail(f"eye radius must be above 0 and at most {MAX_RADIUS:g}")
    x, y = _number(raw["x"], "eye x"), _number(raw["y"], "eye y")
    if abs(x) > MAX_COORD or abs(y) > MAX_COORD:
        raise _fail(f"eye coordinates must be within +-{MAX_COORD:g}")
    return GtEye(x, y, radius, _bool(raw["red"], "red"))


def _face(value: object) -> GtFace:
    raw = _dict(value, {"id", "eyes"}, "face")
    eyes = _list(raw["eyes"], "eyes", EYES_PER_FACE)
    if len(eyes) != EYES_PER_FACE:
        raise _fail("a face needs exactly two eyes")
    first, second = (_eye(e) for e in eyes)
    return GtFace(_text(raw["id"], "face id", _ID), (first, second))


def _region(value: object) -> Region:
    raw = _dict(value, {"category", "box"}, "negative region")
    if raw["category"] not in CATEGORIES:
        raise _fail("unknown negative category")
    box = _list(raw["box"], "box", BOX_VALUES)
    if len(box) != BOX_VALUES:
        raise _fail("a box needs four numbers")
    x0, y0, x1, y1 = (_int(v, "box value", 0, 1_000_000) for v in box)
    if x1 <= x0 or y1 <= y0:
        raise _fail("a box must have x1 > x0 and y1 > y0")
    return Region(raw["category"], (x0, y0, x1, y1))


def _unique(values: list[str], what: str) -> None:
    if len(set(values)) != len(values):
        raise _fail(f"duplicate {what}")


def _image(value: object) -> ManifestImage:
    raw = _dict(value, _IMAGE_REQUIRED | {"group"}, "image", _IMAGE_REQUIRED)
    if raw["upright"] is not True:
        raise _fail("upright must be true: the face detector only finds upright faces")
    path = _text(raw["path"], "path")
    check_relpath(path)
    if raw["split"] not in SPLITS:
        raise _fail("split must be 'tuning' or 'heldout'")
    group = raw.get("group")
    faces = tuple(_face(f) for f in _list(raw["faces"], "faces", MAX_FACES_PER_IMAGE))
    _unique([f.id for f in faces], "face id")
    return ManifestImage(
        id=_text(raw["id"], "image id", _ID),
        path=path,
        sha256=_text(raw["sha256"], "sha256", _SHA),
        dpi=_int(raw["dpi"], "dpi", MIN_DPI, MAX_DPI),
        split=raw["split"],
        rights=_rights(raw["rights"]),
        faces=faces,
        negatives=tuple(
            _region(r) for r in _list(raw["negatives"], "negatives", MAX_NEGATIVES_PER_IMAGE)
        ),
        group=None if group is None else _text(group, "group", _ID),
    )


def parse_manifest(data: bytes, root: Path) -> Manifest:
    """Validate manifest bytes; every problem is a ``ManifestError``."""
    try:
        raw = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as error:
        if isinstance(error, ManifestError):
            raise
        raise _fail("manifest is not valid JSON") from error
    top = _dict(raw, _TOP_KEYS, "manifest")
    if top["format"] != FORMAT or type(top["version"]) is not int or top["version"] != VERSION:
        raise _fail("not a version 1 fastfoto-redeye-eval manifest")
    salt = _text(top["split_salt"], "split_salt", _SALT)
    images = tuple(_image(i) for i in _list(top["images"], "images", MAX_IMAGES))
    _unique([i.id for i in images], "image id")
    _unique([i.sha256 for i in images], "image sha256")
    return Manifest(salt, images, hashlib.sha256(data).hexdigest(), root)


def load_manifest(path: Path) -> Manifest:
    """Read (at most ``MAX_MANIFEST_BYTES``) and validate the manifest at ``path``."""
    try:
        # O_NONBLOCK: opening a FIFO must not wait for a writer.
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise _fail("the manifest must be a regular file")
            data = handle.read(MAX_MANIFEST_BYTES + 1)
        root = path.resolve(strict=True).parent
    except OSError as error:
        raise _fail("cannot read the manifest file") from error
    if len(data) > MAX_MANIFEST_BYTES:
        raise _fail("manifest is too large")
    return parse_manifest(data, root)
