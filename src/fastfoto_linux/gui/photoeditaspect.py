"""Crop shapes (aspect presets) for the photo editor: pure integer geometry, no Qt, no numpy.

A box is ``(left, top, right, bottom)`` in whole pixels, half-open, in the straightened frame
before the quarter turns. A ratio ``(rw, rh)`` is in that same frame. Every division rounds with
integers only, so Python and the QML canvas agree exactly.
"""

import math
from dataclasses import dataclass

Box = tuple[int, int, int, int]
Ratio = tuple[int, int]
Size = tuple[int, int]

FRAME_MICRO = 6  # decimals kept when mapping the pointer, as in photoeditcoords.source_crop


@dataclass(frozen=True)
class AspectPreset:
    id: str
    label: str
    long: int
    short: int


PRESETS: tuple[AspectPreset, ...] = (
    AspectPreset("free", "Free", 0, 0),
    AspectPreset("original", "Original", 0, 0),
    AspectPreset("1:1", "1:1", 1, 1),
    AspectPreset("4:3", "4:3", 4, 3),
    AspectPreset("3:2", "3:2", 3, 2),
    AspectPreset("16:9", "16:9", 16, 9),
    AspectPreset("5:7", "5:7", 7, 5),
)


def half_up(n: int, d: int) -> int:
    """``n / d`` rounded half up, for ``n >= 0`` and ``d > 0`` (``round`` goes to even)."""
    return (2 * n + d) // (2 * d)


