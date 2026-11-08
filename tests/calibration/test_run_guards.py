"""The run contract: pin, held-out refusal, leak check, gate exit code, output location."""

import json
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.evaluation import calib_colour, calib_run
from fastfoto_linux.evaluation.calib_run import resolve_out
from fastfoto_linux.evaluation.corpus_manifest import load_corpus_manifest
from fastfoto_linux.evaluation.corpus_types import CorpusError
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from tests.calibration.synth import (
    AUTO_DPI,
    DETAIL_NOTE,
    Entry,
    bilevel_png,
    colour_png,
    detail_png,
    grey_page,
    manifest_sha,
    png,
    reports,
    run_cli,
    text_png,
    wb_png,
    write_corpus,
)
from tests.documents.auto_helpers import auto_page

LABEL = "autocolour"


def note(label: str) -> dict:
    return {LABEL: {"label": label}}


def entry(name: str, data: bytes, label: str, split: str) -> Entry:
    return Entry(name, data, "document", split, note(label))


def base_entries() -> list[Entry]:
    return [
        entry("t1", colour_png("text"), "bw", "tuning"),
        entry("h1", colour_png("stamp"), "colour", "heldout"),
        entry("h2", colour_png("red_stroke"), "colour", "heldout"),
        entry("h3", colour_png("gradient"), "grey", "heldout"),
        entry("h4", colour_png("reversed"), "grey", "heldout"),
        entry("h5", colour_png("sepia"), "colour", "heldout"),
    ]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return write_corpus(tmp_path / "corpus", base_entries())


def heldout(corpus: Path, tmp_path: Path, *extra: str) -> int:
    pin = manifest_sha(corpus)
    return run_cli(
        LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out", "--split", "heldout",
        "--expect-manifest-sha256", pin, *extra,
    )  # fmt: skip


def only_report(tmp_path: Path) -> dict:
    (path,) = reports(tmp_path / "out")
    return json.loads(path.read_text())


def test_a_tuning_run_needs_no_pin_and_writes_only_report_json(corpus, tmp_path) -> None:
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out") == 0
    (report,) = reports(tmp_path / "out")
    assert sorted(p.name for p in report.parent.iterdir()) == ["report.json"]
    assert json.loads(report.read_text())["metrics"]["counts"]["n"] == 1


def test_heldout_without_a_pin_is_refused_before_anything_is_written(
    corpus, tmp_path, capsys
) -> None:
    code = run_cli(
        LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out", "--split", "heldout"
    )
    assert code == 2
    assert "--expect-manifest-sha256" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("split", ["tuning", "heldout"])
@pytest.mark.parametrize("pin", ["f" * 64, "abc", "G" * 64])
def test_a_pin_that_does_not_match_is_refused_for_either_split(
    corpus, tmp_path, capsys, split, pin
) -> None:
    code = run_cli(
        LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out", "--split", split,
        "--expect-manifest-sha256", pin,
    )  # fmt: skip
    err = capsys.readouterr().err
    assert code == 2 and not reports(tmp_path / "out")
    assert str(corpus.parent) not in err and manifest_sha(corpus) not in err


def test_the_gate_needs_the_held_out_split_and_a_pin(corpus, tmp_path) -> None:
    out, pin = tmp_path / "out", manifest_sha(corpus)
    base = (LABEL, "--corpus", corpus.parent, "--out", out, "--gate")
    assert run_cli(*base) == 2
    assert run_cli(*base, "--split", "heldout") == 2
    assert run_cli(*base, "--expect-manifest-sha256", pin) == 2
    assert not out.exists()


def test_a_passing_gate_says_only_automated_criteria_were_judged(corpus, tmp_path, capsys) -> None:
    assert heldout(corpus, tmp_path, "--gate") == 0
    out = capsys.readouterr().out
    assert "GATE PASS" not in out and "only automated criteria" in out
    assert "not a section 4.9 pass" in out
    metrics = only_report(tmp_path)["metrics"]
    assert metrics["criteria"] == {"colour_loss_zero": "pass", "over_retention": "pass"}
    assert metrics["counts"]["n"] == 5 and metrics["counts"]["errored"] == 0


