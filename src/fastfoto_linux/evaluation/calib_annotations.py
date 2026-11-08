"""Strict parsing of the per-feature annotations of a corpus manifest.

Every field is checked: unknown keys are refused, a bool is not an int, numbers are bounded, lists
are capped and the boxes are checked against the image once it is decoded. A refusal is a fixed
message (an ``AnnotationError``) that never repeats a value from the manifest; the caller adds the
item id.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fastfoto_linux.evaluation.corpus_types import CorpusError

MIN_DPI = 50
MAX_DPI = 2400
MAX_TENTHS = 450
MAX_ANNOTATORS = 4
MAX_BOXES = 16
MAX_COORDINATE = 1_000_000
LABELS = ("colour", "grey", "bw")
AXES = ("h", "v")
BOX_LENGTH = 4

Box = tuple[int, int, int, int]


class AnnotationError(CorpusError):
    """An annotation is not acceptable (the message names the problem, never the value)."""


@dataclass(frozen=True)
class DeskewNote:
    """``correction_tenths``: the clockwise correction that levels the page, per annotator."""

    dpi: int | None
    correction_tenths: tuple[int, ...]


@dataclass(frozen=True)
class ColourNote:
    """``label``: the least rich mode that keeps every meaningful mark."""

    dpi: int | None
    label: str


@dataclass(frozen=True)
class WbNote:
    neutral_boxes: tuple[Box, ...]
    cast: bool


@dataclass(frozen=True)
class EdgeBox:
    """``axis`` "h": the edge is crossed along x (a vertical edge); "v": along y."""

    box: Box
    axis: str


@dataclass(frozen=True)
class DetailNote:
    dpi: int
    flat_boxes: tuple[Box, ...]
    edge_boxes: tuple[EdgeBox, ...]


def _fields(raw: object, required: set[str], optional: frozenset[str], what: str) -> Mapping:
    if not isinstance(raw, Mapping):
        raise AnnotationError(f"the {what} annotation must be an object")
    if not required <= raw.keys():
        raise AnnotationError(f"the {what} annotation lacks a required field")
    if raw.keys() - required - optional:
        raise AnnotationError(f"the {what} annotation has an unknown field")
    return raw


def _int(value: object, low: int, high: int, what: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise AnnotationError(f"{what} must be an integer from {low} to {high}")
    return value


def _items(value: object, what: str, most: int) -> Sequence:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= most:
        raise AnnotationError(f"{what} must be a list of 1 to {most} entries")
    return value


def _box(value: object) -> Box:
    if not isinstance(value, (list, tuple)) or len(value) != BOX_LENGTH:
        raise AnnotationError("a box must be [x, y, width, height]")
    x, y = (_int(v, 0, MAX_COORDINATE, "a box origin") for v in value[:2])
    width, height = (_int(v, 1, MAX_COORDINATE, "a box size") for v in value[2:])
    return x, y, width, height


def _boxes(value: object, what: str) -> tuple[Box, ...]:
    return tuple(_box(v) for v in _items(value, what, MAX_BOXES))


def _optional_dpi(raw: Mapping) -> int | None:
    return _int(raw["dpi"], MIN_DPI, MAX_DPI, "dpi") if "dpi" in raw else None


def parse_deskew(raw: object) -> DeskewNote:
    fields = _fields(raw, {"correction_tenths"}, frozenset({"dpi"}), "deskew")
    tenths = tuple(
        _int(v, -MAX_TENTHS, MAX_TENTHS, "a correction")
        for v in _items(fields["correction_tenths"], "correction_tenths", MAX_ANNOTATORS)
    )
    return DeskewNote(_optional_dpi(fields), tenths)


def parse_autocolour(raw: object) -> ColourNote:
    fields = _fields(raw, {"label"}, frozenset({"dpi"}), "autocolour")
    label = fields["label"]
    if type(label) is not str or label not in LABELS:
        raise AnnotationError("label must be colour, grey or bw")
    return ColourNote(_optional_dpi(fields), label)


def parse_wb(raw: object) -> WbNote:
    fields = _fields(raw, {"neutral_boxes", "cast"}, frozenset(), "wb")
    if type(fields["cast"]) is not bool:
        raise AnnotationError("cast must be true or false")
    return WbNote(_boxes(fields["neutral_boxes"], "neutral_boxes"), fields["cast"])


def _edge(value: object) -> EdgeBox:
    fields = _fields(value, {"box", "axis"}, frozenset(), "edge box")
    if type(fields["axis"]) is not str or fields["axis"] not in AXES:
        raise AnnotationError("axis must be h or v")
    return EdgeBox(_box(fields["box"]), fields["axis"])


def parse_detail(raw: object) -> DetailNote:
    fields = _fields(raw, {"dpi", "flat_boxes", "edge_boxes"}, frozenset(), "detail")
    edges = tuple(_edge(v) for v in _items(fields["edge_boxes"], "edge_boxes", MAX_BOXES))
    dpi = _int(fields["dpi"], MIN_DPI, MAX_DPI, "dpi")
    return DetailNote(dpi, _boxes(fields["flat_boxes"], "flat_boxes"), edges)


def check_inside(boxes: Sequence[Box], width: int, height: int) -> None:
    """Refuse (``AnnotationError``) a box not wholly inside a ``width`` x ``height`` image."""
    for x, y, w, h in boxes:
        if x + w > width or y + h > height:
            raise AnnotationError("a box lies outside the image")


PARSERS = {
    "deskew": parse_deskew,
    "autocolour": parse_autocolour,
    "wb": parse_wb,
    "detail": parse_detail,
}
