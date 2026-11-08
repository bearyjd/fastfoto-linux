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
MIN_N = 5  # a proposal, not a roadmap number: below it a group reports no statistics
PROPOSAL = "proposal"
FLOAT_SLACK = 1e-9  # relative: absorbs float error at an inclusive limit, nothing measurable
_OPS: dict[str, Callable[[object, object], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
}


@dataclass(frozen=True)
class Criterion:
    """``metric`` is a dotted path into the feature's metrics; ``value`` the limit under ``op``.
    ``n_path`` locates the sample size of the group judged: below ``MIN_N`` the verdict is
    ``insufficient_data``. ``label`` is ``proposal`` for numbers that are not from the roadmap's
    measured rows."""

    key: str
    metric: str
    op: str
    value: float | str
    automated: bool = True
    n_path: str = "n"
    label: str = "-"


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
            Criterion("mae_deg", "mae_deg", "<=", 0.3, n_path="applied"),
            Criterion("wrong_direction", "wrong_direction.k", "<=", 0, n_path="wrong_direction.n"),
            Criterion("abstain_rate", "abstain.p", "<=", 0.25, n_path="abstain.n"),
        ),
    ),
    FeatureRow(
        "autocolour",
        "documents/auto_colour.py",
        "documents.md",
        "eval autocolour",
        (
            Criterion("colour_loss_zero", "colour_loss.k", "<=", 0, n_path="colour_loss.n"),
            Criterion("over_retention", "over_retention.p", "<=", 0.30, n_path="over_retention.n"),
        ),
    ),
    FeatureRow(
        "wb",
        "enhance/restore.py",
        "photo-white-balance.md",
        "eval wb",
        (
            Criterion(
                "restore_de00_improvement",
                "improvement_vs_none_restore",
                ">=",
                0.30,
                n_path="settings.none.cast_items.n",
            ),
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
    FeatureRow(
        "small",
        "export presets",
        "export-presets.md",
        NO_HARNESS,
        (
            Criterion("median_mb_per_6x4", "median_mb_per_6x4", "<=", 1.5, False, label=PROPOSAL),
            Criterion("ssim", "ssim", ">=", 0.95, False, label=PROPOSAL),
        ),
    ),
    FeatureRow(
        "redeye",
        "enhance/redeye.py",
        "redeye-evaluation.md",
        "eval redeye",
        (
            Criterion("g1_g5", "g1_g5", "==", "pass", False, label=PROPOSAL),
            Criterion("recall_lb", "recall_lb", ">=", 0.6, False, label=PROPOSAL),
        ),
    ),
    FeatureRow(
        "cleanup",
        "documents/cleanup.py",
        "documents.md",
        NO_HARNESS,
        (
            Criterion("cer_delta_pp", "cer_delta_pp", "<=", 0.5, False, label=PROPOSAL),
            Criterion("pencil_stamp_losses", "pencil_stamp_losses", "<=", 0, False, label=PROPOSAL),
        ),
    ),
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
    size = _lookup(metrics, criterion.n_path)
    if type(size) is not int or size < MIN_N:
        return INSUFFICIENT
    value = _lookup(metrics, criterion.metric)
    if type(value) not in (int, float):
        return INSUFFICIENT
    return PASS if _OPS[criterion.op](value, _slackened(criterion)) else FAIL


def _slackened(criterion: Criterion) -> float:
    """The limit widened by ``FLOAT_SLACK`` in the inclusive direction, so a mean that is
    mathematically on the limit (0.30000000000000004 for 0.3) is not failed by float error."""
    slack = FLOAT_SLACK * max(1.0, abs(criterion.value))
    if criterion.op == "<=":
        return criterion.value + slack
    if criterion.op == ">=":
        return criterion.value - slack
    return criterion.value


def judge(feature: str, metrics: Mapping[str, object]) -> dict[str, str]:
    """The status of each criterion of ``feature`` for its metrics (``not_applicable`` for the
    inert ones); an unknown feature is refused (``ValueError``)."""
    found = row(feature)
    return {criterion.key: _verdict(criterion, metrics) for criterion in found.criteria}
