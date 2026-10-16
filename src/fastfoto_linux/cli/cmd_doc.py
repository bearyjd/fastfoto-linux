"""``ffscan doc``: scanned paper documents to one PDF."""

import argparse

from fastfoto_linux.cli.options import common_parent


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "doc",
        parents=[common_parent()],
        help="documents to PDF (preview)",
        description="Make one searchable PDF from scanned document pages.",
    )
    commands = parser.add_subparsers(dest="doc_command", required=True, metavar="DOC_COMMAND")
    process = commands.add_parser("process", parents=[common_parent()], help="PDF from page files")
    process.add_argument("pages", nargs="*")
    for option in ("--out", "--name", "--colour", "--ocr", "--lang", "--dpi"):
        process.add_argument(option)
    for flag in ("--mkdir", "--keep-blank"):
        process.add_argument(flag, action="store_true")
    process.set_defaults(handler=run_process)


def run_process(args: argparse.Namespace) -> int:
    raise NotImplementedError
