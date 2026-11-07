"""The run contract: pin, held-out refusal, leak check, gate exit code, output location."""

import json
from pathlib import Path

import pytest

from tests.calibration.synth import (
    AUTO_DPI,
    Entry,
    bilevel_png,
    colour_png,
    manifest_sha,
    png,
    reports,
    run_cli,
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
        entry("h2", colour_png("gradient"), "grey", "heldout"),
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


def test_a_passing_gate_exits_zero_and_records_every_criterion(corpus, tmp_path, capsys) -> None:
    assert heldout(corpus, tmp_path, "--gate") == 0
    assert "GATE PASS" in capsys.readouterr().out
    metrics = only_report(tmp_path)["metrics"]
    assert metrics["criteria"] == {"colour_loss_zero": "pass", "over_retention": "pass"}
    assert metrics["counts"]["n"] == 2 and metrics["counts"]["errored"] == 0


def test_a_failing_criterion_exits_five_but_still_writes_the_report(tmp_path, capsys) -> None:
    entries = [*base_entries(), entry("h3", colour_png("faint"), "colour", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)  # a grey result for a colour label
    assert heldout(corpus, tmp_path, "--gate") == 5
    assert "GATE FAIL" in capsys.readouterr().out
    assert only_report(tmp_path)["metrics"]["criteria"]["colour_loss_zero"] == "fail"


def test_over_retention_above_the_limit_fails_the_gate(tmp_path) -> None:
    entries = [*base_entries(), entry("h3", colour_png("sepia"), "bw", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)  # 1 of 3 kept more than needed
    assert heldout(corpus, tmp_path, "--gate") == 5
    assert only_report(tmp_path)["metrics"]["criteria"]["over_retention"] == "fail"


def test_an_errored_held_out_item_fails_the_gate_however_good_the_rest(tmp_path) -> None:
    entries = [*base_entries(), entry("h3", b"not an image", "bw", "heldout")]
    corpus = write_corpus(tmp_path / "corpus", entries)
    assert heldout(corpus, tmp_path, "--gate") == 5
    counts = only_report(tmp_path)["metrics"]["counts"]
    assert counts["errored"] == 1 and counts["n"] == 3


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
