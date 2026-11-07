"""The section 4.9 table as data, and the judge at its boundaries."""

import pytest

from fastfoto_linux.evaluation.calib_thresholds import THRESHOLDS, judge, row


def deskew(mae=0.3, wrong=0.0, abstain=0.25) -> dict:
    return {"mae_deg": mae, "wrong_direction": {"p": wrong}, "abstain": {"p": abstain}}


def test_the_table_lists_every_row_and_marks_unevaluated_ones() -> None:
    harness = {r.feature: r.harness for r in THRESHOLDS}
    assert harness == {
        "deskew": "eval deskew",
        "autocolour": "eval autocolour",
        "wb": "eval wb",
        "detail": "eval detail",
        "small": "none",
        "redeye": "none",
        "cleanup": "none",
    }
    assert all(not r.criteria for r in THRESHOLDS if r.harness == "none")


def test_the_numbers_are_the_roadmap_ones() -> None:
    values = {(r.feature, c.key): (c.op, c.value) for r in THRESHOLDS for c in r.criteria}
    assert values == {
        ("deskew", "mae_deg"): ("<=", 0.3),
        ("deskew", "wrong_direction"): ("<=", 0.0),
        ("deskew", "abstain_rate"): ("<=", 0.25),
        ("autocolour", "colour_loss_zero"): ("<=", 0.0),
        ("autocolour", "over_retention"): ("<=", 0.30),
        ("wb", "restore_de00_improvement"): (">=", 0.30),
        ("wb", "ab_preference"): (">=", 0.60),
        ("detail", "sigma_reduction"): (">=", 25.0),
        ("detail", "edge_width_growth"): ("<=", 10.0),
        ("detail", "halo"): ("<=", 5.0),
    }
    assert row("wb").criterion("ab_preference").automated is False


def test_deskew_boundaries_pass_at_the_limit_and_fail_beyond() -> None:
    assert set(judge("deskew", deskew()).values()) == {"pass"}
    assert judge("deskew", deskew(mae=0.3001))["mae_deg"] == "fail"
    assert judge("deskew", deskew(wrong=0.0001))["wrong_direction"] == "fail"
    assert judge("deskew", deskew(abstain=0.2501))["abstain_rate"] == "fail"


def test_lower_bound_criteria_pass_at_the_limit() -> None:
    detail = {
        "sigma_reduction_pct_median": 25.0,
        "edge_width_growth_pct_median": 10.0,
        "halo_pct_p90": 5.0,
    }
    assert set(judge("detail", detail).values()) == {"pass"}
    assert judge("detail", {**detail, "sigma_reduction_pct_median": 24.9999})[
        "sigma_reduction"
    ] == ("fail")
    assert judge("detail", {**detail, "halo_pct_p90": 5.0001})["halo"] == "fail"
    assert (
        judge("detail", {**detail, "edge_width_growth_pct_median": 10.0001})["edge_width_growth"]
        == "fail"
    )


def test_autocolour_and_wb_rows() -> None:
    ok = {"colour_loss": {"p": 0.0}, "over_retention": {"p": 0.30}}
    assert judge("autocolour", ok) == {"colour_loss_zero": "pass", "over_retention": "pass"}
    assert judge("autocolour", {**ok, "colour_loss": {"p": 0.05}})["colour_loss_zero"] == "fail"
    assert judge("autocolour", {**ok, "over_retention": {"p": 0.31}})["over_retention"] == "fail"
    wb = judge("wb", {"improvement_vs_none_restore": 0.30})
    assert wb == {"restore_de00_improvement": "pass", "ab_preference": "not_applicable"}
    assert judge("wb", {"improvement_vs_none_restore": 0.29})["restore_de00_improvement"] == "fail"


def test_a_missing_number_is_insufficient_data() -> None:
    assert judge("wb", {"improvement_vs_none_restore": None})["restore_de00_improvement"] == (
        "insufficient_data"
    )
    assert set(judge("deskew", {}).values()) == {"insufficient_data"}
    assert judge("deskew", deskew(mae=None))["mae_deg"] == "insufficient_data"
    assert judge("autocolour", {"colour_loss": {"p": None}})["colour_loss_zero"] == (
        "insufficient_data"
    )


def test_an_unknown_feature_is_refused() -> None:
    with pytest.raises(ValueError, match="feature"):
        judge("redeye", {})
    with pytest.raises(ValueError, match="feature"):
        row("nothing")
