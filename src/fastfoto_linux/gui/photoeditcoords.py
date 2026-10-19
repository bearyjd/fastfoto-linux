"""Image-local pointer mapping into canonical full-resolution pixels (RED scaffold)."""


def source_point(  # noqa: PLR0913 - all dimensions belong to one explicit transform
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
    raise NotImplementedError("photo coordinate mapping awaits the recorded RED baseline")


def source_ellipse(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    **geometry: float,
) -> tuple[float, float, float, float] | None:
    raise NotImplementedError("photo ellipse mapping awaits the recorded RED baseline")
