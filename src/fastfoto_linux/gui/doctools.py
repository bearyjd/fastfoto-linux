"""What the Documents mode needs from the machine, and the seams the tests replace."""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastfoto_linux.documents import DocumentResult, find_ocrmypdf
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.scanner.shim_trust import inside_flatpak
from fastfoto_linux.session import DocumentSessionResult

NATIVE_OCR_HINT = "Install OCRmyPDF: sudo dnf install ocrmypdf tesseract-osd"
FLATPAK_OCR_HINT = "Searchable text needs the native install"


@dataclass(frozen=True)
class DocumentTools:
    """The document session and PDF builder (None: the real ones) and the two questions the form
    asks the machine."""

    session: Callable[..., DocumentSessionResult] | None = None
    build: Callable[..., DocumentResult] | None = None
    find_ocr: Callable[[], str | None] = find_ocrmypdf
    in_flatpak: Callable[[], bool] = inside_flatpak

    @property
    def ocr_available(self) -> bool:
        raise NotImplementedError

    @property
    def ocr_hint(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class DocumentSetup:
    """Everything the page needs for Documents mode beyond the Photos form."""

    form: DocumentForm = field(default_factory=DocumentForm)
    mode: Mode = Mode.PHOTOS
    tools: DocumentTools = field(default_factory=DocumentTools)
    save_form: Callable[[DocumentForm], None] | None = None
    save_mode: Callable[[Mode], None] | None = None
