"""Crop shape actions for the Qt-free photo editor (stub)."""


class PhotoAspectActions:
    """Mixin for ``PhotoEditSide``: the crop shape lock lives here, never in the page."""

    _aspect_preset = "free"
    _aspect_portrait = False
    _aspect_geometry = None

    def set_crop_aspect(self, preset_id: str) -> None:
        raise NotImplementedError

    def swap_crop_aspect(self) -> None:
        raise NotImplementedError

    def set_aspect_crop(self, left: int, top: int, right: int, bottom: int) -> None:
        raise NotImplementedError

    @property
    def crop_aspect(self) -> str:
        raise NotImplementedError

    @property
    def aspect_portrait(self) -> bool:
        raise NotImplementedError

    @property
    def crop_ratio(self) -> tuple[int, int] | None:
        raise NotImplementedError

    @property
    def can_swap_aspect(self) -> bool:
        raise NotImplementedError
