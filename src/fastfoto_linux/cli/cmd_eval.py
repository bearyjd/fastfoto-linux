"""``ffscan eval``: offline evaluation harnesses (they read only the manifest they are given)."""

import argparse
import os
from pathlib import Path

from fastfoto_linux.cli.errors import EXIT_GATE_FAILED, EXIT_OK, EXIT_USAGE, CliError
from fastfoto_linux.cli.options import common_parent
from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.evaluation.redeye_manifest import SPLITS, Manifest, ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_output import resolve_out_dir, write_outputs
from fastfoto_linux.evaluation.redeye_report import (
    GateOptions,
    build_report,
    evaluate_gate,
    perf_json,
    render_summary,
    report_json,
)
from fastfoto_linux.evaluation.redeye_run import run_eval
from fastfoto_linux.evaluation.redeye_split import check_declared_splits


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser(
        "eval",
        help="offline evaluation harnesses (developer tools)",
        description="Evaluation harnesses. They ship no data and read only the manifest given.",
    )
    kinds = parser.add_subparsers(dest="eval_command", required=True, metavar="KIND")
    redeye = kinds.add_parser(
        "redeye",
        parents=[common_parent()],
        help="measure the auto red-eye path against a labelled manifest",
        description="Evaluate red-eye detection and correction against a manifest of labelled "
        "images. Reads only the manifest and the images it names, and writes report.json, "
        "summary.md and perf.json into a new run-... directory under DIR (outside the "
        "manifest directory); a run directory without report.json is incomplete.",
    )
    redeye.add_argument("manifest", type=Path, metavar="MANIFEST.json")
    redeye.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="results directory (each run adds a run-... directory)",
    )
    redeye.add_argument("--split", choices=SPLITS, default="tuning", help="split to report")
    redeye.add_argument(
        "--tuning-manifest",
        type=Path,
        action="append",
        default=[],
        metavar="MANIFEST.json",
        help="another manifest whose items must not leak into a held-out report (repeatable)",
    )
    redeye.add_argument("--gate", action="store_true", help="exit 5 unless the gates pass")
    redeye.add_argument("--expect-manifest-sha256", metavar="HEX", help="freeze the set for --gate")
    redeye.add_argument("--min-precision", type=float, metavar="F", help="Wilson lower bound")
    redeye.add_argument("--min-recall", type=float, metavar="F", help="Wilson lower bound")
    redeye.add_argument("--no-perf", action="store_true", help="skip perf.json")
    redeye.set_defaults(handler=run)


def make_detector() -> FaceDetector | None:
    """The face detector to evaluate with; None means the shared YuNet one (tests replace it)."""
    return None


def _check_usage(args: argparse.Namespace) -> None:
    if args.gate and (args.split != "heldout" or not args.expect_manifest_sha256):
        raise CliError("--gate needs --split heldout and --expect-manifest-sha256", EXIT_USAGE)
    optional = (args.min_precision, args.min_recall, args.expect_manifest_sha256)
    if not args.gate and any(v is not None for v in optional):
        raise CliError(
            "--min-precision, --min-recall and --expect-manifest-sha256 need --gate", EXIT_USAGE
        )
    for floor in (args.min_precision, args.min_recall):
        if floor is not None and not 0.0 <= floor <= 1.0:
            raise CliError("--min-precision and --min-recall are fractions from 0 to 1", EXIT_USAGE)


def _load_all(args: argparse.Namespace) -> tuple[Manifest, list[Manifest]]:
    """The manifest and the tuning manifests; each keeps its directory open (pinned) until
    the caller closes it."""
    loaded: list[Manifest] = []
    try:
        for path in (args.manifest, *args.tuning_manifest):
            loaded.append(load_manifest(path))
        return loaded[0], loaded[1:]
    except BaseException:
        for manifest in loaded:
            manifest.close()
        raise


def run(args: argparse.Namespace) -> int:
    _check_usage(args)
    try:
        manifest, tuning = _load_all(args)
    except ManifestError as error:
        raise CliError(str(error), EXIT_USAGE) from error
    try:
        return _run_loaded(args, manifest, tuning)
    finally:
        for loaded in (manifest, *tuning):
            loaded.close()


def _run_loaded(args: argparse.Namespace, manifest: Manifest, tuning: list[Manifest]) -> int:
    try:
        check_declared_splits(manifest)
        out_dir = resolve_out_dir(manifest, args.out, os.environ)
        result = run_eval(
            manifest,
            args.split,
            detector=make_detector(),
            tuning_manifests=tuning,
            perf=not args.no_perf,
        )
    except ManifestError as error:
        raise CliError(str(error), EXIT_USAGE) from error
    report = build_report(manifest, result)
    files = {"report.json": report_json(report), "summary.md": render_summary(report)}
    if not args.no_perf:
        files["perf.json"] = perf_json(result)
    try:
        run_name = write_outputs(
            out_dir, files, forbidden=[m.identity for m in (manifest, *tuning)]
        )
    except ManifestError as error:
        raise CliError(str(error), EXIT_USAGE) from error
    except OSError as error:
        raise CliError("cannot write the results directory") from error
    print(f"results: {out_dir / run_name}")
    totals = report["totals"]
    print(f"evaluated {totals['images']} image(s), {totals['errored']} errored")  # type: ignore[index]
    if not args.gate:
        return EXIT_OK
    verdict = evaluate_gate(
        report,
        GateOptions(args.expect_manifest_sha256, args.min_precision, args.min_recall),
    )
    if verdict.passed:
        print("GATE PASS")
        return EXIT_OK
    print("GATE FAIL")
    for failure in verdict.failures:
        print(f"  {failure}")
    return EXIT_GATE_FAILED
