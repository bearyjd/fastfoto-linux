"""Qt properties for explicit scanner power reads and local drafts."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, Signal, Slot

from fastfoto_linux.gui.power import RESTART_MESSAGE
from fastfoto_linux.gui.state import ActionBlockedError

if TYPE_CHECKING:
    from fastfoto_linux.gui.qt.bridge import Bridge


class PowerView(QObject):
    changed = Signal()

    def __init__(self, bridge: "Bridge") -> None:
        super().__init__(bridge)
        self._settings = bridge.controller.power
        self._controller = bridge.controller

    def refresh(self) -> None:
        self.changed.emit()

    @Property(bool, notify=changed)
    def loaded(self) -> bool:
        return self._settings.snapshot is not None

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._settings.pending

    @Property(bool, notify=changed)
    def canRead(self) -> bool:
        return self._settings.can_read

    @Property(bool, notify=changed)
    def canApply(self) -> bool:
        return self._settings.can_apply

    @Property(bool, notify=changed)
    def reconnectRequired(self) -> bool:
        return self._settings.reconnect_required

    @Property(bool, notify=changed)
    def canCheckConnection(self) -> bool:
        return self.reconnectRequired and self._settings.available

    @Property(str, notify=changed)
    def message(self) -> str:
        if self.reconnectRequired and RESTART_MESSAGE not in self._settings.message:
            return self._settings.recovery_message
        return self._settings.message

    @Property(str, notify=changed)
    def targetLabel(self) -> str:
        target = self._settings.target
        return f"FF-680W · USB {target.bus}:{target.device}" if target else "FF-680W · USB"

    @Property(str, notify=changed)
    def sleepCurrent(self) -> str:
        return self._current("sleep_minutes")

    @Property(str, notify=changed)
    def powerOffCurrent(self) -> str:
        return self._current("power_off_minutes")

    @Property(int, notify=changed)
    def sleepDraft(self) -> int:
        return self._settings.drafts.get("sleep_minutes", -1)

    @Property(int, notify=changed)
    def powerOffDraft(self) -> int:
        return self._settings.drafts.get("power_off_minutes", -1)

    @Property("QVariantList", notify=changed)
    def sleepChoices(self) -> list[dict[str, object]]:
        return self._choices("sleep_minutes")

    @Property("QVariantList", notify=changed)
    def powerOffChoices(self) -> list[dict[str, object]]:
        return self._choices("power_off_minutes")

    def _current(self, name: str) -> str:
        snapshot = self._settings.snapshot
        if snapshot is None:
            return "Not read"
        if self._settings.capability(name) is None:
            return "Unsupported"
        value = getattr(snapshot, name)
        if value is None:
            return "Unavailable"
        return "Off" if value == 0 else f"{value} minutes"

    def _choices(self, name: str) -> list[dict[str, object]]:
        capability = self._settings.capability(name)
        if capability is None or name not in self._settings.drafts:
            return []
        values = capability.values
        if not values and capability.minimum is not None and capability.maximum is not None:
            values = tuple(range(capability.minimum, capability.maximum + 1, capability.step))
        return [
            {"label": "Off" if value == 0 else f"{value} minutes", "value": value}
            for value in values
            if capability.accepts(value)
        ]

    def _call(self, action: Callable[[], None]) -> None:
        try:
            action()
        except ActionBlockedError as error:
            self._settings.message = str(error)
            self._controller._changed()

    @Slot()
    def read(self) -> None:
        self._call(self._settings.read)

    @Slot()
    def apply(self) -> None:
        self._call(self._settings.apply)

    @Slot(str, int)
    def setValue(self, name: str, value: int) -> None:
        self._call(lambda: self._settings.set_value(name, value))

    @Slot()
    def checkConnection(self) -> None:
        self._call(self._settings.check_connection)
