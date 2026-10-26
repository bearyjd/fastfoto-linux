"""report.json, summary.md, perf.json and the gate verdict."""

from dataclasses import dataclass

from fastfoto_linux.evaluation.redeye_manifest import Manifest
from fastfoto_linux.evaluation.redeye_run import RunResult


@dataclass(frozen=True)
class GateOptions:
    expect_sha256: str
    min_precision: float | None = None
    min_recall: float | None = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]


def build_report(manifest: Manifest, run: RunResult) -> dict[str, object]:
    raise NotImplementedError


def report_json(report: dict[str, object]) -> str:
    raise NotImplementedError


def render_summary(report: dict[str, object]) -> str:
    raise NotImplementedError


def perf_json(run: RunResult) -> str:
    raise NotImplementedError


def evaluate_gate(report: dict[str, object], options: GateOptions) -> GateResult:
    raise NotImplementedError
