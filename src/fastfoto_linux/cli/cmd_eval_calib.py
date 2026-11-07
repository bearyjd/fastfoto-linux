"""``ffscan eval deskew|autocolour|wb|detail``: the calibration harnesses on a corpus manifest."""

import argparse
import os
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_GATE_FAILED, EXIT_OK, EXIT_USAGE, CliError
from fastfoto_linux.cli.options import common_parent
from fastfoto_linux.evaluation.calib_detail import DEFAULT_STRENGTH, Strengths
from fastfoto_linux.evaluation.calib_run import (
    FEATURES,
    check_pin,
    check_request,
    resolve_out,
    run_calibration,
    write_report,
)
from fastfoto_linux.evaluation.corpus_manifest import SPLITS, load_corpus_manifest
from fastfoto_linux.evaluation.corpus_storage import manifest_path
from fastfoto_linux.evaluation.corpus_types import CorpusError
from fastfoto_linux.evaluation.redeye_manifest import ManifestError

HELP = {
    "deskew": "measure the page skew estimate against annotated corrections",
    "autocolour": "measure the automatic colour mode against annotated labels",
    "wb": "measure neutral-patch colour error under each white balance setting",
    "detail": "measure noise reduction and sharpening on annotated patches and edges",
}


def add_parsers(kinds: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    for feature in FEATURES:
        parser = kinds.add_parser(
            feature,
            parents=[common_parent()],
            help=HELP[feature],
            description=f"{HELP[feature].capitalize()}. Reads only the corpus manifest and the "
            "files it names, and writes a metrics-only report.json into a new run-... directory "
            "under --out (outside the corpus). See docs/design/calibration-harness.md.",
        )
        parser.add_argument("--corpus", type=Path, metavar="DIR", help="corpus directory")
        parser.add_argument("--out", type=Path, metavar="DIR", help="results directory")
        parser.add_argument("--split", choices=SPLITS, default="tuning", help="split to report")
        parser.add_argument("--expect-manifest-sha256", metavar="HEX", help="pin the manifest")
        parser.add_argument("--gate", action="store_true", help="exit 5 unless every gate passes")
        if feature == "detail":
            for name in ("denoise-luma", "denoise-chroma", "sharpen"):
                parser.add_argument(
                    f"--{name}", type=int, default=DEFAULT_STRENGTH, metavar="0-100",
                    help=f"{name} strength to evaluate",
                )  # fmt: skip
        parser.set_defaults(handler=run, feature=feature)


def _settings(args: argparse.Namespace) -> Strengths | None:
    if args.feature != "detail":
        return None
    return Strengths(args.denoise_luma, args.denoise_chroma, args.sharpen)


def run(args: argparse.Namespace) -> int:
    try:
        check_request(args.split, args.expect_manifest_sha256, args.gate)
        settings = _settings(args)
        with load_corpus_manifest(manifest_path(args.corpus, os.environ)) as manifest:
            check_pin(manifest, args.expect_manifest_sha256)
            out_dir = resolve_out(args.feature, manifest, args.out, os.environ)
            result = run_calibration(
                manifest, args.feature, args.split, args.expect_manifest_sha256, settings
            )
            run_dir = write_report(manifest, out_dir, result.report)
    except (CorpusError, ManifestError, ValueError) as error:
        raise CliError(str(error), EXIT_USAGE) from error
    print(f"results: {run_dir}")
    print(f"{result.errored} item(s) errored")
    if not args.gate:
        return EXIT_OK
    if not result.failures:
        print("GATE PASS")
        return EXIT_OK
    print("GATE FAIL")
    for failure in result.failures:
        print(f"  {failure}")
    return EXIT_GATE_FAILED
