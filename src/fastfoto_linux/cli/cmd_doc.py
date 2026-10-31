"""``ffscan doc``: scanned paper documents to one PDF."""

import argparse
import contextlib
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

from fastfoto_linux.cli.cmd_process import existing_pages
from fastfoto_linux.cli.doc_dry_run import dry_run_lines
from fastfoto_linux.cli.doc_edit_options import add_edit_options, edits_from_args
from fastfoto_linux.cli.doc_options import (
    add_document_options,
    add_document_scan_options,
    add_fallback_dpi_option,
    add_pairing_option,
    build_settings,
)
from fastfoto_linux.cli.doc_rawdir import folder_pages, raw_folder
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
    CleanupPolicy,
    ColourMode,
    DocumentSettings,
    DocumentSettingsError,
    NothingSelectedError,
    OcrMissingError,
    OcrMode,
    OutputFolderMissingError,
    build_document,
    find_ocrmypdf,
)
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.auto_colour import page_colour
from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.deskew_draft import estimate_deskew
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import (
    PageEdits,
    parts,
    set_deskew,
    set_document_cleanup,
    set_document_despeckle,
    with_edits,
)
from fastfoto_linux.documents.draft_store import open_draft
from fastfoto_linux.documents.errors import DocumentEditError, UnsupportedPageError
from fastfoto_linux.documents.ocr_tools import ocr_fix_hint
from fastfoto_linux.documents.write import DocumentResult, write_document
from fastfoto_linux.scanner import ScannerError, resolve_target, run_scan
from fastfoto_linux.scanner.shim_trust import inside_flatpak
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
        "that order. Unless --simplex they are paired as the two sides of sheets, 1+2, 3+4 and so "
        "on, so they must start with a front. The page files are never changed or deleted. "
        "--drop, --keep, --rotate, --split, --order and --part-name change what the PDFs hold "
        "(see their help); --dry-run shows what would happen and writes nothing.",
    )
    process.add_argument(
        "pages",
        nargs="+",
        type=Path,
        metavar="PAGE.png|RAWDIR",
        help="raw page files, or one raw folder (.raw/<time>/) with the edits saved in its "
        "review.json; the command never writes into it",
    )
    add_document_options(process)
    add_fallback_dpi_option(process)
    add_pairing_option(process)
    add_edit_options(process)
    process.set_defaults(handler=run_process)


def _ocr_missing_message() -> str:
    hint = ocr_fix_hint()
    if inside_flatpak():  # the hint is a sentence about the bundle: it leads, as one
        return f"{hint} (--ocr on needs OCR)"
    return f"--ocr on needs OCR (ocrmypdf and Tesseract), which is not available ({hint})"


def _require_ocr_if_asked(settings: DocumentSettings) -> None:
    if settings.ocr is OcrMode.ON and find_ocrmypdf() is None:
        raise CliError(_ocr_missing_message(), EXIT_TOOL_MISSING)


def document_failure(error: Exception) -> Exception:
    """The error to raise for a failed document run: the ones a user can act on become one line."""
    if isinstance(error, AllPagesBlankError):
        return CliError(f"{error}; --keep-blank keeps blank pages", EXIT_PROCESSING_ERROR)
    if isinstance(error, NothingSelectedError):
        return CliError(f"{error}; --keep brings back a page", EXIT_PROCESSING_ERROR)
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


def _apply_edits(draft: DocumentDraft, edits: PageEdits) -> DocumentDraft:
    """``draft`` with the edits made. An edit that cannot be made is a usage error."""
    try:
        return with_edits(draft, edits)
    except DocumentEditError as error:
        raise CliError(str(error), EXIT_USAGE) from error


def _edited(
    draft: DocumentDraft,
    settings: DocumentSettings,
    *,
    dry_run: bool,
    notes: Mapping[int, str] | None = None,
) -> DocumentResult | None:
    """Write the PDFs of the edited draft (None for a dry run, which prints what would happen
    instead). The pages that stay are settled first, so ``--deskew`` measures the right ones."""
    if dry_run:
        print("\n".join(dry_run_lines(draft, settings.colour, notes)))
        return None
    if draft.raw_dir is None and any(
        page.encoded is None or turns for part in parts(draft) for page, turns in part.pages
    ):
        raise CliError(  # a page to turn or bring back is read again from its file
            "--rotate and --keep need the pages in one folder, which these are not",
            EXIT_USAGE,
        )
    if draft.raw_dir is None and any(
        page.encoded is not None
        and page_colour(draft, page, settings.colour) is not page.encoded.mode
        for part in parts(draft)
        for page, _turns in part.pages
    ):
        raise CliError(
            "--page-colour changes need the original pages in one folder; "
            "these inputs are from different folders",
            EXIT_USAGE,
        )
    return write_document(draft, settings)


