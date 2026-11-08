"""One end-to-end run per feature on a few tiny synthetic files, and the report's properties."""

import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from fastfoto_linux.evaluation import calib_detail, calib_pages, calib_wb
from fastfoto_linux.evaluation.calib_run import run_calibration
from fastfoto_linux.evaluation.corpus_manifest import load_corpus_manifest, parse_corpus_manifest
from fastfoto_linux.evaluation.corpus_report import build_report, check_metrics_only
from fastfoto_linux.evaluation.corpus_types import CorpusError
from fastfoto_linux.evaluation.redeye_images import decode_image
from fastfoto_linux.photo_edits.detail import apply_denoise, apply_sharpen
from fastfoto_linux.photo_edits.model import PhotoDetail
from tests.calibration.synth import (
    DETAIL_NOTE,
    Entry,
    bilevel_png,
    blank_png,
    colour_png,
    detail_png,
    reports,
    run_cli,
    text_png,
    wb_png,
    write_corpus,
)
from tests.corpus.helpers import document, encode, raw_item


def run_one(tmp_path: Path, feature: str, entries: list[Entry], *extra: object, tag: str = "out"):
    corpus = write_corpus(tmp_path / f"corpus-{tag}", entries)
    out = tmp_path / tag
    assert run_cli(feature, "--corpus", corpus.parent, "--out", out, *extra) == 0
    (path,) = reports(out)
    return path.read_bytes(), json.loads(path.read_bytes())["metrics"]


PAGES = [(-40, 1), (25, 2), (60, 3), (-15, 4), (35, 5)]


def deskew_entries(sign: int = 1) -> list[Entry]:
    items = [
        Entry(f"p{i}", text_png(t, seed), "document", "tuning",
              {"deskew": {"correction_tenths": [-t * sign]}})
        for i, (t, seed) in enumerate(PAGES)
    ]  # fmt: skip
    blank = {"deskew": {"dpi": 150, "correction_tenths": [0]}}
    items.append(Entry("blank", blank_png(), "document", "tuning", blank))
    items.append(Entry("noannotation", text_png(10, 9), "document", "tuning", {}))
    photo = {"deskew": {"correction_tenths": [0]}}
    items.append(Entry("aphoto", wb_png(False), "photo", "tuning", photo))
    return items


def test_deskew_measures_both_directions_and_abstains_on_a_blank_page(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "deskew", deskew_entries())
    assert metrics["counts"] == {"n": 6, "skipped": 1, "errored": 0}
    deskew = metrics["deskew"]
    assert deskew["applied"] == 5 and deskew["abstain"]["k"] == 1
    assert deskew["wrong_direction"]["k"] == 0 and deskew["wrong_direction"]["n"] == 5
    assert deskew["mae_deg"] <= 0.3 and deskew["p90_abs_err_deg"] <= 0.5
    assert metrics["criteria"]["wrong_direction"] == "pass"


def test_deskew_with_the_opposite_sign_annotated_is_all_wrong_direction(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "deskew", deskew_entries(sign=-1))
    assert metrics["deskew"]["wrong_direction"]["k"] == 5
    assert metrics["deskew"]["mae_deg"] > 3
    assert metrics["criteria"]["wrong_direction"] == "fail"


def test_autocolour_counts_losses_and_over_retention(tmp_path) -> None:
    pages = [
        ("a", colour_png("text"), "bw"),  # right
        ("b", colour_png("stamp"), "colour"),  # right
        ("c", colour_png("faint"), "colour"),  # grey result for a colour label: a loss
        ("d", colour_png("sepia"), "bw"),  # colour kept where bw was enough: over-retention
        ("e", colour_png("gradient"), "grey"),  # right
        ("f", bilevel_png(), "bw"),  # a one-bit source stays one-bit
    ]
    entries = [
        Entry(n, d, "document", "tuning", {"autocolour": {"label": lab}}) for n, d, lab in pages
    ]
    _, metrics = run_one(tmp_path, "autocolour", entries)
    auto = metrics["autocolour"]
    assert metrics["counts"]["n"] == 6 and metrics["counts"]["errored"] == 0
    assert (auto["colour_loss"]["k"], auto["colour_loss"]["n"]) == (1, 6)
    assert auto["over_retention"]["k"] == 1
    assert auto["colour_loss"]["zero_upper_bound"] is None


def test_autocolour_reports_the_zero_loss_upper_bound(tmp_path) -> None:
    cases = [("a", "stamp", "colour"), ("b", "text", "bw"), ("c", "gradient", "grey"),
             ("d", "red_stroke", "colour"), ("e", "reversed", "grey")]  # fmt: skip
    entries = [
        Entry(n, colour_png(c), "document", "tuning", {"autocolour": {"label": lab}})
        for n, c, lab in cases
    ]
    _, metrics = run_one(tmp_path, "autocolour", entries)
    loss = metrics["autocolour"]["colour_loss"]
    assert loss["zero_upper_bound"] == pytest.approx(0.4507, abs=1e-4)
    assert metrics["criteria"]["colour_loss_zero"] == "pass"


