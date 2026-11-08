"""The section 4.9 table as data, and the judge at its boundaries and at small n."""

import pytest

from fastfoto_linux.evaluation.calib_thresholds import MIN_N, THRESHOLDS, judge, row


def group(k: int, n: int = 50, p: float = 0.0) -> dict:
    return {"k": k, "n": n, "p": p}


def deskew(mae=0.3, wrong=None, abstain=0.25, applied=MIN_N) -> dict:
    return {
        "n": 10,
        "applied": applied,
        "mae_deg": mae,
        "wrong_direction": wrong or group(0, applied),
        "abstain": group(0, 10, abstain),
    }


def test_the_table_lists_every_row_and_marks_unevaluated_ones() -> None:
    harness = {r.feature: r.harness for r in THRESHOLDS}
    assert harness == {
        "deskew": "eval deskew",
        "autocolour": "eval autocolour",
        "wb": "eval wb",
        "detail": "eval detail",
        "small": "none",
        "redeye": "eval redeye",
        "cleanup": "none",
    }


def test_the_numbers_are_the_roadmap_ones() -> None:
    values = {(r.feature, c.key): (c.op, c.value) for r in THRESHOLDS for c in r.criteria}
    assert values == {
        ("deskew", "mae_deg"): ("<=", 0.3),
        ("deskew", "wrong_direction"): ("<=", 0),
        ("deskew", "abstain_rate"): ("<=", 0.25),
        ("autocolour", "colour_loss_zero"): ("<=", 0),
        ("autocolour", "over_retention"): ("<=", 0.30),
        ("wb", "restore_de00_improvement"): (">=", 0.30),
        ("wb", "ab_preference"): (">=", 0.60),
        ("detail", "sigma_reduction"): (">=", 25.0),
        ("detail", "edge_width_growth"): ("<=", 10.0),
        ("detail", "halo"): ("<=", 5.0),
        ("small", "median_mb_per_6x4"): ("<=", 1.5),
        ("small", "ssim"): (">=", 0.95),
        ("redeye", "g1_g5"): ("==", "pass"),
        ("redeye", "recall_lb"): (">=", 0.6),
        ("cleanup", "cer_delta_pp"): ("<=", 0.5),
        ("cleanup", "pencil_stamp_losses"): ("<=", 0),
    }


def test_the_extra_rows_are_inert_proposals() -> None:
    for feature in ("small", "redeye", "cleanup"):
        assert row(feature).criteria
        for criterion in row(feature).criteria:
            assert criterion.automated is False and criterion.label == "proposal"
        assert set(judge(feature, {}).values()) == {"not_applicable"}
    assert row("wb").criterion("ab_preference").automated is False
    assert MIN_N == 5


def test_deskew_boundaries_pass_at_the_limit_and_fail_beyond() -> None:
    assert set(judge("deskew", deskew()).values()) == {"pass"}
    assert judge("deskew", deskew(mae=0.3001))["mae_deg"] == "fail"
    assert judge("deskew", deskew(abstain=0.2501))["abstain_rate"] == "fail"


def test_zero_event_criteria_are_judged_on_the_count_not_the_rounded_rate() -> None:
    one_in_many = group(k=1, n=50_000, p=0.0)  # a rate that rounds to 0.0
    assert judge("deskew", deskew(wrong=one_in_many))["wrong_direction"] == "fail"
    auto = {"n": 50_000, "colour_loss": one_in_many, "over_retention": group(0, 50_000)}
    assert judge("autocolour", auto)["colour_loss_zero"] == "fail"
    auto["colour_loss"] = group(0, 50_000)
    assert judge("autocolour", auto) == {"colour_loss_zero": "pass", "over_retention": "pass"}


def test_lower_bound_criteria_pass_at_the_limit() -> None:
    detail = {
        "n": MIN_N,
        "sigma_reduction_pct_median": 25.0,
        "edge_width_growth_pct_median": 10.0,
        "halo_pct_p90": 5.0,
    }
    assert set(judge("detail", detail).values()) == {"pass"}
    low = judge("detail", {**detail, "sigma_reduction_pct_median": 24.9999})
    assert low["sigma_reduction"] == "fail"
    assert judge("detail", {**detail, "halo_pct_p90": 5.0001})["halo"] == "fail"
    growth = judge("detail", {**detail, "edge_width_growth_pct_median": 10.0001})
    assert growth["edge_width_growth"] == "fail"


def test_wb_row() -> None:
    cast = {"settings": {"none": {"cast_items": {"n": MIN_N}}}}
    wb = judge("wb", {**cast, "improvement_vs_none_restore": 0.30})
    assert wb == {"restore_de00_improvement": "pass", "ab_preference": "not_applicable"}
    assert (
        judge("wb", {**cast, "improvement_vs_none_restore": 0.29})["restore_de00_improvement"]
        == "fail"
    )


def test_a_missing_number_is_insufficient_data() -> None:
    cast = {"settings": {"none": {"cast_items": {"n": MIN_N}}}}
    got = judge("wb", {**cast, "improvement_vs_none_restore": None})
    assert got["restore_de00_improvement"] == "insufficient_data"
    assert set(judge("deskew", {}).values()) == {"insufficient_data"}
    assert judge("deskew", deskew(mae=None))["mae_deg"] == "insufficient_data"


def test_below_the_minimum_sample_every_automated_criterion_is_insufficient() -> None:
    small = deskew(applied=MIN_N - 1)
    assert judge("deskew", small)["mae_deg"] == "insufficient_data"
    assert judge("deskew", small)["wrong_direction"] == "insufficient_data"
    auto = {"n": MIN_N - 1, "colour_loss": group(0, MIN_N - 1), "over_retention": group(0, 4)}
    assert set(judge("autocolour", auto).values()) == {"insufficient_data"}
    detail = {"n": MIN_N - 1, "sigma_reduction_pct_median": 99.0, "halo_pct_p90": 0.0}
    assert set(judge("detail", detail).values()) == {"insufficient_data"}
    few_cast = {"settings": {"none": {"cast_items": {"n": MIN_N - 1}}}}
    wb = judge("wb", {**few_cast, "improvement_vs_none_restore": 0.9})
    assert wb["restore_de00_improvement"] == "insufficient_data"


def test_an_unknown_feature_is_refused() -> None:
    with pytest.raises(ValueError, match="feature"):
        row("nothing")
    with pytest.raises(ValueError, match="feature"):
        judge("nothing", {})


def test_a_mean_exactly_at_the_limit_passes_despite_float_error() -> None:
    errors = [0.4, 0.2, 0.4, 0.4, 0.2, 0.2, 0.4, 0.2]
    mae = sum(errors) / len(errors)  # 0.30000000000000004
    metrics = {
        "applied": 8,
        "mae_deg": mae,
        "wrong_direction": {"k": 0, "n": 8, "p": 0.0},
        "abstain": {"k": 0, "n": 8, "p": 0.0},
    }
    assert judge("deskew", metrics)["mae_deg"] == "pass"


def test_a_value_clearly_past_the_limit_still_fails() -> None:
    metrics = {"over_retention": {"k": 601, "n": 2003, "p": 601 / 2003}}
    assert judge("autocolour", metrics)["over_retention"] == "fail"