def _with_cleanup(draft: DocumentDraft, args: argparse.Namespace) -> DocumentDraft:
    """``draft`` at the paper cleanup level ``--cleanup`` names (the draft as it is when the
    option is not given). A page's own level in the review file still wins over it. Nothing is
    saved: the command never writes the review file."""
    if args.cleanup is None:
        return draft
    try:
        return set_document_cleanup(draft, CleanupPolicy(args.cleanup))
    except DocumentEditError as error:
        raise CliError(str(error), EXIT_USAGE) from error


def _with_despeckle(draft: DocumentDraft, args: argparse.Namespace) -> DocumentDraft:
    """``draft`` with the despeckle switch ``--despeckle`` or ``--no-despeckle`` names (the draft
    as it is when neither is given). Nothing is saved."""
    if args.despeckle is None:
        return draft
    try:
        return set_document_despeckle(draft, args.despeckle)
    except DocumentEditError as error:
        raise CliError(str(error), EXIT_USAGE) from error


def _with_deskew(
    draft: DocumentDraft, args: argparse.Namespace
) -> tuple[DocumentDraft, Mapping[int, str]]:
    """``draft`` with the angles ``--deskew`` or ``--no-deskew`` names (the draft as it is when
    neither is given), and a dry-run note for each page that was looked at and not turned, or
    that lost its crop. ``--deskew`` measures the pages with no angle and no crop; ``--no-deskew``
    clears every angle, and with it the crop of a page that had both. Nothing is saved."""
    if args.deskew is None:
        return draft, {}
    notes: dict[int, str] = {}
    try:
        if args.deskew:
            measured, statuses = estimate_deskew(draft)
            notes = {
                number: f"deskew skipped ({status.value})"
                for number, status in statuses.items()
                if status is not SkewStatus.ESTIMATED
            }
            return measured, notes
        for number, edit in draft.edits.items():
            if edit.deskew_tenths is not None:
                if edit.crop is not None:
                    notes[number] = "crop removed"
                draft = set_deskew(draft, number, None)
    except (DocumentEditError, UnsupportedPageError, ValueError) as error:
        raise CliError(str(error), EXIT_USAGE) from error
    return draft, notes


def _process_pages(args: argparse.Namespace) -> tuple[Path | None, list[Path]]:
    """The raw folder, if the input is one, and the pages to process."""
    folder = raw_folder(args.pages)
    if folder is None and args.fresh:
        raise CliError("--fresh applies to a raw folder, which was not given", EXIT_USAGE)
    return folder, folder_pages(folder) if folder is not None else existing_pages(args.pages)


def run_process(args: argparse.Namespace) -> int:
    folder, pages = _process_pages(args)
    settings = build_settings(args)
    edits = edits_from_args(args, len(pages))
    _require_ocr_if_asked(settings)
    if args.dry_run:  # nothing is made, not even the folder
        if not args.out.is_dir():
            raise CliError(f"--dry-run needs the output folder {args.out}", EXIT_USAGE)
    else:
        prepare_output_root(args)
    try:
        if folder is not None:
            opened = open_draft(folder, pages, settings, fresh=args.fresh)
            draft = _apply_edits(_with_despeckle(_with_cleanup(opened, args), args), edits)
            draft, notes = _with_deskew(draft, args)
            result: DocumentResult | None = _edited(
                draft, settings, dry_run=args.dry_run, notes=notes
            )
        elif edits == PageEdits() and not args.dry_run:
            result = build_document(pages, settings)
        else:
            draft, notes = _with_deskew(
                _apply_edits(analyse_document(pages, settings), edits), args
            )
            result = _edited(draft, settings, dry_run=args.dry_run, notes=notes)
    except (AllPagesBlankError, NothingSelectedError, OcrMissingError) as error:
        _raise_failure(error)
    if result is None:
        return EXIT_OK
    print_document_summary(result, install_hint=ocr_fix_hint())
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
            duplex=settings.duplex,
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
            install_hint=ocr_fix_hint(),
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
        (settings.colour != ColourMode.COLOUR, ["--colour", settings.colour.value]),
        (settings.cleanup is not CleanupPolicy.OFF, ["--cleanup", settings.cleanup.value]),
        (settings.despeckle, ["--despeckle"]),
        (settings.deskew, ["--deskew"]),
        (settings.preset is not None, ["--preset", str(settings.preset)]),
        (settings.name != DEFAULT_NAME, ["--name", settings.name]),
        (settings.ocr is not OcrMode.AUTO, ["--ocr", settings.ocr.value]),
        (settings.langs != DEFAULT_LANGS, ["--lang", settings.langs]),
        (settings.keep_blank, ["--keep-blank"]),
        (not settings.duplex, ["--simplex"]),
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
