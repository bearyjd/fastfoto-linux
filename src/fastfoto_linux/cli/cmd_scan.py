"""``ffscan scan``: scan the document feeder, then process the pages."""

import argparse
import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_OK, EXIT_PROCESSING_ERROR
from fastfoto_linux.cli.options import (
    add_output_options,
    add_scan_options,
    build_settings,
    common_parent,
    prepare_output_root,
)
from fastfoto_linux.cli.rawdir import create_raw_dir, settle_raw_dir
from fastfoto_linux.cli.summary import print_summary
from fastfoto_linux.pipeline.process import ProcessResult, ProcessSettings, process_pages
from fastfoto_linux.scanner import (
    ScanError,
    ScanJob,
    ScanTarget,
    Source,
    default_shim_candidates,
    resolve_target,
    run_scan,
)

logger = logging.getLogger(__name__)

CONFIG_DIR_PREFIX = "ffscan-sane-"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "scan",
        parents=[common_parent()],
        help="scan the document feeder and process the pages",
        description="Scan every photo in the document feeder (both sides unless --simplex) and "
        "write them as album photos. Load the photos, then run this.",
    )
    add_output_options(parser)
    add_scan_options(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    settings = build_settings(args)  # check every option before the scanner is touched
    root = prepare_output_root(args)
    with contextlib.ExitStack() as stack:
        config_dir = None
        if args.net is not None:  # a private SANE config dir, removed again when the scan is over
            private = tempfile.TemporaryDirectory(prefix=CONFIG_DIR_PREFIX)
            config_dir = Path(stack.enter_context(private))
        target = resolve_target(
            shim_candidates=default_shim_candidates(os.environ),
            net_host=args.net,
            config_dir=config_dir,
        )
        return _scan_into(root, target, settings, args)


def _scan_into(
    root: Path, target: ScanTarget, settings: ProcessSettings, args: argparse.Namespace
) -> int:
    """Scan into a raw folder, process it, and delete the raw pages only if nothing was lost."""
    raw = create_raw_dir(root, keep=args.keep_raw)
    result: ProcessResult | None = None
    scan_error: ScanError | None = None
    exit_code = EXIT_PROCESSING_ERROR
    try:
        pages, scan_error = _scan(raw, target, simplex=args.simplex, dpi=args.dpi)
        result = process_pages(pages, settings)
        print_summary(result, can_keep_raw=True)
        exit_code = EXIT_OK if result.ok else EXIT_PROCESSING_ERROR
    finally:  # also for Ctrl-C and a crash: a scanned page cannot be had again without a rescan
        calm = scan_error is None and result is not None and result.ok
        kept = settle_raw_dir(raw, root, keep=_keep_raw(args, result, scan_error))
        _report_kept(kept, calm=calm)
    if scan_error is not None:
        raise scan_error
    return exit_code


def _keep_raw(
    args: argparse.Namespace, result: ProcessResult | None, scan_error: ScanError | None
) -> bool:
    """Whether the raw pages stay: always unless the run was clean (no ``result`` means it ended
    early, by an interrupt or an error).

    A clean run that dropped a back for lack of writing keeps them too, so that a back with
    faint writing is never lost for good; ``--discard-raw`` opts out of that one reason.
    """
    if args.keep_raw or scan_error is not None or result is None or not result.ok:
        return True
    return result.backs_dropped > 0 and not args.discard_raw


def _report_kept(kept: Path | None, *, calm: bool) -> None:
    """Say where the raw pages are: on stdout when it was planned, on stderr when it was not."""
    if kept is None:
        return
    if calm:
        print(f"raw pages kept in: {kept}")
    else:
        print(f"ffscan: raw pages kept in {kept}", file=sys.stderr)


def _scan(
    raw: Path, target: ScanTarget, *, simplex: bool, dpi: int
) -> tuple[tuple[Path, ...], ScanError | None]:
    """Run the scan. A scanner failure part-way keeps the pages finished before it."""
    job = ScanJob(
        device=target.device,
        output_dir=raw,
        source=Source.FRONT if simplex else Source.DUPLEX,
        resolution=dpi,
    )
    try:
        return run_scan(job, env=target.env(os.environ), on_progress=_log_page).pages, None
    except ScanError as error:
        if not error.pages:
            raise
        logger.error("the scan stopped early; processing the %d finished pages", len(error.pages))
        return error.pages, error


def _log_page(number: int) -> None:
    logger.info("page %d scanned", number)
