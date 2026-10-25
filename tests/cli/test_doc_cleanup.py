"""``--cleanup off|light|strong`` of ``ffscan doc``: the option, its settings, its errors."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.cli.app import build_parser
from fastfoto_linux.cli.doc_options import build_settings
from fastfoto_linux.documents.modes import CleanupPolicy
from tests.cli.doc_cleanup_helpers import shaded_pages

pytestmark = pytest.mark.usefixtures("no_real_ocr")

PROCESS = ["doc", "process", "x.png", "--out", "o"]
SCAN = ["doc", "scan", "--out", "o"]


def settings_of(argv: list[str]):
    return build_settings(build_parser().parse_args(argv))


@pytest.mark.parametrize(
    ("extra", "level"),
    [
        ([], CleanupPolicy.OFF),
        (["--cleanup", "off"], CleanupPolicy.OFF),
        (["--cleanup", "light"], CleanupPolicy.LIGHT),
        (["--cleanup", "strong"], CleanupPolicy.STRONG),
    ],
)
@pytest.mark.parametrize("base", [PROCESS, SCAN], ids=["process", "scan"])
def test_the_flag_sets_the_document_level_and_not_given_is_off(base, extra, level) -> None:
    assert settings_of([*base, *extra]).cleanup is level


def test_not_given_is_not_the_same_as_off() -> None:
    parse = build_parser().parse_args
    assert parse([*PROCESS]).cleanup is None
    assert parse([*PROCESS, "--cleanup", "off"]).cleanup == "off"


@pytest.mark.parametrize("value", ["medium", "Light", "STRONG", ""])
@pytest.mark.parametrize("base", [PROCESS, SCAN], ids=["process", "scan"])
def test_a_bad_level_is_exit_2(base, value, capsys) -> None:
    assert main([*base, "--cleanup", value]) == 2
    err = capsys.readouterr().err
    assert "--cleanup" in err
    assert "invalid choice" in err


def test_the_choices_message_names_the_three_levels(capsys) -> None:
    assert main([*PROCESS, "--cleanup", "medium"]) == 2
    assert "choose from off, light, strong" in capsys.readouterr().err.replace("'", "")


def test_a_bad_level_is_refused_before_any_page_is_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "o").mkdir()
    shaded_pages(tmp_path)[0].rename(tmp_path / "x.png")
    assert main([*PROCESS, "--cleanup", "medium"]) == 2
    assert not list((tmp_path / "o").iterdir())


@pytest.mark.parametrize("command", ["process", "scan"])
def test_the_help_lists_the_flag(command, capsys) -> None:
    assert main(["doc", command, "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "--cleanup {off,light,strong}" in text
    assert "paper cleanup: off, light or strong lightens the paper tone" in text
    assert "black and white pages are not changed" in text
