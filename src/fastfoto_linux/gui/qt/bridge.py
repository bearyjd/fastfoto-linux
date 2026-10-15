"""The object QML talks to: the controller's properties and slots, on the GUI thread."""

from PySide6.QtCore import QObject

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.worker import DiscoverFn, ProcessFn, SessionFn


class Bridge(QObject):
    def __init__(
        self,
        *,
        form: ScanForm | None = None,
        remember: bool = True,
        discover: DiscoverFn | None = None,
        session: SessionFn | None = None,
        process: ProcessFn | None = None,
    ) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        raise NotImplementedError