def test_below_five_items_the_statistics_are_withheld_and_the_counts_kept(tmp_path) -> None:
    cases = [("a", "stamp", "colour"), ("b", "text", "bw"), ("c", "gradient", "grey"),
             ("d", "red_stroke", "colour")]  # fmt: skip
    entries = [
        Entry(n, colour_png(c), "document", "tuning", {"autocolour": {"label": lab}})
        for n, c, lab in cases
    ]
    _, metrics = run_one(tmp_path, "autocolour", entries)
    loss = metrics["autocolour"]["colour_loss"]
    assert (loss["k"], loss["n"]) == (0, 4)
    assert loss["p"] is None and loss["zero_upper_bound"] is None
    assert loss["status"] == "insufficient_data"
    assert set(metrics["criteria"].values()) == {"insufficient_data"}
    assert metrics["counts"]["n"] == 4


def wb_entries(neutral: int = 1, cast: int = 5) -> list[Entry]:
    note = {"wb": {"neutral_boxes": [[60, 20, 40, 20]], "cast": False}}
    cast_note = {"wb": {"neutral_boxes": [[60, 20, 40, 20]], "cast": True}}
    return [
        *(Entry(f"n{i}", wb_png(False, i), "photo", "tuning", note) for i in range(neutral)),
        *(Entry(f"c{i}", wb_png(True, 10 + i), "photo", "tuning", cast_note) for i in range(cast)),
    ]


def test_wb_reports_every_setting_on_all_items_and_on_cast_items(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "wb", wb_entries())
    wb = metrics["wb"]
    settings = wb["settings"]
    assert list(settings) == sorted(["none", "restore", "warm", "cool", "faded", "mono"])
    assert settings["none"]["all_items"]["n"] == 6 and settings["none"]["cast_items"]["n"] == 5
    assert settings["none"]["cast_items"]["median_de00"] > 5
    assert settings["mono"] == settings["none"]  # the preset's white balance part is neutral
    restored = settings["restore"]["cast_items"]["median_de00"]
    assert restored < settings["none"]["cast_items"]["median_de00"]
    assert wb["improvement_vs_none_restore"] > 0


def test_wb_presets_move_a_neutral_patch_away_from_neutral(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "wb", wb_entries(neutral=5, cast=0))
    settings = metrics["wb"]["settings"]
    assert settings["none"]["all_items"]["median_de00"] < 0.5
    assert settings["warm"]["all_items"]["median_de00"] > 2
    assert settings["cool"]["all_items"]["median_de00"] > 2
    assert metrics["wb"]["improvement_vs_none_restore"] is None  # no cast items: no judgement


def test_the_wb_cast_subset_is_withheld_below_five_items(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "wb", wb_entries(neutral=5, cast=2))
    settings = metrics["wb"]["settings"]
    assert settings["none"]["all_items"]["median_de00"] is not None
    cast = settings["none"]["cast_items"]
    assert cast["n"] == 2 and cast["median_de00"] is None and cast["p90_de00"] is None
    assert cast["status"] == "insufficient_data"
    assert metrics["wb"]["improvement_vs_none_restore"] is None
    assert metrics["criteria"]["restore_de00_improvement"] == "insufficient_data"


def test_the_wb_renderings_leave_their_input_untouched() -> None:
    rgb = decode_image(wb_png(True))
    before = rgb.copy()
    for setting in calib_wb.SETTINGS:
        first = calib_wb.render(rgb, setting)
        assert np.array_equal(rgb, before)
        assert np.array_equal(first, calib_wb.render(rgb, setting))


def test_detail_renders_denoise_then_sharpen_on_one_buffer_like_the_product() -> None:
    rgb = decode_image(detail_png())
    before = rgb.copy()
    strengths = calib_detail.Strengths(50, 50, 50)
    chained = calib_detail.render(rgb, 300, strengths)
    assert np.array_equal(rgb, before)
    expected = rgb.copy()
    apply_denoise(expected, PhotoDetail(denoise_luma=50, denoise_chroma=50), Event())
    apply_sharpen(expected, PhotoDetail(sharpen=50), 300.0, Event())
    assert np.array_equal(chained, expected)


def detail_entries(count: int = 5) -> list[Entry]:
    return [
        Entry(f"d{i}", detail_png(i + 1), "photo", "tuning", {"detail": DETAIL_NOTE})
        for i in range(count)
    ]


def test_detail_cuts_noise_and_sharpening_leaves_a_halo(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "detail", detail_entries())
    detail = metrics["detail"]
    assert detail["strengths"] == {"denoise_luma": 50, "denoise_chroma": 50, "sharpen": 50}
    assert detail["sigma_reduction_pct_median"] > 10
    assert detail["halo_pct_p90"] > 0
    assert isinstance(detail["edge_width_growth_pct_median"], float)


