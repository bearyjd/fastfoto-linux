"""The roadmap section 4.9 acceptance table as data, and the judge that applies it.

Constants of the features were tuned on synthetic data only; this table is what a human run on a
real corpus is measured against. ``judge`` compares a feature's metrics (as reported, already
rounded) with each criterion: ``pass``, ``fail``, ``insufficient_data`` (the number is missing)
or ``not_applicable`` (a human judgement, not automated).
"""

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass

PASS = "pass"
FAIL = "fail"
INSUFFICIENT = "insufficient_data"
NOT_APPLICABLE = "not_applicable"
NO_HARNESS = "none"
_OPS: dict[str, Callable[[float, float], bool]] = {"<=": operator.le, ">=": operator.ge}


@dataclass(frozen=True)
class Criterion:
    """``metric`` is a dotted path into the feature's metrics; ``value`` the limit under ``op``."""

    key: str
    metric: str
    op: str
    value: float
    automated: bool = True


@dataclass(frozen=True)
class FeatureRow:
    feature: str
    family: str  # where the constants live
    design_doc: str
    harness: str  # the command that evaluates it, or "none"
    criteria: tuple[Criterion, ...] = ()

    def criterion(self, key: str) -> Criterion:
        for criterion in self.criteria:
            if criterion.key == key:
                return criterion
        raise ValueError("no such criterion")


THRESHOLDS = (
    FeatureRow(
        "deskew",
        "documents/deskew_tables.py",
        "documents.md",
        "eval deskew",
        (
            Criterion("mae_deg", "mae_deg", "<=", 0.3),
            Criterion("wrong_direction", "wrong_direction.p", "<=", 0.0),
            Criterion("abstain_rate", "abstain.p", "<=", 0.25),
        ),
    ),
    FeatureRow(
        "autocolour",
        "documents/auto_colour.py",
        "documents.md",
        "eval autocolour",
        (
            Criterion("colour_loss_zero", "colour_loss.p", "<=", 0.0),
            Criterion("over_retention", "over_retention.p", "<=", 0.30),
        ),
    ),
    FeatureRow(
        "wb",
        "enhance/restore.py",
        "photo-white-balance.md",
        "eval wb",
        (
            Criterion("restore_de00_improvement", "improvement_vs_none_restore", ">=", 0.30),
            Criterion("ab_preference", "ab_preference", ">=", 0.60, automated=False),
        ),
    ),
    FeatureRow(
        "detail",
        "photo_edits/detail.py",
        "photo-detail.md",
        "eval detail",
        (
            Criterion("sigma_reduction", "sigma_reduction_pct_median", ">=", 25.0),
            Criterion("edge_width_growth", "edge_width_growth_pct_median", "<=", 10.0),
            Criterion("halo", "halo_pct_p90", "<=", 5.0),
        ),
    ),
    FeatureRow("small", "export presets", "export-presets.md", NO_HARNESS),
    FeatureRow("redeye", "enhance/redeye.py", "redeye-evaluation.md", NO_HARNESS),
    FeatureRow("cleanup", "documents/cleanup.py", "documents.md", NO_HARNESS),
)


def row(feature: str) -> FeatureRow:
    for found in THRESHOLDS:
        if found.feature == feature:
            return found
    raise ValueError("unknown feature")


def _lookup(metrics: Mapping[str, object], path: str) -> object:
    node: object = metrics
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _verdict(criterion: Criterion, metrics: Mapping[str, object]) -> str:
    if not criterion.automated:
        return NOT_APPLICABLE
    value = _lookup(metrics, criterion.metric)
    if type(value) not in (int, float):
        return INSUFFICIENT
    return PASS if _OPS[criterion.op](value, criterion.value) else FAIL


def judge(feature: str, metrics: Mapping[str, object]) -> dict[str, str]:
    """The status of each criterion of ``feature`` for its metrics; a feature that no harness
    here evaluates is refused (``ValueError``)."""
    found = row(feature)
    if found.harness == NO_HARNESS:
        raise ValueError("this feature is not evaluated by the calibration harness")
    return {criterion.key: _verdict(criterion, metrics) for criterion in found.criteria}
