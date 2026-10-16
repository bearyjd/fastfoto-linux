"""Put encoded pages into one PDF without re-encoding them.

``img2pdf`` embeds a JPEG as DCTDecode and a CCITT G4 TIFF as CCITTFaxDecode exactly as they
are, and sizes every page from the resolution stored in its image.
"""

from collections.abc import Sequence
from datetime import datetime

import img2pdf

from fastfoto_linux.documents.encode import EncodedPage
from fastfoto_linux.documents.errors import DocumentError

PRODUCER = "fastfoto-linux"


def assemble_pdf(pages: Sequence[EncodedPage], *, title: str, created: datetime) -> bytes:
    """One PDF with a page per ``EncodedPage``, each sized from its pixels and resolution.

    The JPEG or CCITT data is embedded as it is. Metadata: ``title``, ``created`` (also the
    modification date) and producer ``fastfoto-linux``. ``created`` must carry a time zone.
    """
    if not pages:
        raise DocumentError("no pages to put in a PDF")
    return img2pdf.convert(
        *(page.data for page in pages),
        title=title,
        producer=PRODUCER,
        creationdate=created,
        moddate=created,
    )
