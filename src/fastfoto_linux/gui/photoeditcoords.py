"""Image-local pointer mapping into canonical full-resolution pixels."""

import math


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
