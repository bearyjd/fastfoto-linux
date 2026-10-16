"""``ffscan doc``: scanned paper documents to one PDF."""

import argparse
from pathlib import Path

from fastfoto_linux.cli.cmd_process import existing_pages
from fastfoto_linux.cli.doc_options import add_document_options, build_settings
from fastfoto_linux.cli.doc_summary import print_document_summary
from fastfoto_linux.cli.errors import (
    EXIT_OK,
    EXIT_PROCESSING_ERROR,
    EXIT_TOOL_MISSING,
    CliError,
)
from fastfoto_linux.cli.options import common_parent, prepare_output_root
from fastfoto_linux.documents import (
    AllPagesBlankError,
    DocumentSettings,
    OcrMissingError,
    OcrMode,
    build_document,
    find_ocrmypdf,
)
from fastfoto_linux.scanner import resolve_target, run_scan  # noqa: F401 - used by doc scan

OCR_INSTALL_HINT = (
    "sudo dnf install ocrmypdf tesseract-osd"  # OSD data is what --rotate-pages needs
)


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "doc",
        parents=[common_parent()],
        help="documents to PDF (preview)",
        description="Make one searchable PDF from scanned document pages.",
    )
    commands = parser.add_subparsers(dest="doc_command", required=True, metavar="DOC_COMMAND")
    process = commands.add_parser(
        "process",
        parents=[common_parent()],
        help="make a PDF from pages scanned earlier",
        description="Trim, drop blank pages, and write raw scanner pages (PNG) as one PDF. "
        "Pages are taken in natural filename order (page-2 before page-10) and counted from 1 in "
        "that order. The page files are never changed or deleted.",
    )
    process.add_argument("pages", nargs="+", type=Path, metavar="PAGE.png", help="raw page files")
    add_document_options(process)
    process.set_defaults(handler=run_process)


def _require_ocr_if_asked(settings: DocumentSettings) -> None:
    if settings.ocr is OcrMode.ON and find_ocrmypdf() is None:
        raise CliError(
            f"--ocr on needs ocrmypdf, which is not installed ({OCR_INSTALL_HINT})",
            EXIT_TOOL_MISSING,
        )


def run_process(args: argparse.Namespace) -> int:
    pages = existing_pages(args.pages)
    settings = build_settings(args)
    _require_ocr_if_asked(settings)
    prepare_output_root(args)
    try:
        result = build_document(pages, settings)
    except AllPagesBlankError as error:
        raise CliError(f"{error}; --keep-blank keeps blank pages", EXIT_PROCESSING_ERROR) from error
    except OcrMissingError as error:  # it vanished between the check and the run
        raise CliError(str(error), EXIT_TOOL_MISSING) from error
    print_document_summary(result, install_hint=OCR_INSTALL_HINT)
    return EXIT_OK if result.ok else EXIT_PROCESSING_ERROR
