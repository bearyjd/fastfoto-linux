import os
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_scan
from fastfoto_linux.cli.app import build_parser
from fastfoto_linux.cli.options import build_settings
from fastfoto_linux.enhance.orient import auto_orient
from fastfoto_linux.enhance.redeye import remove_red_eye
from fastfoto_linux.enhance.restore import restore_colour
from fastfoto_linux.gui.form import (
    BACK_CHOICES,
    FEED_CHOICES,
    FIELD_NAMES,
    FormInvalidError,
    ScanForm,
    absolute_folder,
    destination,
    parse_date,
    to_request,
    to_settings,
    update_field,
    validate,
    validate_filesystem,
    validate_syntax,
)
from fastfoto_linux.output import DateRange, PhotoDate
from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.scanner import SUPPORTED_DPI, ScanTarget
from fastfoto_linux.session import RawPolicy
from tests.cli.fakes import DEVICE

TARGET = ScanTarget(device=DEVICE)


@pytest.fixture
def form(out: Path) -> ScanForm:
    return ScanForm(output_folder=str(out))


def cli_namespace(out: Path, *options: str):
    return build_parser().parse_args(["scan", "--out", str(out), *options])


def test_default_form_makes_the_request_ffscan_scan_makes(out: Path, form: ScanForm) -> None:
    args = cli_namespace(out)
    request = to_request(form, TARGET)
    assert request.settings == build_settings(args)
    assert request.dpi == args.dpi
    assert request.duplex is (not args.simplex)
    assert request.raw_policy is cmd_scan._raw_policy(args) is RawPolicy.AUTO
    assert request.raw_root == out
    assert request.target is TARGET


def test_every_option_the_form_has_maps_like_the_command_line(out: Path, form: ScanForm) -> None:
    args = cli_namespace(
        out,
        *("--album", "Family Trips", "--date", "1975-06", "--notes", "Summer"),
        *("--backs", "always", "--feed", "face-up", "--no-restore", "--redeye", "--no-orient"),
        *("--enhanced-only", "--dpi", "300"),
    )
    filled = replace(
        form,
        album="Family Trips",
        date="1975-06",
        notes="Summer",
        backs="always",
        feed="face-up",
        restore=False,
        redeye=True,
        orient=False,
        keep_original=False,
        dpi=300,
    )
    request = to_request(filled, TARGET)
    assert request.settings == build_settings(args)
    assert request.dpi == 300


def test_toggles_pick_the_processing_steps(form: ScanForm) -> None:
    both = to_settings(replace(form, restore=True, redeye=True))
    assert both.enhancers == (restore_colour, remove_red_eye)
    assert both.orienter is auto_orient
    none = to_settings(replace(form, restore=False, redeye=False, orient=False))
    assert none.enhancers == ()
    assert none.orienter is None


def test_feed_and_backs_reach_the_settings(form: ScanForm) -> None:
    face_up = to_settings(replace(form, feed="face-up", backs="never"))
    assert face_up.expect_front_first is True
    assert face_up.back_policy is BackPolicy.NEVER
    assert to_settings(form).expect_front_first is False


def test_blank_texts_mean_none(form: ScanForm) -> None:
    settings = to_settings(replace(form, album="  ", date=" ", notes=""))
    assert (settings.album, settings.date, settings.notes) == (None, None, None)


def test_a_valid_form_has_no_errors(form: ScanForm) -> None:
    assert validate(form) == {}


def test_the_choices_match_the_command_line() -> None:
    assert set(FEED_CHOICES) == {"face-down", "face-up"}
    assert set(BACK_CHOICES) == {policy.value for policy in BackPolicy}
    assert set(FIELD_NAMES) >= {"output_folder", "album", "date", "notes", "dpi"}


def test_an_empty_output_folder_is_an_error() -> None:
    assert list(validate(ScanForm())) == ["output_folder"]


