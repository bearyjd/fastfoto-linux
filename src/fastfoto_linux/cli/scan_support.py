"""What ``ffscan scan`` and ``ffscan doc scan`` do the same way: the scanner address, the raw page
policy and the lines a scan says while it runs."""

import argparse
import contextlib
import logging
import os
import sys
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path

from fastfoto_linux.scanner import ScanTarget, default_shim_candidates
from fastfoto_linux.session import RawPolicy, Stage

logger = logging.getLogger(__name__)

CONFIG_DIR_PREFIX = "ffscan-sane-"
WAITING_TEXT = "Waiting for the scanner to answer…"


@contextlib.contextmanager
def scan_target(net_host: str | None, resolve: Callable[..., ScanTarget]) -> Generator[ScanTarget]:
    """The scanner to use, found by ``resolve`` (``resolve_target``, or a test's stand-in).

    With ``net_host`` a private SANE config folder is made for the network address and removed
    again when the scan is over, whatever way it ends.
    """
    with contextlib.ExitStack() as stack:
        config_dir = None
        if net_host is not None:
            private = tempfile.TemporaryDirectory(prefix=CONFIG_DIR_PREFIX)
            config_dir = Path(stack.enter_context(private))
        yield resolve(
            shim_candidates=default_shim_candidates(os.environ),
            net_host=net_host,
            config_dir=config_dir,
        )


def raw_policy(args: argparse.Namespace) -> RawPolicy:
    if args.keep_raw:
        return RawPolicy.KEEP
    return RawPolicy.DISCARD if args.discard_raw else RawPolicy.AUTO


def announce_stage(stage: Stage) -> None:
    """One line when the check waits for a slow scanner, so the wait is not taken for a hang."""
    if stage is Stage.WAITING:
        with contextlib.suppress(OSError):  # a hung-up terminal must not stop the scan
            print(WAITING_TEXT, file=sys.stderr)


def log_page(number: int) -> None:
    logger.info("page %d scanned", number)
