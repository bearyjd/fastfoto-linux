"""Publish a finished PDF into the output folder without overwriting anything."""

from pathlib import Path

from fastfoto_linux.output.naming import next_index  # noqa: F401


def publish_pdf(data: bytes, directory: Path, name: str) -> Path:
    """Write ``data`` as ``<name>_NNNN.pdf`` in ``directory`` and return its path.

    ``name`` is cleaned like an album name and the number continues after the highest
    ``<name>_NNNN`` of any kind already there. Takes the folder lock only for the numbering and
    the write; never replaces a file.
    """
    raise NotImplementedError
