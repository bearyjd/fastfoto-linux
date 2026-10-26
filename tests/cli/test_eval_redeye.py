"""``ffscan eval redeye``: arguments, exit codes and what lands on disk."""

import json
import re
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_eval, main
from fastfoto_linux.evaluation.redeye_manifest import load_manifest
from tests.redeye_eval.synth import (
    KeyedDetector,
    SynthItem,
    clean_heldout_set,
    positive,
    with_split,
    write_corpus,
)

UNIQUE = "uniq-corpus-77c1"


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    items = clean_heldout_set()
    path = write_corpus(tmp_path / UNIQUE, items)
    monkeypatch.setattr(cmd_eval, "make_detector", lambda: KeyedDetector(items))
    return path, items, load_manifest(path).sha256


def test_help_lists_the_eval_command(capsys) -> None:
    assert main(["eval", "redeye", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--gate" in out and "--expect-manifest-sha256" in out and "--no-perf" in out


def test_a_tuning_run_writes_the_three_files_outside_the_corpus(corpus, tmp_path) -> None:
    path, _, _ = corpus
    out = tmp_path / "results"
    assert main(["eval", "redeye", str(path), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["perf.json", "report.json", "summary.md"]
    assert json.loads((out / "report.json").read_text())["split"] == "tuning"
    assert (out.stat().st_mode & 0o777) == 0o700


def test_no_perf_skips_perf_json(corpus, tmp_path) -> None:
    out = tmp_path / "results"
    assert main(["eval", "redeye", str(corpus[0]), "--out", str(out), "--no-perf"]) == 0
    assert not (out / "perf.json").exists()


def test_the_default_out_dir_is_the_cache(corpus, tmp_path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    assert main(["eval", "redeye", str(corpus[0]), "--no-perf"]) == 0
    assert (cache / "fastfoto-linux" / "redeye-eval" / corpus[2][:12] / "report.json").is_file()


def test_gate_needs_heldout_and_a_frozen_manifest_hash(corpus, tmp_path, capsys) -> None:
    path, _, sha = corpus
    out = str(tmp_path / "r")
    assert main(["eval", "redeye", str(path), "--out", out, "--gate"]) == 2
    assert main(["eval", "redeye", str(path), "--out", out, "--gate", "--split", "heldout"]) == 2
    assert (
        main(
            [
                "eval",
                "redeye",
                str(path),
                "--out",
                out,
                "--split",
                "tuning",
                "--gate",
                "--expect-manifest-sha256",
                sha,
            ]
        )
        == 2
    )
    assert not Path(out).exists()


def test_a_passing_gate_exits_zero(corpus, tmp_path, capsys) -> None:
    path, _, sha = corpus
    args = [
        "eval",
        "redeye",
        str(path),
        "--out",
        str(tmp_path / "r"),
        "--split",
        "heldout",
        "--gate",
        "--expect-manifest-sha256",
        sha,
        "--no-perf",
    ]
    assert main(args) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_failing_gate_exits_five_and_still_writes_the_report(
    tmp_path, monkeypatch, capsys
) -> None:
    base = positive("planted")
    box = [100, 90, 220, 110]
    items = [
        *clean_heldout_set(),
        with_split(
            SynthItem("planted", base.arr, [], [{"category": "lips", "box": box}], base.detections),
            "heldout",
        ),
    ]
    path = write_corpus(tmp_path / "c", items)
    monkeypatch.setattr(cmd_eval, "make_detector", lambda: KeyedDetector(items))
    out = tmp_path / "r"
    args = [
        "eval",
        "redeye",
        str(path),
        "--out",
        str(out),
        "--split",
        "heldout",
        "--gate",
        "--expect-manifest-sha256",
        load_manifest(path).sha256,
        "--no-perf",
    ]
    assert main(args) == 5
    assert "G1" in capsys.readouterr().out
    assert (out / "report.json").is_file()


def test_a_wrong_expected_hash_exits_five(corpus, tmp_path) -> None:
    args = [
        "eval",
        "redeye",
        str(corpus[0]),
        "--out",
        str(tmp_path / "r"),
        "--split",
        "heldout",
        "--gate",
        "--expect-manifest-sha256",
        "0" * 64,
    ]
    assert main(args) == 5


def test_usage_errors_exit_two_with_one_line(tmp_path, capsys) -> None:
    assert main(["eval", "redeye", str(tmp_path / "missing.json")]) == 2
    assert "error" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert main(["eval", "redeye", str(bad), "--out", str(tmp_path / "r")]) == 2


def test_out_inside_the_corpus_is_refused(corpus) -> None:
    path = corpus[0]
    assert main(["eval", "redeye", str(path), "--out", str(path.parent / "results")]) == 2


def test_a_leaking_heldout_run_exits_two(tmp_path, monkeypatch) -> None:
    held = with_split(positive("held"), "heldout")
    twin = SynthItem("twin", held.arr.copy(), held.faces, [], held.detections)
    path = write_corpus(tmp_path / "c", [held, twin], splits={"held": "heldout", "twin": "tuning"})
    monkeypatch.setattr(cmd_eval, "make_detector", lambda: KeyedDetector([held]))
    args = ["eval", "redeye", str(path), "--out", str(tmp_path / "r"), "--split", "heldout"]
    assert main(args) == 2


def test_stdout_never_prints_a_path(corpus, tmp_path, capsys) -> None:
    main(["eval", "redeye", str(corpus[0]), "--out", str(tmp_path / "r"), "--no-perf"])
    out = capsys.readouterr().out
    assert UNIQUE not in out and not re.search(r"\.png", out)
