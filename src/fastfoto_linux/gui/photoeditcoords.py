"""Image-local pointer mapping into canonical full-resolution pixels."""

import math


def micro(v: float) -> float:
    """``v`` to six decimals, half up: what the canvas's ``Math.round(v * 1e6) / 1e6`` does."""
    return math.floor(v * 1e6 + 0.5) / 1e6


def source_point(  # noqa: PLR0913 - dimensions describe one explicit transform
    x: float,
    y: float,
    *,
    source_width: int,
    source_height: int,
    painted_width: float,
    painted_height: float,
    item_width: float,
    item_height: float,
) -> tuple[float, float] | None:
    values = (
        x,
        y,
        source_width,
        source_height,
        painted_width,
        painted_height,
        item_width,
        item_height,
    )
    if not all(math.isfinite(value) for value in values):
        return None
    if min(values[2:]) <= 0:
        return None
    left = (item_width - painted_width) / 2
    top = (item_height - painted_height) / 2
    if not left <= x <= left + painted_width or not top <= y <= top + painted_height:
        return None
    return ((x - left) * source_width / painted_width, (y - top) * source_height / painted_height)


def source_ellipse(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    **geometry: float,
) -> tuple[float, float, float, float] | None:
    start = source_point(x0, y0, **geometry)
    end = source_point(x1, y1, **geometry)
    if start is None or end is None:
        return None
    return (
        (start[0] + end[0]) / 2,
        (start[1] + end[1]) / 2,
        abs(end[0] - start[0]) / 2,
        abs(end[1] - start[1]) / 2,
    )


def source_crop(  # noqa: PLR0913 - dimensions describe one explicit transform
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    min_width: int,
    min_height: int,
    source_width: int,
    source_height: int,
    painted_width: float,
    painted_height: float,
    item_width: float,
    item_height: float,
) -> tuple[int, int, int, int] | None:
    """The whole-pixel source rectangle covering a drag, clamped to the painted image."""
    values = (x0, y0, x1, y1, source_width, source_height, painted_width, painted_height)
    if not all(math.isfinite(value) for value in (*values, item_width, item_height)):
        return None
    if min(values[4:]) <= 0 or item_width <= 0 or item_height <= 0:
        return None
    left = (item_width - painted_width) / 2
    top = (item_height - painted_height) / 2

    def across(v: float, origin: float, painted: float, source: int) -> float:
        # Rounding first keeps an exact pixel edge from ceiling up a whole pixel.
        return micro((min(max(v, origin), origin + painted) - origin) * source / painted)

    xs = sorted(across(v, left, painted_width, source_width) for v in (x0, x1))
    ys = sorted(across(v, top, painted_height, source_height) for v in (y0, y1))
    box = (
        math.floor(xs[0]),
        math.floor(ys[0]),
        min(source_width, math.ceil(xs[1])),
        min(source_height, math.ceil(ys[1])),
    )
    if box[2] - box[0] < max(1, min_width) or box[3] - box[1] < max(1, min_height):
        return None
    return box
