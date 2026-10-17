"""How command-line flags turn into ``ProcessSettings`` (defaults included)."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.enhance.orient import auto_orient
from fastfoto_linux.enhance.redeye import remove_red_eye
from fastfoto_linux.enhance.restore import restore_colour
from fastfoto_linux.output import PhotoDate
from fastfoto_linux.pipeline.process import ProcessSettings
from fastfoto_linux.pipeline.sides import BackPolicy
from tests.cli.fakes import write_dummy_page


@pytest.fixture
def settings_of(tmp_path, out, spy):
    def run(*extra: str) -> ProcessSettings:
        page = write_dummy_page(tmp_path / "raw", "page-1.png")
        assert main(["process", str(page), "--out", str(out), *extra]) == 0
        return spy[-1][1]

    return run


def test_the_defaults(settings_of, out) -> None:
    settings = settings_of()
    assert settings.output_root == out
    assert settings.album is None
    assert settings.prefix is None
    assert settings.date is None
    assert settings.notes is None
    assert settings.duplex is True
    assert settings.back_policy is BackPolicy.AUTO
    assert settings.expect_front_first is False  # photos face up, top edge first: back first
    assert settings.quality == 95
    assert settings.keep_original is True
    assert settings.orienter is auto_orient
    assert settings.enhancers == (restore_colour,)  # red-eye is opt-in (about 17% visible damage)


def test_face_up_is_the_default_and_means_the_back_comes_first(settings_of) -> None:
    assert settings_of("--feed", "face-up").expect_front_first is False


def test_face_down_means_the_front_comes_first(settings_of) -> None:
    assert settings_of("--feed", "face-down").expect_front_first is True


def test_the_feed_help_says_which_side_each_loading_scans_first(capsys) -> None:
    assert main(["process", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert (
        "how photos were loaded (top edge first): face-up scans the back first (default); "
        "face-down scans the front first"
    ) in text


def test_every_value_option(settings_of) -> None:
    settings = settings_of(
        "--album",
        "Family Trip",
        "--date",
        "1975-06-14",
        "--notes",
        "Lake house",
        "--prefix",
        "Trip",
        "--quality",
        "80",
        "--backs",
        "always",
        "--simplex",
        "--enhanced-only",
    )
    assert settings.album == "Family Trip"
    assert settings.date == PhotoDate(1975, 6, 14)
    assert settings.notes == "Lake house"
    assert settings.prefix == "Trip"
    assert settings.quality == 80
    assert settings.back_policy is BackPolicy.ALWAYS
    assert settings.duplex is False
    assert settings.keep_original is False


@pytest.mark.parametrize(
    ("text", "date"),
    [
        ("1975", PhotoDate(1975)),
        ("1975-06", PhotoDate(1975, 6)),
        ("1975-06-14", PhotoDate(1975, 6, 14)),
    ],
)
def test_date_precision(settings_of, text, date) -> None:
    assert settings_of("--date", text).date == date


def test_the_enhancement_switches(settings_of) -> None:
    assert settings_of("--no-orient").orienter is None
    assert settings_of("--no-restore").enhancers == ()
    assert settings_of("--redeye").enhancers == (restore_colour, remove_red_eye)  # restore first
    assert settings_of("--redeye", "--no-restore").enhancers == (remove_red_eye,)
    assert settings_of("--no-redeye").enhancers == (restore_colour,)


def test_keep_original_is_the_explicit_spelling_of_the_default(settings_of) -> None:
    assert settings_of("--keep-original").keep_original is True


def test_the_output_folder_is_a_path(settings_of) -> None:
    assert isinstance(settings_of().output_root, Path)
