"""What the Documents mode needs from the machine, and the seams the tests replace."""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastfoto_linux.documents import DocumentResult, find_ocrmypdf
from fastfoto_linux.documents.ocr_tools import (
    DNF_INSTALL_HINT,
    FLATPAK_BROKEN_HINT,
    TESSERACT_NAME,
    ocr_fixes,
)
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.scanner.shim_trust import inside_flatpak
from fastfoto_linux.session import DocumentSessionResult

NATIVE_OCR_HINT = f"Install {TESSERACT_NAME}: {DNF_INSTALL_HINT}"  # classic system, only it missing
FLATPAK_OCR_HINT = FLATPAK_BROKEN_HINT  # the Flatpak brings OCR; missing means a broken bundle


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
        """True when OCR is available, OCRmyPDF and Tesseract both (looked up each time)."""
        return self.find_ocr() is not None

    @property
    def ocr_hint(self) -> str:
        """What to do about missing searchable text, empty when it is available."""
        if self.ocr_available:
            return ""
        if self.in_flatpak():
            return FLATPAK_OCR_HINT
        return "; ".join(f"Install {name}: {fix}" for name, fix in ocr_fixes())


@dataclass(frozen=True)
class DocumentSetup:
    """Everything the page needs for Documents mode beyond the Photos form."""

    form: DocumentForm = field(default_factory=DocumentForm)
    mode: Mode = Mode.PHOTOS
    tools: DocumentTools = field(default_factory=DocumentTools)
    save_form: Callable[[DocumentForm], None] | None = None
    save_mode: Callable[[Mode], None] | None = None