def test_a_missing_output_folder_is_an_error(tmp_path: Path) -> None:
    errors = validate(ScanForm(output_folder=str(tmp_path / "nope")))
    assert "does not exist" in errors["output_folder"]


def test_a_file_is_not_an_output_folder(tmp_path: Path) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    assert "not a folder" in validate(ScanForm(output_folder=str(plain)))["output_folder"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_folder_that_cannot_be_written_is_an_error(out: Path, form: ScanForm) -> None:
    out.chmod(0o500)
    try:
        assert "cannot write" in validate(form)["output_folder"]
    finally:
        out.chmod(0o700)


def test_a_leading_tilde_means_the_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Scans").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    assert validate(ScanForm(output_folder="~/Scans")) == {}
    assert to_settings(ScanForm(output_folder="~/Scans")).output_root == tmp_path / "Scans"


@pytest.mark.parametrize("album", ["..", "///", " . "])
def test_an_album_with_no_usable_characters_is_an_error(form: ScanForm, album: str) -> None:
    assert "album" in validate(replace(form, album=album))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("  ", None),
        ("1975", PhotoDate(1975)),
        ("1975-06", PhotoDate(1975, 6)),
        (" 1975-06-14 ", PhotoDate(1975, 6, 14)),
        ("1970/1979", DateRange(PhotoDate(1970), PhotoDate(1979))),
    ],
)
def test_dates_are_a_day_a_month_a_year_or_a_range(text: str, expected: object) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["June 1975", "1975-13", "1975-02-30", "1979/1970", "1970/"])
def test_a_bad_date_is_an_error_naming_the_field(form: ScanForm, text: str) -> None:
    assert "date" in validate(replace(form, date=text))


def test_notes_have_a_length_limit(form: ScanForm) -> None:
    assert "notes" in validate(replace(form, notes="x" * 10_001))
    assert "notes" not in validate(replace(form, notes="x" * 10_000))


def test_unsupported_choices_are_errors(form: ScanForm) -> None:
    bad = replace(form, dpi=123, feed="sideways", backs="maybe")
    assert set(validate(bad)) == {"dpi", "feed", "backs"}
    assert all(dpi in SUPPORTED_DPI for dpi in (300, 600))


def test_all_the_errors_come_together(out: Path) -> None:
    errors = validate(ScanForm(output_folder=str(out / "x"), date="soon", album=".."))
    assert set(errors) == {"output_folder", "date", "album"}


def test_an_invalid_form_cannot_make_a_request() -> None:
    with pytest.raises(FormInvalidError) as caught:
        to_request(ScanForm(date="soon"), TARGET)
    assert set(caught.value.errors) == {"output_folder", "date"}
    with pytest.raises(FormInvalidError):
        to_settings(ScanForm())


def test_the_destination_shows_the_sanitised_album_folder(out: Path, form: ScanForm) -> None:
    shown = destination(replace(form, album="Trips/2019: Rome"))
    assert shown is not None
    assert str(out.resolve() / "Trips 2019: Rome") in shown
    assert "Trips 2019: Rome_####.jpg" in shown


def test_the_destination_without_an_album_is_the_output_folder(out: Path, form: ScanForm) -> None:
    shown = destination(form)
    assert shown is not None
    assert str(out.resolve()) in shown
    assert "FastFoto_####.jpg" in shown


def test_the_destination_is_unknown_for_a_bad_folder_or_album(out: Path, form: ScanForm) -> None:
    assert destination(ScanForm()) is None
    assert destination(replace(form, album="..")) is None


def test_update_field_returns_a_new_form_with_the_value_coerced(form: ScanForm) -> None:
    changed = update_field(form, "dpi", 300.0)
    assert changed.dpi == 300
    assert form.dpi == 600
    assert update_field(form, "redeye", True).redeye is True
    assert update_field(form, "album", "Rome").album == "Rome"
    assert update_field(form, "restore", 0).restore is False


