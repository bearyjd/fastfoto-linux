"""Put encoded pages into one PDF without re-encoding them."""

from collections.abc import Sequence
from datetime import datetime

from fastfoto_linux.documents.encode import EncodedPage

PRODUCER = "fastfoto-linux"


def assemble_pdf(pages: Sequence[EncodedPage], *, title: str, created: datetime) -> bytes:
    """One PDF with a page per ``EncodedPage``, each sized from its pixels and resolution.

    The JPEG or CCITT data is embedded as it is. Metadata: ``title``, ``created`` (also the
    modification date) and producer ``fastfoto-linux``. ``created`` must carry a time zone.
    """
    raise NotImplementedError