def test_a_failing_criterion_exits_five_but_still_writes_the_report(tmp_path, capsys) -> None:
    entries = [*base_entries(), entry("h6", colour_png("faint"), "colour", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)  # a grey result for a colour label
    assert heldout(corpus, tmp_path, "--gate") == 5
    assert "AUTOMATED GATE FAIL" in capsys.readouterr().out
    assert only_report(tmp_path)["metrics"]["criteria"]["colour_loss_zero"] == "fail"


def test_over_retention_above_the_limit_fails_the_gate(tmp_path) -> None:
    entries = [
        entry(
            e.name,
            e.data,
            "bw" if e.name in ("h2", "h5") else e.annotations[LABEL]["label"],
            e.split,
        )
        for e in base_entries()
    ]  # 2 of 5 kept more than needed
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path, "--gate") == 5
    assert only_report(tmp_path)["metrics"]["criteria"]["over_retention"] == "fail"


def test_an_errored_held_out_item_fails_the_gate_however_good_the_rest(tmp_path) -> None:
    tiny = png(np.full((20, 20), 200, np.uint8), dpi=100)  # decodes, but under 10 mm
    entries = [*base_entries(), entry("h6", tiny, "bw", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path, "--gate") == 5
    counts = only_report(tmp_path)["metrics"]["counts"]
    assert counts["errored"] == 1 and counts["n"] == 6


def test_a_gate_with_no_annotated_held_out_items_is_insufficient_data(tmp_path) -> None:
    unannotated = Entry("h1", colour_png("stamp"), "document", "heldout", {})
    corpus = write_corpus(tmp_path / "corpus", [base_entries()[0], unannotated])
    assert heldout(corpus, tmp_path, "--gate") == 5
    metrics = only_report(tmp_path)["metrics"]
    assert set(metrics["criteria"].values()) == {"insufficient_data"}
    assert metrics["counts"]["skipped"] == 1


def test_a_pixel_duplicate_across_the_splits_refuses_a_held_out_run(tmp_path, capsys) -> None:
    pixels = auto_page("text", AUTO_DPI).pixels
    twin = png(pixels, dpi=AUTO_DPI + 1)  # other file bytes, same pixels
    entries = [
        entry("t1", colour_png("text"), "bw", "tuning"),
        entry("h1", twin, "bw", "heldout"),
    ]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path) == 2
    err = capsys.readouterr().err
    assert "item-h1" in err and "item-t1" in err and "pixel hash" in err
    assert not reports(tmp_path / "out")
    # the same corpus is fine as a tuning run: only held-out runs need the leak check
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out2") == 0


def test_an_unreadable_tuning_item_refuses_a_held_out_run(tmp_path, capsys) -> None:
    entries = [entry("t1", b"not an image", "bw", "tuning"), *base_entries()[1:]]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path) == 2
    assert "item-t1" in capsys.readouterr().err
    assert not reports(tmp_path / "out")


def test_unknown_annotation_fields_refuse_the_run_naming_only_the_item(tmp_path, capsys) -> None:
    bad = Entry("t1", colour_png("text"), "document", "tuning", {LABEL: {"label": "bw", "zzq": 1}})
    corpus = write_corpus(tmp_path / "corpus", [bad])
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out") == 2
    err = capsys.readouterr().err
    assert "item-t1" in err and "zzq" not in err and not (tmp_path / "out").exists()


def test_the_output_may_not_be_inside_the_corpus(corpus) -> None:
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", corpus.parent / "results") == 2
    assert not (corpus.parent / "results").exists()


