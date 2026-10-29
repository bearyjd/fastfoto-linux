"""The straighten child of the review view: thin properties and slots over ``ReviewDeskew``."""

from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, Signal, Slot

if TYPE_CHECKING:
    from fastfoto_linux.gui.qt.review_view import ReviewView
    from fastfoto_linux.gui.reviewdeskew import ReviewDeskew


class ReviewDeskewView(QObject):
    changed = Signal()

    def __init__(self, parent: "ReviewView") -> None:
        super().__init__(parent)
        self._view = parent

    @property
    def _deskew(self) -> "ReviewDeskew":
        return self._view._side.deskew

    @Property(bool, notify=changed)
    def canStraighten(self) -> bool:
        return self._deskew.can_straighten

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._deskew.pending is not None

    @Property(str, notify=changed)
    def message(self) -> str:
        state = self._view._side.state
        return self._deskew.message_text(state.focus) if state else ""

    @Slot(int)
    def straightenPage(self, number: int) -> None:
        self._view._call(self._whole, self._deskew.straighten, number)

    @Slot(int)
    def clearStraighten(self, number: int) -> None:
        self._view._call(self._whole, self._deskew.clear, number)

    @staticmethod
    def _whole(action: object, number: object) -> None:
        if type(number) is not int:
            raise ValueError("choose a page by its number")
        action(number)  # type: ignore[operator]
