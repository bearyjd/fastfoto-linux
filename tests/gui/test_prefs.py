import json
import logging
import os
import stat
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.prefs import PREFS_DIR, PREFS_FILE, load_form, prefs_path, save_form

LOGGER = "fastfoto_linux.gui.prefs"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config" / PREFS_DIR / PREFS_FILE


CUSTOM = ScanForm(
    output_folder="/srv/demo/FastFoto",
    album="Family Trips",
    feed="face-up",
    backs="always",
    restore=False,
    orient=False,
    redeye=True,
    dpi=300,
    keep_original=False,
)


def test_the_file_lives_in_the_xdg_config_folder() -> None:
    assert prefs_path({"XDG_CONFIG_HOME": "/x/config", "HOME": "/h"}) == Path(
        "/x/config/fastfoto-linux/gui.json"
    )


@pytest.mark.parametrize("env", [{"HOME": "/h"}, {"HOME": "/h", "XDG_CONFIG_HOME": ""}])
def test_without_xdg_config_home_it_is_dot_config(env: dict[str, str]) -> None:
    assert prefs_path(env) == Path("/h/.config/fastfoto-linux/gui.json")


def test_a_saved_form_comes_back(path: Path) -> None:
    save_form(CUSTOM, path)
    assert load_form(path) == CUSTOM


def test_the_date_and_notes_belong_to_one_batch_and_are_not_remembered(path: Path) -> None:
    save_form(replace(CUSTOM, date="1975-06", notes="Summer"), path)
    saved = json.loads(path.read_text())
    assert "date" not in saved
    assert "notes" not in saved
    assert load_form(path) == CUSTOM


def test_a_missing_file_gives_the_defaults_quietly(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_form(path) == ScanForm()
    assert caplog.records == []


@pytest.mark.parametrize("content", ["{not json", "", "[1, 2]", '"text"', "null"])
def test_a_corrupt_file_gives_the_defaults_and_a_warning(
    path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_form(path) == ScanForm()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert str(path) in caplog.records[0].getMessage()


def test_unknown_keys_are_ignored(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"album": "Rome", "theme": "dark", "dpi": 300}))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_form(path) == ScanForm(album="Rome", dpi=300)
    assert caplog.records == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("dpi", "fast"),
        ("dpi", 123),
        ("dpi", True),
        ("feed", "sideways"),
        ("backs", 3),
        ("redeye", "yes"),
        ("album", ["a"]),
        ("output_folder", None),
    ],
)
def test_a_bad_value_costs_only_its_own_field(
    path: Path, key: str, value: object, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**vars_of(CUSTOM), key: value}))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        loaded = load_form(path)
    assert getattr(loaded, key) == getattr(ScanForm(), key)
    others = {k: v for k, v in vars_of(CUSTOM).items() if k != key}
    assert {k: getattr(loaded, k) for k in others} == others
    assert key in caplog.text


def vars_of(form: ScanForm) -> dict[str, object]:
    return {k: v for k, v in asdict(form).items() if k not in ("date", "notes")}


def test_saving_creates_the_folder_and_leaves_no_temporary_file(path: Path) -> None:
    save_form(CUSTOM, path)
    assert [entry.name for entry in path.parent.iterdir()] == [PREFS_FILE]


def test_the_file_is_private_to_the_user(path: Path) -> None:
    save_form(CUSTOM, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_failed_write_keeps_the_old_file_and_cleans_up(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_form(CUSTOM, path)

    def broken(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        save_form(replace(CUSTOM, album="Other"), path)
    monkeypatch.undo()
    assert load_form(path) == CUSTOM
    assert [entry.name for entry in path.parent.iterdir()] == [PREFS_FILE]


def test_saving_twice_replaces_the_content(path: Path) -> None:
    save_form(CUSTOM, path)
    save_form(replace(CUSTOM, album="Other"), path)
    assert load_form(path).album == "Other"