def test_detail_strengths_can_be_overridden_and_zero_changes_nothing(tmp_path) -> None:
    _, metrics = run_one(
        tmp_path, "detail", detail_entries(),
        "--denoise-luma", 0, "--denoise-chroma", 0, "--sharpen", 0,
    )  # fmt: skip
    detail = metrics["detail"]
    assert detail["strengths"] == {"denoise_luma": 0, "denoise_chroma": 0, "sharpen": 0}
    assert detail["sigma_reduction_pct_median"] == 0.0
    assert detail["edge_width_growth_pct_median"] == 0.0 and detail["halo_pct_p90"] == 0.0


def test_a_box_outside_the_image_is_counted_as_an_errored_item_not_fatal(tmp_path, capsys) -> None:
    bad = {"detail": {**DETAIL_NOTE, "flat_boxes": [[100, 80, 40, 40]]}}
    entries = [*detail_entries(), Entry("d9", detail_png(9), "photo", "tuning", bad)]
    _, metrics = run_one(tmp_path, "detail", entries)
    assert metrics["counts"] == {"n": 6, "skipped": 0, "errored": 1}
    err = capsys.readouterr().err
    assert "item-d9: errored (AnnotationError)" in err


def test_an_item_over_the_pixel_cap_is_errored(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(calib_pages, "MAX_PIXELS", 1000)
    _, metrics = run_one(tmp_path, "detail", detail_entries(), tag="photo")
    assert metrics["counts"]["errored"] == 5
    entries = [
        Entry("a", colour_png("text"), "document", "tuning", {"autocolour": {"label": "bw"}})
    ]
    _, metrics = run_one(tmp_path, "autocolour", entries, tag="doc")
    assert metrics["counts"]["errored"] == 1
    assert "errored (ValueError)" in capsys.readouterr().err


def test_a_memory_error_is_not_swallowed(tmp_path, monkeypatch) -> None:
    def boom(*_args: object) -> None:
        raise MemoryError

    monkeypatch.setattr(calib_detail, "measure", boom)
    corpus = write_corpus(tmp_path / "corpus", detail_entries(1))
    with load_corpus_manifest(corpus) as manifest, pytest.raises(MemoryError):
        run_calibration(manifest, "detail", "tuning")


@pytest.mark.parametrize(
    ("feature", "make"),
    [
        ("deskew", deskew_entries),
        ("wb", wb_entries),
        ("detail", detail_entries),
    ],
)
def test_the_report_is_byte_identical_on_rerun_and_carries_no_item_data(
    tmp_path, feature, make
) -> None:
    first, metrics = run_one(tmp_path, feature, make(), tag="one")
    second, _ = run_one(tmp_path, feature, make(), tag="two")
    assert first == second
    check_metrics_only({"metrics": metrics})
    text = first.decode("ascii")
    for private in ("item-", "corpus-one", ".png", str(tmp_path), "synthetic test pixels"):
        assert private not in text
    assert "run-" not in text and "elapsed" not in text and "seconds" not in text


def test_the_metrics_pass_the_echo_guard_with_every_annotation_on_every_item(tmp_path) -> None:
    every = {
        "deskew": {"dpi": 150, "correction_tenths": [0]},
        "autocolour": {"label": "bw"},
        "wb": {"neutral_boxes": [[60, 20, 40, 20]], "cast": True},
        "detail": DETAIL_NOTE,
    }
    entries = [Entry("x", wb_png(True), "photo", "tuning", every)]
    for feature in ("wb", "detail"):
        run_one(tmp_path, feature, entries, tag=feature)
    doc = [Entry("y", colour_png("text"), "document", "tuning", every)]
    for feature in ("autocolour", "deskew"):
        run_one(tmp_path, feature, doc, tag=feature)


def test_check_metrics_only_refuses_a_metric_named_like_an_annotation_value() -> None:
    item = raw_item("a", annotations={"autocolour": {"label": "colour"}})
    manifest = parse_corpus_manifest(encode(document([item])))
    with pytest.raises(CorpusError):
        build_report(manifest, {"colour": 1})


def test_deskew_and_detail_withhold_their_statistics_below_five_items(tmp_path) -> None:
    _, metrics = run_one(tmp_path, "deskew", deskew_entries()[:4], tag="deskew")
    deskew = metrics["deskew"]
    assert deskew["applied"] == 4 and deskew["status"] == "insufficient_data"
    assert deskew["mae_deg"] is None and deskew["p90_abs_err_deg"] is None
    assert set(metrics["criteria"].values()) == {"insufficient_data"}
    _, metrics = run_one(tmp_path, "detail", detail_entries(4), tag="detail")
    detail = metrics["detail"]
    assert detail["status"] == "insufficient_data" and detail["n"] == 4
    assert detail["sigma_reduction_pct_median"] is None and detail["halo_pct_p90"] is None
    assert detail["edge_width_growth_pct_median"] is None