def ceil_div(n: int, d: int) -> int:
    return -(-n // d)


def crop_ratio(preset_id: str, portrait: bool, *, frame: Size, quarter_turns: int) -> Ratio | None:
    """The ratio a box needs in the unturned frame, so the turned picture has the chosen shape."""
    preset = next((p for p in PRESETS if p.id == preset_id), None)
    if preset is None:
        raise ValueError("unknown crop shape")
    if preset.id == "free":
        return None
    long, short = (
        (max(frame), min(frame)) if preset.id == "original" else (preset.long, preset.short)
    )
    dw, dh = (short, long) if portrait else (long, short)
    rw, rh = (dh, dw) if quarter_turns % 2 else (dw, dh)
    divisor = math.gcd(rw, rh)
    return rw // divisor, rh // divisor


def default_portrait(box: Box, quarter_turns: int) -> bool:
    """Whether the box is taller than wide once turned; a square counts as landscape."""
    width, height = box[2] - box[0], box[3] - box[1]
    out_w, out_h = (height, width) if quarter_turns % 2 else (width, height)
    return out_w < out_h


def _reach(limit: int, a: int, b: int) -> int:
    """The largest ``x`` with ``half_up(x * b, a) <= limit``: ``x*b/a < limit + 1/2``."""
    return ((2 * limit + 1) * a - 1) // (2 * b)


def _shape_in(width: int, height: int, ratio: Ratio) -> Size:
    """The largest shaped box inside ``width`` x ``height``; full width wins a tie.

    Shaped: the height is the rounded width's share (A), or the width is the rounded height's
    (B). The widest A and the tallest B are the only candidates, as area grows with either side.
    A very wide or tall ratio can leave no whole-pixel box inside a small one; that is (0, 0).
    """
    rw, rh = ratio
    wa = min(width, _reach(height, rw, rh))
    hb = min(height, _reach(width, rh, rw))
    first, second = (wa, half_up(wa * rh, rw)), (half_up(hb * rw, rh), hb)
    candidates = [c for c in (first, second) if c[0] >= 1 and c[1] >= 1]
    if not candidates:
        return 0, 0
    best = candidates[0]
    return candidates[-1] if candidates[-1][0] * candidates[-1][1] > best[0] * best[1] else best


def _grown(ratio: Ratio, minimum: Size, frame: Size) -> Size:
    """The smallest shaped box reaching ``minimum`` inside ``frame``, or (0, 0).

    Shaped means the height is the rounded width's share, or the width is the rounded height's.
    The least width that rounds up to the minimum height is ``ceil((2*min_h - 1)*rw / (2*rh))``.
    """
    rw, rh = ratio
    (min_w, min_h), (fw, fh) = minimum, frame
    w = max(min_w, ceil_div((2 * min_h - 1) * rw, 2 * rh))
    h = half_up(w * rh, rw)
    if w <= fw and h <= fh:
        return w, h
    h = max(min_h, ceil_div((2 * min_w - 1) * rh, 2 * rw))
    w = half_up(h * rw, rh)
    return (w, h) if w <= fw and h <= fh else (0, 0)


def fit_centred(box: Box, ratio: Ratio, *, frame: Size, minimum: Size) -> Box | None:
    """The largest box of ``ratio`` centred in ``box``, grown to the minimum; None if too small."""
    left, top, right, bottom = box
    w, h = _shape_in(right - left, bottom - top, ratio)
    min_w, min_h = max(1, minimum[0]), max(1, minimum[1])
    if w >= min_w and h >= min_h:
        x = left + (right - left - w) // 2
        y = top + (bottom - top - h) // 2
        return x, y, x + w, y + h
    w, h = _grown(ratio, (min_w, min_h), frame)
    if w == 0:
        return None
    x = min(max((left + right - w) // 2, 0), frame[0] - w)
    y = min(max((top + bottom - h) // 2, 0), frame[1] - h)
    return x, y, x + w, y + h


def swap_box(box: Box, ratio_swapped: Ratio, *, frame: Size, minimum: Size) -> Box | None:
    """The box turned from landscape to portrait (or back) about its centre, then re-fitted."""
    left, top, right, bottom = box
    width = min(bottom - top, frame[0])
    height = min(right - left, frame[1])
    x = min(max((left + right - width) // 2, 0), frame[0] - width)
    y = min(max((top + bottom - height) // 2, 0), frame[1] - height)
    return fit_centred((x, y, x + width, y + height), ratio_swapped, frame=frame, minimum=minimum)


def _across(v: float, origin: float, painted: float, source: int) -> float:
    clamped = min(max(v, origin), origin + painted)
    return round((clamped - origin) * source / painted, FRAME_MICRO)


def _drag_axis(anchor: float, pointer: float, source: int) -> tuple[int, int, int, int]:
    """(sign, anchor pixel, pointer extent, room from the anchor) along one axis."""
    sign = 1 if pointer >= anchor else -1
    start = math.floor(anchor) if sign > 0 else math.ceil(anchor)
    extent = math.ceil(round(abs(pointer - start), FRAME_MICRO))
    return sign, start, extent, source - start if sign > 0 else start


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
    """A ratio-locked drag: the smallest box of ``ratio`` covering it, anchored at the press."""
    values = (x0, y0, x1, y1, source_width, source_height, painted_width, painted_height)
    if not all(math.isfinite(value) for value in (*values, item_width, item_height)):
        return None
    rw, rh = ratio
    if min(values[4:]) <= 0 or item_width <= 0 or item_height <= 0 or rw <= 0 or rh <= 0:
        return None
    left, top = (item_width - painted_width) / 2, (item_height - painted_height) / 2
    ax, px = (_across(v, left, painted_width, source_width) for v in (x0, x1))
    ay, py = (_across(v, top, painted_height, source_height) for v in (y0, y1))
    sx, start_x, dx, max_w = _drag_axis(ax, px, source_width)
    sy, start_y, dy, max_h = _drag_axis(ay, py, source_height)
    w = min(max(dx, ceil_div(dy * rw, rh)), max_w, (max_h * rw) // rh)
    h = half_up(w * rh, rw)
    if w < max(1, min_width) or h < max(1, min_height):
        return None
    x = start_x if sx > 0 else start_x - w
    y = start_y if sy > 0 else start_y - h
    return x, y, x + w, y + h
