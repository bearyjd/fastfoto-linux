"""Shared by the ``ffscan doc scan`` tests."""

from pathlib import Path

from fastfoto_linux.cli import main

STAMP = "20261013T230000Z"
OFF = ["--ocr", "off"]
HINT = "sudo dnf install tesseract tesseract-osd"


def doc_scan(out: Path, *extra: str) -> int:
    """``ffscan doc scan`` without searchable text unless the test asks for it."""
    ocr = [] if "--ocr" in extra else OFF
    return main(["doc", "scan", "--out", str(out), *ocr, *extra])


def visible(folder: Path) -> list[str]:
    """The files a user sees in ``folder``."""
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def kept(out: Path) -> Path:
    return out / ".raw" / STAMP


def kept_pages(out: Path) -> list[str]:
    return sorted(p.name for p in kept(out).iterdir()) if kept(out).is_dir() else []
