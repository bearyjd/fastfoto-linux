"""The settings of the app under its old name (fastfoto-linux) are copied once to the new folder."""

import json
import logging
import os
from pathlib import Path

import pytest

from fastfoto_linux.gui import prefs
from fastfoto_linux.gui.prefs import MAX_PREFS_BYTES, load_mode, migrate_old_prefs

LOGGER = "fastfoto_linux.gui.prefs"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "config")}


def old_file(env: dict[str, str]) -> Path:
    return Path(env["XDG_CONFIG_HOME"]) / "fastfoto-linux" / "gui.json"


def new_file(env: dict[str, str]) -> Path:
    return Path(env["XDG_CONFIG_HOME"]) / "feedshot" / "gui.json"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_new_folder_is_feedshot() -> None:
    assert prefs.PREFS_DIR == "feedshot"


def test_the_old_settings_are_copied_and_the_old_file_is_kept(env: dict[str, str]) -> None:
    write(old_file(env), json.dumps({"mode": "documents", "album": "Trips"}))
    assert migrate_old_prefs(env) is True
    assert json.loads(new_file(env).read_text()) == {"mode": "documents", "album": "Trips"}
    assert json.loads(old_file(env).read_text())["album"] == "Trips"
    assert load_mode(new_file(env)).value == "documents"


def test_it_works_without_xdg_config_home(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path)}
    write(tmp_path / ".config" / "fastfoto-linux" / "gui.json", '{"mode": "documents"}')
    assert migrate_old_prefs(env) is True
    assert (tmp_path / ".config" / "feedshot" / "gui.json").is_file()


def test_new_settings_are_never_overwritten(env: dict[str, str]) -> None:
    write(old_file(env), '{"album": "old"}')
    write(new_file(env), '{"album": "new"}')
    assert migrate_old_prefs(env) is False
    assert json.loads(new_file(env).read_text()) == {"album": "new"}


def test_a_dangling_symlink_in_place_of_the_new_file_is_never_replaced(
    env: dict[str, str],
) -> None:
    write(old_file(env), '{"album": "old"}')
    new_file(env).parent.mkdir(parents=True)
    new_file(env).symlink_to(new_file(env).parent / "missing.json")
    assert migrate_old_prefs(env) is False
    assert new_file(env).is_symlink() and not new_file(env).exists()


def test_nothing_happens_without_old_settings(env: dict[str, str]) -> None:
    assert migrate_old_prefs(env) is False
    assert not new_file(env).parent.exists()


def test_it_happens_once(env: dict[str, str]) -> None:
    write(old_file(env), '{"album": "old"}')
    assert migrate_old_prefs(env) is True
    new_file(env).write_text('{"album": "edited"}')
    assert migrate_old_prefs(env) is False
    assert json.loads(new_file(env).read_text()) == {"album": "edited"}


@pytest.mark.parametrize("text", ["not json", "[1, 2]", "[" * 100000])
def test_an_unusable_old_file_is_not_copied(
    env: dict[str, str], text: str, caplog: pytest.LogCaptureFixture
) -> None:
    write(old_file(env), text)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert migrate_old_prefs(env) is False
    assert not new_file(env).exists()
    assert caplog.records


def test_an_oversize_old_file_is_not_copied(env: dict[str, str]) -> None:
    write(old_file(env), '{"album": "' + "x" * MAX_PREFS_BYTES + '"}')
    assert migrate_old_prefs(env) is False
    assert not new_file(env).exists()


def test_a_pipe_in_place_of_the_old_file_is_not_read(env: dict[str, str]) -> None:
    old_file(env).parent.mkdir(parents=True)
    os.mkfifo(old_file(env))
    assert migrate_old_prefs(env) is False
    assert not new_file(env).exists()


def test_a_link_to_a_regular_file_is_read_like_the_loader_does(
    env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "dotfiles" / "gui.json"
    write(target, '{"album": "linked"}')
    old_file(env).parent.mkdir(parents=True)
    old_file(env).symlink_to(target)
    assert migrate_old_prefs(env) is True
    assert not new_file(env).is_symlink()
    assert json.loads(new_file(env).read_text()) == {"album": "linked"}


def test_a_failed_write_is_logged_and_not_fatal(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    write(old_file(env), '{"album": "old"}')
    config = Path(env["XDG_CONFIG_HOME"])
    config.chmod(0o500)
    try:
        if os.access(config, os.W_OK):
            pytest.skip("permissions are not enforced here")
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            assert migrate_old_prefs(env) is False
    finally:
        config.chmod(0o700)
    assert any("could not copy" in record.getMessage() for record in caplog.records)
    assert old_file(env).is_file()
