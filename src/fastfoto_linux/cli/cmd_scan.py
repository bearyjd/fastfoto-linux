"""``ffscan scan``: scan the document feeder, then process the pages."""

import argparse
import contextlib
import sys
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_OK, EXIT_PROCESSING_ERROR
from fastfoto_linux.cli.options import (
    add_output_options,
    add_scan_options,
    build_settings,
    common_parent,
    prepare_output_root,
)
from fastfoto_linux.cli.scan_support import announce_stage, log_page, raw_policy, scan_target
from fastfoto_linux.cli.summary import print_summary
from fastfoto_linux.pipeline.process import ProcessSettings, process_pages
from fastfoto_linux.scanner import ScanTarget, resolve_target, run_scan
from fastfoto_linux.session import RawReason, ScanRequest, SessionResult, run_session

# Under the names this module has always had them: tests call and replace these here.
_raw_policy = raw_policy
_announce_stage = announce_stage
_log_page = log_page


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
    with scan_target(args.net, resolve_target) as target:
        return _scan_into(root, target, settings, args)


def _scan_into(
    root: Path, target: ScanTarget, settings: ProcessSettings, args: argparse.Namespace
) -> int:
    """Run the scan session, say what happened, and map its end to the exit code.

    The session scans into a raw folder, processes it, and deletes the raw pages only if
    nothing was lost; an error or an interrupt comes back in its result, after the raw pages
    are settled, to be raised here once the user has been told where they are.
    """
    request = ScanRequest(
        target=target,
        dpi=args.dpi,
        duplex=not args.simplex,
        settings=settings,
        raw_policy=_raw_policy(args),
        raw_parent=root,
    )
    session = run_session(
        request, on_page=_log_page, on_stage=_announce_stage, scan=run_scan, process=process_pages
    )
    try:
        if session.process is not None:
            print_summary(session.process)
    finally:  # the pages are kept whatever happens: say where, even if the summary fails
        _report_kept(session)
    if session.error is not None:
        raise session.error
    if session.cancelled:
        raise KeyboardInterrupt  # an interrupt like Ctrl-C: main() ends it with exit code 130
    return EXIT_OK if session.ok else EXIT_PROCESSING_ERROR


def _report_kept(session: SessionResult) -> None:
    """Say where the raw pages are: on stdout when it was planned, on stderr when it was not.

    A dropped back is the one reason nobody asked for them, so the user is told how to get rid
    of them. A terminal that has hung up (EIO) must not replace the interrupt or error that is
    on its way.
    """
    kept = session.raw_dir
    if kept is None:
        return
    calm = session.ok
    with contextlib.suppress(OSError):
        if calm and session.raw_reason is RawReason.BACK_DROPPED:
            print(
                f"raw pages kept in {kept} (a back was dropped); "
                "--discard-raw deletes them after a clean run"
            )
            print("  raw PNGs use disk space; delete that folder once the photos look right")
        elif calm:
            print(f"raw pages kept in: {kept}")
        else:
            print(f"ffscan: raw pages kept in {kept}", file=sys.stderr)
