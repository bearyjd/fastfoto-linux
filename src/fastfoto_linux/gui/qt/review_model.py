"""Incremental review rows: edit, filter and move without resetting the grid."""

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Slot,
)

from fastfoto_linux.gui.qt.photos_model import file_url
from fastfoto_linux.gui.review import ReviewItem

Index = QModelIndex | QPersistentModelIndex
_FIRST_ROLE = Qt.ItemDataRole.UserRole + 1
_ROLES = (
    "number",
    "orderIndex",
    "thumbUrl",
    "included",
    "turns",
    "flags",
    "flagText",
    "marks",
    "startsPart",
    "part",
    "dropped",
    "colourPolicy",
    "colourMode",
    "colourReason",
    "colourOverride",
    "colourText",
)


def _values(item: ReviewItem) -> dict[str, object]:
    return {
        "number": item.number,
        "orderIndex": item.order_index,
        "thumbUrl": file_url(item.thumb),
        "included": item.included,
        "turns": item.turns,
        "flags": list(item.flags),
        "flagText": item.flag_text,
        "marks": [{"x0": box.x0, "y0": box.y0, "x1": box.x1, "y1": box.y1} for box in item.marks],
        "startsPart": item.starts_part,
        "part": item.part,
        "dropped": item.dropped,
        "colourPolicy": item.colour_policy,
        "colourMode": item.colour_mode,
        "colourReason": item.colour_reason,
        "colourOverride": item.colour_override,
        "colourText": item.colour_text,
    }


class ReviewModel(QAbstractListModel):
    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self._items: list[ReviewItem] = []

    def rowCount(self, parent: Index | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._items)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        name = _ROLES[role - _FIRST_ROLE] if _FIRST_ROLE <= role < _FIRST_ROLE + len(_ROLES) else ""
        return _values(self._items[index.row()]).get(name)

    def roleNames(self) -> dict[int, QByteArray]:
        return {_FIRST_ROLE + i: QByteArray(name.encode()) for i, name in enumerate(_ROLES)}

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, object]:
        return _values(self._items[row]) if 0 <= row < len(self._items) else {}

    def set_items(self, items: tuple[ReviewItem, ...]) -> None:
        wanted = {item.number for item in items}
        for row in range(len(self._items) - 1, -1, -1):
            if self._items[row].number not in wanted:
                self.beginRemoveRows(QModelIndex(), row, row)
                self._items.pop(row)
                self.endRemoveRows()
        for row, item in enumerate(items):
            old = next(
                (i for i, previous in enumerate(self._items) if previous.number == item.number), -1
            )
            if old == -1:
                self.beginInsertRows(QModelIndex(), row, row)
                self._items.insert(row, item)
                self.endInsertRows()
            elif old != row:
                self.beginMoveRows(QModelIndex(), old, old, QModelIndex(), row)
                self._items.insert(row, self._items.pop(old))
                self.endMoveRows()
            if self._items[row] != item:
                self._items[row] = item
                self.dataChanged.emit(
                    self.index(row, 0), self.index(row, 0), list(self.roleNames())
                )
