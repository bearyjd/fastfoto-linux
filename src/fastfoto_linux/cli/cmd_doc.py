"""``ffscan doc``: scanned paper documents to one PDF."""

import argparse
import contextlib
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from fastfoto_linux.cli.cmd_process import existing_pages
from fastfoto_linux.cli.doc_options import (
    add_document_options,
    add_document_scan_options,
    add_fallback_dpi_option,
    add_pairing_option,
    build_settings,
)
from fastfoto_linux.cli.doc_summary import (
    PAGES_SCANNED,
    print_document_summary,
    raw_pages_line,
)
from fastfoto_linux.cli.errors import (
    EXIT_OK,
    EXIT_PROCESSING_ERROR,
    EXIT_TOOL_MISSING,
    EXIT_USAGE,
    CliError,
)
from fastfoto_linux.cli.options import common_parent, prepare_output_root
from fastfoto_linux.cli.scan_support import announce_stage, log_page, raw_policy, scan_target
from fastfoto_linux.documents import (
    DEFAULT_LANGS,
    DEFAULT_NAME,
    AllPagesBlankError,
    ColourMode,
    DocumentSettings,
    DocumentSettingsError,
    OcrMissingError,
    OcrMode,
    OutputFolderMissingError,
    build_document,
    find_ocrmypdf,
)
from fastfoto_linux.documents.ocr import OCR_INSTALL_HINT
from fastfoto_linux.scanner import ScannerError, resolve_target, run_scan
from fastfoto_linux.session import (
    DocumentScanRequest,
    DocumentSessionResult,
    run_document_session,
)


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "doc",
        parents=[common_parent()],
        help="documents to PDF (preview)",
        description="Make one searchable PDF from scanned document pages.",
    )
    commands = parser.add_subparsers(dest="doc_command", required=True, metavar="DOC_COMMAND")
    scan = commands.add_parser(
        "scan",
        parents=[common_parent()],
        help="scan the document feeder into a PDF",
        description="Scan every page in the document feeder (both sides unless --simplex), trim "
        "it, drop blank pages and write one PDF. Always scans in colour; grey and black and "
        "white are made after trimming. Load the pages, then run this.",
    )
    add_document_options(scan)
    add_document_scan_options(scan)
    scan.set_defaults(handler=run_scan_command)
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
    add_fallback_dpi_option(process)
    add_pairing_option(process)
    process.set_defaults(handler=run_process)


def _require_ocr_if_asked(settings: DocumentSettings) -> None:
    if settings.ocr is OcrMode.ON and find_ocrmypdf() is None:
        raise CliError(
            f"--ocr on needs ocrmypdf, which is not installed ({OCR_INSTALL_HINT})",
            EXIT_TOOL_MISSING,
        )


def document_failure(error: Exception) -> Exception:
    """The error to raise for a failed document run: the ones a user can act on become one line."""
    if isinstance(error, AllPagesBlankError):
        return CliError(f"{error}; --keep-blank keeps blank pages", EXIT_PROCESSING_ERROR)
    if isinstance(error, OcrMissingError):  # it vanished between the check and the run
        return CliError(str(error), EXIT_TOOL_MISSING)
    if isinstance(error, OutputFolderMissingError):  # it was there when the options were checked
        return error  # a problem like any other (exit 1), as for ``doc process``
    if isinstance(error, DocumentSettingsError):  # the options were checked
        return CliError(str(error), EXIT_USAGE)
    return error


def _raise_failure(error: Exception) -> NoReturn:
    failure = document_failure(error)
    if failure is error:
        raise error
    raise failure from error


def run_process(args: argparse.Namespace) -> int:
    pages = existing_pages(args.pages)
    settings = build_settings(args)
    _require_ocr_if_asked(settings)
    prepare_output_root(args)
    try:
        result = build_document(pages, settings)
    except (AllPagesBlankError, OcrMissingError) as error:
        _raise_failure(error)
    print_document_summary(result, install_hint=OCR_INSTALL_HINT)
    return EXIT_OK if result.ok else EXIT_PROCESSING_ERROR


def run_scan_command(args: argparse.Namespace) -> int:
    settings = build_settings(args)  # check every option before the scanner is touched
    _require_ocr_if_asked(settings)
    root = prepare_output_root(args)
    with scan_target(args.net, resolve_target) as target:
        request = DocumentScanRequest(
            target=target,
            settings=settings,
            dpi=args.dpi,
            duplex=not args.simplex,
            raw_policy=raw_policy(args),
            raw_parent=root,
        )
        return _scan_into(request, root)


def _scan_into(request: DocumentScanRequest, root: Path) -> int:
    """Run the scan session, say what happened, and map its end to the exit code.

    The session scans into a raw folder, makes the PDF, and deletes the raw pages only if
    nothing was lost; an error or an interrupt comes back in its result, after the raw pages
    are settled, to be raised here once the user has been told where they are.
    """
    try:
        session = run_document_session(
            request,
            on_page=log_page,
            on_stage=announce_stage,
            scan=run_scan,
            build=build_document,
        )
    except (DocumentSettingsError, OcrMissingError) as error:  # refused before any scan
        _raise_failure(error)
    if session.document is not None:
        print_document_summary(
            session.document,
            install_hint=OCR_INSTALL_HINT,
            pages_label=PAGES_SCANNED,
            raw_line=raw_pages_line(session),
        )
    else:  # no summary to say where the pages are: the pages are kept whatever happens
        _report_kept(session, request, root)
    if session.error is not None:
        _raise_failure(session.error)
    if session.cancelled:
        raise KeyboardInterrupt  # an interrupt like Ctrl-C: main() ends it with exit code 130
    return EXIT_OK if session.ok else EXIT_PROCESSING_ERROR


def _pages(count: int) -> str:
    return f"{count} page" if count == 1 else f"{count} pages"


def process_command(pages: Sequence[Path], request: DocumentScanRequest, root: Path) -> str:
    """The ``ffscan doc process`` command that makes the PDF this scan would have made from
    ``pages``: the same folder, resolution and every option that is not the default."""
    settings = request.settings
    options = (
        (settings.colour is not ColourMode.COLOUR, ["--colour", settings.colour.value]),
        (settings.name != DEFAULT_NAME, ["--name", settings.name]),
        (settings.ocr is not OcrMode.AUTO, ["--ocr", settings.ocr.value]),
        (settings.langs != DEFAULT_LANGS, ["--lang", settings.langs]),
        (settings.keep_blank, ["--keep-blank"]),
    )
    return shlex.join(
        [
            "ffscan",
            "doc",
            "process",
            *map(str, pages),
            "--out",
            str(root),
            "--dpi",
            str(request.dpi),
            *(word for wanted, words in options if wanted for word in words),
        ]
    )


def _report_kept(session: DocumentSessionResult, request: DocumentScanRequest, root: Path) -> None:
    """Say on stderr where the raw pages are when there is no PDF; after a scanner failure that
    left pages, also the exact command that makes a PDF from the finished ones. A terminal that
    has hung up (EIO) must not replace the interrupt or error that is on its way."""
    kept = session.raw_dir
    if kept is None:
        return
    with contextlib.suppress(OSError):
        print(f"ffscan: raw pages kept in {kept}", file=sys.stderr)
        if isinstance(session.error, ScannerError) and session.kept_pages:
            print(
                f"ffscan: no PDF is made from part of a stack; to make one from the "
                f"{_pages(len(session.kept_pages))} scanned, run:",
                file=sys.stderr,
            )
            print(process_command(session.kept_pages, request, root), file=sys.stderr)
