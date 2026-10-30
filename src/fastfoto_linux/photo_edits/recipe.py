"""Strict, allocation-bounded JSON recipes with exact packed local masks."""

import base64
import binascii
import json
from dataclasses import asdict, replace
from typing import Any

import numpy as np

from fastfoto_linux.photo_edits.model import (
    GEOMETRY_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    MAX_EYES,
    MAX_MASK_PIXELS,
    MAX_RECIPE_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_PIXELS,
    POINT_COORDINATES,
    RECIPE_VERSIONS,
    ROI_COORDINATES,
    STRAIGHTEN_SCHEMA_VERSION,
    TONE_SCHEMA_VERSION,
    WHITE_BALANCE_SCHEMA_VERSION,
    EyeEdit,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoSource,
    PhotoTone,
    PhotoWhiteBalance,
    digest,
    finite,
    frame_size,
    integer,
    sibling_name,
    validate_version,
)

TONE_KEYS = frozenset({"brightness", "contrast", "saturation", "strength"})
GEOMETRY_KEYS = frozenset({"quarter_turns", "crop"})
STRAIGHTEN_KEYS = GEOMETRY_KEYS | {"straighten_tenths"}
WHITE_BALANCE_KEYS = frozenset({"temperature", "tint"})
ROOT_KEYS = frozenset({"schema_version", "algorithm_version", "quality", "source", "eyes"})
SOURCE_KEYS = (
    "sha256",
    "byte_size",
    "width",
    "height",
    "dpi_x",
    "dpi_y",
    "effective_dpi",
    "orientation",
)
EYE_KEYS = frozenset({"id", "origin", "roi", "center", "accepted", "strength", "mask"})
BITS_PER_BYTE = 8
BASE64_GROUP_SIZE = 4
BASE64_INPUT_GROUP = 3


def source_identity(source: PhotoSource) -> dict[str, Any]:
    return {"name": source.path.name, **{key: getattr(source, key) for key in SOURCE_KEYS}}


def _eye_dict(eye: EyeEdit) -> dict[str, Any]:
    bits = base64.b64encode(np.packbits(eye.mask.ravel()).tobytes()).decode("ascii")
    return {
        "id": eye.id,
        "origin": eye.origin,
        "roi": eye.roi,
        "center": eye.center,
        "accepted": eye.accepted,
        "strength": eye.strength,
        "mask": {"shape": eye.mask.shape, "bits": bits},
    }


def recipe_object(recipe: PhotoEditRecipe) -> dict[str, Any]:
    payload = {
        "schema_version": recipe.schema_version,
        "algorithm_version": recipe.algorithm_version,
        "quality": recipe.quality,
        "source": source_identity(recipe.source),
        "eyes": [_eye_dict(eye) for eye in recipe.eyes],
    }
    if recipe.schema_version >= TONE_SCHEMA_VERSION:
        payload["tone"] = asdict(recipe.tone)
    if recipe.schema_version >= GEOMETRY_SCHEMA_VERSION:
        crop = recipe.geometry.crop
        geometry = {
            "crop": None if crop is None else list(crop),
            "quarter_turns": recipe.geometry.quarter_turns,
        }
        if recipe.schema_version >= STRAIGHTEN_SCHEMA_VERSION:
            geometry["straighten_tenths"] = recipe.geometry.straighten_tenths
        payload["geometry"] = geometry
    if recipe.schema_version >= WHITE_BALANCE_SCHEMA_VERSION:
        payload["white_balance"] = asdict(recipe.white_balance)
    return payload


