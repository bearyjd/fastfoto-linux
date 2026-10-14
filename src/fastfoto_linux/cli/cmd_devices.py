"""``ffscan devices``: what the transport would use to reach a scanner (reads sysfs only)."""

import argparse
import os

from fastfoto_linux.cli.errors import EXIT_OK, EXIT_SCANNER, CliError
from fastfoto_linux.cli.options import common_parent, host
from fastfoto_linux.scanner import default_shim_candidates, find_usb_scanners, sane_net_device_name
from fastfoto_linux.scanner.target import SHIM_BUILD_COMMAND, SHIM_ENV_VAR


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "devices",
        parents=[common_parent()],
        help="list the scanners that can be reached",
        description="List the FF-680W scanners on USB and whether the USB gap shim is found. "
        "Nothing is sent to the scanner.",
    )
    parser.add_argument("--net", type=host, metavar="HOST", help="also list a Wi-Fi scanner")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    scanners = find_usb_scanners()
    shim = next((path for path in default_shim_candidates(os.environ) if path.is_file()), None)
    print(f"USB scanners: {len(scanners)}")
    for scanner in scanners:
        print(f"  {scanner.sane_usb_device_name()}")
    if shim is not None:
        print(f"USB gap shim: found ({shim})")
    else:
        print(f"USB gap shim: missing (build it with `{SHIM_BUILD_COMMAND}`)")
    if args.net is not None:
        print(f"Network scanner: {sane_net_device_name(args.net)}")
        return EXIT_OK
    if not scanners:
        raise CliError(
            "no FF-680W found on USB; check the cable and the power switch, or use --net HOST",
            EXIT_SCANNER,
        )
    if shim is None:
        raise CliError(
            f"the USB gap shim is missing, USB I/O fails without it; build it with "
            f"`{SHIM_BUILD_COMMAND}` or set ${SHIM_ENV_VAR}",
            EXIT_SCANNER,
        )
    return EXIT_OK