def test_update_field_rejects_unknown_names_and_values(form: ScanForm) -> None:
    with pytest.raises(ValueError, match="no field"):
        update_field(form, "colour", "red")
    with pytest.raises(ValueError, match="dpi"):
        update_field(form, "dpi", "fast")


def test_the_destination_never_promises_a_number_the_folder_has_already_used(
    out: Path, form: ScanForm
) -> None:
    for number in (1, 2, 3):
        (out / f"FastFoto_{number:04d}.jpg").write_bytes(b"")
    shown = destination(form)
    assert shown is not None
    assert "_0001" not in shown
    assert shown.endswith("FastFoto_####.jpg")


# -- a relative output folder is not a place (item 6) ------------------------------------------


@pytest.mark.parametrize("text", ["photos", "./photos", "../photos", "a/b"])
def test_a_relative_output_folder_is_rejected_with_a_hint(
    text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "photos").mkdir()
    (tmp_path / "a" / "b").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    errors = validate(ScanForm(output_folder=text))
    assert "full path" in errors["output_folder"]
    assert destination(ScanForm(output_folder=text)) is None
    with pytest.raises(FormInvalidError):
        to_settings(ScanForm(output_folder=text))


def test_a_home_relative_folder_is_a_full_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Pictures").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    assert validate(ScanForm(output_folder="~/Pictures")) == {}
    assert to_settings(ScanForm(output_folder="~/Pictures")).output_root == tmp_path / "Pictures"


# -- editing checks the text only; the disk is looked at when the user is done (item 11) -------


def test_syntax_validation_never_touches_the_filesystem(
    form: ScanForm, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []

    def watch(owner: object, name: str) -> None:
        original = getattr(owner, name)

        def watched(*args: object, **kwargs: object) -> object:
            reads.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, watched)

    watch(os, "access")
    for method in ("exists", "is_dir", "stat"):
        watch(Path, method)
    assert validate_syntax(replace(form, album="Rome", date="1975")) == {}
    assert validate_syntax(ScanForm(output_folder="/no/such/folder")) == {}
    problems = validate_syntax(ScanForm(date="soon", output_folder="x"))
    assert set(problems) == {"output_folder", "date"}
    assert destination(replace(form, album="Rome")) is not None
    assert reads == []


def test_syntax_validation_asks_for_a_folder_and_checks_album_date_and_notes() -> None:
    errors = validate_syntax(ScanForm(album="..", date="soon", notes="x" * 100_000))
    assert set(errors) == {"output_folder", "album", "date", "notes"}


def test_filesystem_validation_finds_a_missing_or_unwritable_folder(
    tmp_path: Path, form: ScanForm
) -> None:
    assert validate_filesystem(form) == {}
    assert (
        "does not exist"
        in validate_filesystem(replace(form, output_folder=str(tmp_path / "gone")))["output_folder"]
    )
    plain_file = tmp_path / "file"
    plain_file.write_text("x")
    assert (
        "not a folder"
        in validate_filesystem(replace(form, output_folder=str(plain_file)))["output_folder"]
    )


def test_filesystem_validation_leaves_what_the_text_check_already_rejected(
    tmp_path: Path,
) -> None:
    assert validate_filesystem(ScanForm(output_folder="relative")) == {}
    assert validate_filesystem(ScanForm()) == {}


def test_the_full_validation_is_both_checks(tmp_path: Path, form: ScanForm) -> None:
    gone = replace(form, output_folder=str(tmp_path / "gone"), date="soon")
    assert set(validate(gone)) == {"output_folder", "date"}
    assert validate(gone) == {**validate_filesystem(gone), **validate_syntax(gone)}


def test_a_home_folder_that_does_not_exist_is_a_field_error_not_a_crash() -> None:
    form = ScanForm(output_folder="~no-such-user-zzq/photos")
    assert "output_folder" in validate_syntax(form)
    assert "output_folder" in validate(form)
    assert destination(form) is None
    assert absolute_folder(form.output_folder) == ""
