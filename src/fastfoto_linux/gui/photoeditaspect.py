"""Crop shapes (aspect presets) for the photo editor: pure integer geometry, no Qt, no numpy."""

from dataclasses import dataclass

Box = tuple[int, int, int, int]
Ratio = tuple[int, int]
Size = tuple[int, int]


@dataclass(frozen=True)
class AspectPreset:
    id: str
    label: str
    long: int
    short: int


PRESETS: tuple[AspectPreset, ...] = ()


def half_up(n: int, d: int) -> int:
    raise NotImplementedError


def ceil_div(n: int, d: int) -> int:
    raise NotImplementedError


def crop_ratio(preset_id: str, portrait: bool, *, frame: Size, quarter_turns: int) -> Ratio | None:
    raise NotImplementedError


def default_portrait(box: Box, quarter_turns: int) -> bool:
    raise NotImplementedError


def fit_centred(box: Box, ratio: Ratio, *, frame: Size, minimum: Size) -> Box | None:
    raise NotImplementedError


def swap_box(box: Box, ratio_swapped: Ratio, *, frame: Size, minimum: Size) -> Box | None:
    raise NotImplementedError


def aspect_crop(  # noqa: PLR0913 - dimensions describe one explicit transform
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    ratio: Ratio,
    min_width: int,
    min_height: int,
    source_width: int,
    source_height: int,
    painted_width: float,
    painted_height: float,
    item_width: float,
    item_height: float,
) -> Box | None:
    raise NotImplementedError