def json_bytes(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_RECIPE_BYTES:
        raise PhotoEditError("photo recipe exceeds its byte limit")
    return data


def recipe_bytes(recipe: PhotoEditRecipe) -> bytes:
    """Encode source identity and exact local masks as a schema-versioned JSON recipe."""
    return json_bytes(recipe_object(recipe))


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise PhotoEditError("duplicate JSON field in photo recipe")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise PhotoEditError("nonfinite number in photo recipe")


def fields(value: object, expected: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PhotoEditError(f"invalid {label} fields")
    return value


def read_object(data: bytes) -> dict[str, Any]:
    """The validated recipe object, checked before any source is decoded."""
    return _read_checked(data)[0]


def _read_checked(
    data: bytes,
) -> tuple[dict[str, Any], PhotoTone, PhotoGeometry, PhotoWhiteBalance]:
    """The validated recipe object with its edit controls, validated here and only here."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_RECIPE_BYTES:
        raise PhotoEditError("photo recipe exceeds its byte limit or is empty")
    try:
        value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PhotoEditError("photo recipe is not valid bounded JSON") from error
    if not isinstance(value, dict):
        raise PhotoEditError("photo recipe must be an object")
    validate_version(value.get("schema_version"), value.get("algorithm_version"))
    expected = ROOT_KEYS | ({"output"} if "output" in value else set())
    if value["schema_version"] >= TONE_SCHEMA_VERSION:
        expected |= {"tone"}
    if value["schema_version"] >= GEOMETRY_SCHEMA_VERSION:
        expected |= {"geometry"}
    if value["schema_version"] >= WHITE_BALANCE_SCHEMA_VERSION:
        expected |= {"white_balance"}
    fields(value, expected, "photo recipe")
    integer(value["quality"], 1, 100, "JPEG quality")
    tone, geometry = _read_tone(value), _read_geometry(value)
    white_balance = _read_white_balance(value)
    if "output" in value:
        output = fields(value["output"], {"name", "sha256"}, "output identity")
        sibling_name(output["name"])
        digest(output["sha256"])
    return value, tone, geometry, white_balance


def _read_tone(payload: dict[str, Any]) -> PhotoTone:
    if payload["schema_version"] == LEGACY_SCHEMA_VERSION:
        return PhotoTone()
    tone = fields(payload["tone"], TONE_KEYS, "photo tone")
    return PhotoTone(**tone)


def _read_white_balance(payload: dict[str, Any]) -> PhotoWhiteBalance:
    if payload["schema_version"] < WHITE_BALANCE_SCHEMA_VERSION:
        return PhotoWhiteBalance()
    return PhotoWhiteBalance(
        **fields(payload["white_balance"], WHITE_BALANCE_KEYS, "white balance")
    )


def _read_geometry(payload: dict[str, Any]) -> PhotoGeometry:
    version = payload["schema_version"]
    if version < GEOMETRY_SCHEMA_VERSION:
        return PhotoGeometry()
    keys = STRAIGHTEN_KEYS if version >= STRAIGHTEN_SCHEMA_VERSION else GEOMETRY_KEYS
    geometry = fields(payload["geometry"], keys, "photo geometry")
    crop = geometry["crop"]
    if crop is not None and not isinstance(crop, list):
        raise PhotoEditError("crop must be null or a list of four integers")
    return PhotoGeometry(
        geometry["quarter_turns"],
        None if crop is None else tuple(crop),
        geometry.get("straighten_tenths", 0),
    )


def _mask_shape(payload: dict[str, Any]) -> tuple[int, int]:
    shape = payload["shape"]
    if not isinstance(shape, list) or len(shape) != POINT_COORDINATES:
        raise PhotoEditError("eye mask shape must have two integer dimensions")
    height, width = (integer(size, 1, MAX_MASK_PIXELS, "mask dimension") for size in shape)
    if height * width > MAX_MASK_PIXELS:
        raise PhotoEditError("eye mask shape exceeds its pixel limit")
    return height, width


def _mask_budget(eyes: list[object]) -> None:
    total = 0
    for eye in eyes:
        payload = fields(eye, EYE_KEYS, "eye correction")
        height, width = _mask_shape(fields(payload["mask"], {"shape", "bits"}, "eye mask"))
        total += height * width
        if total > MAX_MASK_PIXELS:
            raise PhotoEditError("total eye mask pixels exceed the recipe limit")


def _mask(value: object, roi: tuple[int, ...]) -> np.ndarray:
    payload = fields(value, {"shape", "bits"}, "eye mask")
    height, width = _mask_shape(payload)
    count = height * width
    if (height, width) != (roi[3] - roi[1], roi[2] - roi[0]):
        raise PhotoEditError("eye mask shape does not match its ROI")
    byte_count = (count + BITS_PER_BYTE - 1) // BITS_PER_BYTE
    encoded_length = BASE64_GROUP_SIZE * (
        (byte_count + BASE64_INPUT_GROUP - 1) // BASE64_INPUT_GROUP
    )
    bits = payload["bits"]
    if not isinstance(bits, str) or len(bits) != encoded_length:
        raise PhotoEditError("packed eye mask has an invalid size")
    try:
        packed = base64.b64decode(bits, validate=True)
    except (ValueError, binascii.Error) as error:
        raise PhotoEditError("packed eye mask is invalid base64") from error
    if len(packed) != byte_count or base64.b64encode(packed).decode("ascii") != bits:
        raise PhotoEditError("packed eye mask has invalid padding")
    unpacked = np.unpackbits(np.frombuffer(packed, dtype=np.uint8))
    if unpacked[count:].any():
        raise PhotoEditError("packed eye mask has nonzero padding bits")
    return unpacked[:count].reshape(height, width).astype(bool)


def _eye(value: object) -> EyeEdit:
    payload = fields(value, EYE_KEYS, "eye correction")
    roi, center = payload["roi"], payload["center"]
    if not isinstance(roi, list) or len(roi) != ROI_COORDINATES:
        raise PhotoEditError("eye ROI needs four integer coordinates")
    for coordinate in roi:
        integer(coordinate, 0, MAX_SOURCE_PIXELS, "ROI coordinate")
    if not isinstance(center, list) or len(center) != POINT_COORDINATES:
        raise PhotoEditError("eye center needs two finite coordinates")
    return EyeEdit(
        payload["id"],
        payload["origin"],
        tuple(roi),
        tuple(center),
        _mask(payload["mask"], tuple(roi)),
        payload["accepted"],
        payload["strength"],
    )


def parse_recipe(data: bytes, source: PhotoSource) -> PhotoEditRecipe:
    """Decode a bounded recipe only when its retained source identity matches."""
    payload, tone, geometry, white_balance = _read_checked(data)
    stored_source = fields(payload["source"], {"name", *SOURCE_KEYS}, "source identity")
    sibling_name(stored_source["name"])
    if any(type(stored_source[key]) is bool for key in SOURCE_KEYS):
        raise PhotoEditError("source identity fields cannot be boolean")
    integer(stored_source["byte_size"], 1, MAX_SOURCE_BYTES, "source byte size")
    for key in ("width", "height"):
        integer(stored_source[key], 1, MAX_SOURCE_PIXELS, f"source {key}")
    integer(stored_source["orientation"], 1, 8, "source orientation")
    digest(stored_source["sha256"])
    for key in ("dpi_x", "dpi_y", "effective_dpi"):
        if finite(stored_source[key], key) <= 0:
            raise PhotoEditError("source DPI must be positive")
    if stored_source != source_identity(source):
        raise PhotoEditError("recipe source identity does not match the retained source hash")
    eyes = payload["eyes"]
    if not isinstance(eyes, list) or len(eyes) > MAX_EYES:
        raise PhotoEditError("too many or invalid eye corrections")
    _mask_budget(eyes)
    return PhotoEditRecipe(
        source=source,
        eyes=tuple(_eye(eye) for eye in eyes),
        schema_version=payload["schema_version"],
        algorithm_version=payload["algorithm_version"],
        quality=payload["quality"],
        tone=tone,
        geometry=geometry,
        white_balance=white_balance,
    )


def update_tone(recipe: PhotoEditRecipe, tone: PhotoTone) -> PhotoEditRecipe:
    """Preserve no-op identity; upgrade a changed v1 draft without mutating it or downgrading v3."""
    if not isinstance(recipe, PhotoEditRecipe) or not isinstance(tone, PhotoTone):
        raise PhotoEditError("tone updates require a recipe and validated photo adjustments")
    if recipe.tone == tone:
        return recipe
    schema = max(recipe.schema_version, TONE_SCHEMA_VERSION)
    return replace(
        recipe, tone=tone, schema_version=schema, algorithm_version=RECIPE_VERSIONS[schema]
    )


def update_geometry(recipe: PhotoEditRecipe, geometry: PhotoGeometry) -> PhotoEditRecipe:
    """Preserve no-op identity; a change reaches schema 3, or 4 with an angle, and never drops."""
    if not isinstance(recipe, PhotoEditRecipe) or not isinstance(geometry, PhotoGeometry):
        raise PhotoEditError("geometry updates require a recipe and validated geometry")
    if geometry.crop == (0, 0, *frame_size(recipe.source, geometry)):
        geometry = replace(geometry, crop=None)
    if geometry == recipe.geometry:
        return recipe
    wanted = STRAIGHTEN_SCHEMA_VERSION if geometry.straighten_tenths else GEOMETRY_SCHEMA_VERSION
    schema = max(recipe.schema_version, wanted)
    return replace(
        recipe, geometry=geometry, schema_version=schema, algorithm_version=RECIPE_VERSIONS[schema]
    )


def update_white_balance(recipe: PhotoEditRecipe, balance: PhotoWhiteBalance) -> PhotoEditRecipe:
    """Preserve no-op identity; a non-neutral balance reaches schema 5, and no draft ever drops."""
    if not isinstance(recipe, PhotoEditRecipe) or not isinstance(balance, PhotoWhiteBalance):
        raise PhotoEditError("white balance updates require a recipe and validated white balance")
    if recipe.white_balance == balance:
        return recipe
    schema = recipe.schema_version
    if balance != PhotoWhiteBalance():
        schema = max(schema, WHITE_BALANCE_SCHEMA_VERSION)
    return replace(
        recipe,
        white_balance=balance,
        schema_version=schema,
        algorithm_version=RECIPE_VERSIONS[schema],
    )