def test_the_default_output_is_under_the_cache_and_the_corpus_comes_from_the_environment(
    corpus, tmp_path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("FASTFOTO_CORPUS_DIR", str(corpus.parent))
    assert run_cli(LABEL) == 0
    target = cache / "fastfoto-linux" / "calibration-eval" / LABEL / manifest_sha(corpus)[:12]
    assert len(list(target.glob("run-*/report.json"))) == 1


def test_no_corpus_directory_is_a_usage_error_that_names_the_variable(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("FASTFOTO_CORPUS_DIR", raising=False)
    assert run_cli(LABEL, "--out", tmp_path / "out") == 2
    assert "FASTFOTO_CORPUS_DIR" in capsys.readouterr().err


def test_a_one_bit_page_is_accepted(tmp_path) -> None:
    entries = [Entry("t1", bilevel_png(), "document", "tuning", note("bw"))]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out") == 0
    assert only_report(tmp_path)["metrics"]["counts"]["errored"] == 0


@pytest.mark.parametrize("pin", ["abc", "G" * 64, "F" * 64])
def test_a_malformed_pin_is_called_malformed_not_mismatched(corpus, tmp_path, capsys, pin) -> None:
    code = run_cli(
        LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out", "--expect-manifest-sha256", pin
    )
    assert code == 2 and "hexadecimal" in capsys.readouterr().err


def test_the_output_location_is_refused_before_any_item_is_read(corpus) -> None:
    with load_corpus_manifest(corpus) as manifest:
        for inside in (corpus.parent, corpus.parent / "results" / "deep"):
            with pytest.raises(ManifestError):
                resolve_out(LABEL, manifest, inside, {})


def test_skipped_held_out_items_fail_the_gate(tmp_path, capsys) -> None:
    unannotated = Entry("h9", colour_png("faint"), "document", "heldout", {})
    corpus = write_corpus(tmp_path / "corpus", [*base_entries(), unannotated])
    assert heldout(corpus, tmp_path, "--gate") == 5
    assert "skipped items" in capsys.readouterr().out
    assert only_report(tmp_path)["metrics"]["counts"]["skipped"] == 1


def test_a_gate_run_lists_the_human_criteria_that_are_pending(tmp_path, capsys) -> None:
    cast = {"wb": {"neutral_boxes": [[60, 20, 40, 20]], "cast": True}}
    entries = [Entry("t0", wb_png(True, 99), "photo", "tuning", cast)]
    entries += [Entry(f"h{i}", wb_png(True, i), "photo", "heldout", cast) for i in range(5)]
    corpus = write_corpus(tmp_path / "corpus", entries)
    code = run_cli(
        "wb", "--corpus", corpus.parent, "--out", tmp_path / "out", "--split", "heldout",
        "--expect-manifest-sha256", manifest_sha(corpus), "--gate",
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "GATE PASS" not in out
    assert "pending" in out and "ab_preference" in out


def gate_run(tmp_path: Path, feature: str, entries: list[Entry], *extra: str) -> tuple[int, dict]:
    corpus = write_corpus(tmp_path / "corpus", entries)
    code = run_cli(
        feature, "--corpus", corpus.parent, "--out", tmp_path / "out", "--split", "heldout",
        "--expect-manifest-sha256", manifest_sha(corpus), "--gate", *extra,
    )  # fmt: skip
    return code, only_report(tmp_path)["metrics"]


def test_a_deskew_gate_resolves_to_pass_or_fail_not_insufficient(tmp_path) -> None:
    pages = [(-40, 11), (25, 12), (60, 13), (-15, 14), (35, 15)]

    def entries(sign: int) -> list[Entry]:
        held = [
            Entry(f"h{i}", text_png(t, seed), "document", "heldout",
                  {"deskew": {"correction_tenths": [-t * sign]}})
            for i, (t, seed) in enumerate(pages)
        ]  # fmt: skip
        return [Entry("t0", text_png(20, 1), "document", "tuning", {}), *held]

    code, metrics = gate_run(tmp_path / "good", "deskew", entries(1))
    assert code == 0 and set(metrics["criteria"].values()) == {"pass"}
    code, metrics = gate_run(tmp_path / "bad", "deskew", entries(-1))
    assert code == 5 and metrics["criteria"]["wrong_direction"] == "fail"
    assert "insufficient_data" not in metrics["criteria"].values()


def test_a_wb_gate_resolves_the_restore_criterion(tmp_path) -> None:
    cast = {"wb": {"neutral_boxes": [[60, 20, 40, 20]], "cast": True}}
    entries = [Entry("t0", wb_png(True, 99), "photo", "tuning", cast)]
    entries += [Entry(f"h{i}", wb_png(True, i), "photo", "heldout", cast) for i in range(5)]
    code, metrics = gate_run(tmp_path, "wb", entries)
    assert metrics["criteria"]["restore_de00_improvement"] == "pass" and code == 0


def test_a_detail_gate_resolves_every_criterion(tmp_path) -> None:
    note = {"detail": DETAIL_NOTE}
    entries = [Entry("t0", detail_png(99), "photo", "tuning", note)]
    entries += [Entry(f"h{i}", detail_png(i), "photo", "heldout", note) for i in range(5)]
    code, metrics = gate_run(tmp_path, "detail", entries)
    statuses = set(metrics["criteria"].values())
    assert statuses <= {"pass", "fail"}
    assert code == (0 if statuses == {"pass"} else 5)


def test_a_grey_page_and_its_rgb_copy_are_the_same_picture_for_the_leak_check(
    tmp_path, capsys
) -> None:
    grey = grey_page()
    twin = png(np.stack([grey] * 3, axis=-1), dpi=100)
    entries = [
        entry("t1", png(grey, dpi=100), "bw", "tuning"),
        entry("h1", twin, "bw", "heldout"),
    ]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path) == 2
    err = capsys.readouterr().err
    assert "item-h1" in err and "pixel hash" in err


def test_unannotated_items_are_fingerprinted_too(tmp_path, capsys) -> None:
    grey = grey_page()
    entries = [
        Entry("t1", png(grey, dpi=100), "document", "tuning", {}),
        entry("h1", png(np.stack([grey] * 3, axis=-1), dpi=100), "bw", "heldout"),
    ]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path) == 2
    assert "item-t1" in capsys.readouterr().err


def test_a_held_out_item_that_cannot_be_fingerprinted_refuses_the_run(tmp_path, capsys) -> None:
    entries = [*base_entries(), entry("h9", b"not an image", "bw", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path) == 2
    assert "item-h9" in capsys.readouterr().err
    assert not reports(tmp_path / "out")


def test_a_hash_failure_while_measuring_refuses_the_run_and_is_not_counted(
    corpus, tmp_path, monkeypatch, capsys
) -> None:
    def refuse(manifest, item):
        raise CorpusError(f"item {item.id!r}: content does not match its sha256")

    monkeypatch.setattr(calib_run, "read_verified", refuse)
    assert run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out") == 2
    assert "item-t1" in capsys.readouterr().err
    assert not reports(tmp_path / "out")


@pytest.mark.parametrize("error", [OSError("/secret/path"), RuntimeError("/secret/path")])
def test_output_failures_end_as_a_fixed_message_without_the_path(
    corpus, tmp_path, monkeypatch, capsys, error
) -> None:
    def fail(*_args: object, **_kwargs: object) -> str:
        raise error

    monkeypatch.setattr(calib_run, "write_outputs", fail)
    code = run_cli(LABEL, "--corpus", corpus.parent, "--out", tmp_path / "out")
    err = capsys.readouterr().err
    assert code != 0 and "secret" not in err and "error" in err


def test_criteria_are_judged_before_the_report_rounds(tmp_path, monkeypatch) -> None:
    """601 of 2003 over-retained is 0.30005 > 0.30: rounding must not turn it into a pass."""

    def aggregate(rows, settings):
        return {
            "colour_loss": {"k": 0, "n": 2003, "p": 0.0},
            "over_retention": {"k": 601, "n": 2003, "p": 601 / 2003},
        }

    monkeypatch.setattr(calib_colour, "aggregate", aggregate)
    pages = [Entry(f"h{i}", text_png(10 * i, i), "document", "heldout",
                   {"autocolour": {"label": "bw"}}) for i in range(1, 6)]  # fmt: skip
    code, metrics = gate_run(tmp_path, "autocolour", [*pages])
    assert metrics["criteria"]["over_retention"] == "fail"
    assert code == 5
