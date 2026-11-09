"""install-desktop.sh removes an install made under the old name (fastfoto-linux), only what it can
prove is its own: recorded in the old installed.txt, or a link into the old environment."""

from pathlib import Path

import pytest

from tests.gui import test_install_script as script

run, tree = script.run, script.tree
checkout, env, home = script.checkout, script.env, script.home  # the fixtures, shared

OLD_ID = "io.github.bearyjd.FastFotoLinux"
OLD_SHIM = "ff680w_usb_gap.so"


class OldInstall:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.data = home / ".local" / "share" / "fastfoto-linux"
        self.venv = self.data / "venv"
        self.record = self.data / "installed.txt"
        self.bin = home / ".local" / "bin"
        self.desktop = home / ".local" / "share" / "applications" / f"{OLD_ID}.desktop"
        self.icon = home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
        self.icon = self.icon / f"{OLD_ID}.svg"
        self.lib = home / ".local" / "lib" / "fastfoto-linux"
        self.tessdata = self.data / "tessdata" / "rev1" / "eng.traineddata"

    def create(self, *, record: bool = True, links: bool = True) -> None:
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        for name in ("python", "fastfoto", "ffscan"):
            (self.venv / "bin" / name).write_text("#!/bin/sh\n")
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text("[Desktop Entry]\n")
        self.icon.parent.mkdir(parents=True)
        self.icon.write_text("<svg/>")
        self.lib.mkdir(parents=True)
        (self.lib / OLD_SHIM).write_text("shim")
        self.tessdata.parent.mkdir(parents=True)
        self.tessdata.write_text("data")
        if record:
            self.record.write_text(f"{self.lib / OLD_SHIM}\n{self.desktop}\n{self.icon}\n")
        if links:
            self.bin.mkdir(parents=True, exist_ok=True)
            for name in ("fastfoto", "ffscan"):
                (self.bin / name).symlink_to(self.venv / "bin" / name)


@pytest.fixture
def old(home: Path) -> OldInstall:
    return OldInstall(home)


def test_an_old_install_is_removed_when_the_new_one_goes_in(
    checkout: Path,
    env: dict[str, str],
    home: Path,
    old: OldInstall,
) -> None:
    old.create()
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert not old.venv.exists()
    assert not old.desktop.exists()
    assert not old.icon.exists()
    assert not (old.bin / "fastfoto").exists() and not (old.bin / "fastfoto").is_symlink()
    assert (old.bin / "feedshot").is_symlink()
    # ffscan is kept, and now points at the new environment
    assert (old.bin / "ffscan").readlink() == home / ".local/share/feedshot/venv/bin/ffscan"
    assert "removed" in done.stdout


def test_the_old_tessdata_and_shim_folder_are_left_alone_with_a_note(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create()
    done = run(checkout, env)
    assert old.tessdata.read_text() == "data"
    assert (old.lib / OLD_SHIM).read_text() == "shim"
    assert "fastfoto-linux" in done.stdout
    assert "not moved" in done.stdout


def test_a_dry_run_lists_the_old_removals_and_changes_nothing(
    checkout: Path,
    env: dict[str, str],
    home: Path,
    old: OldInstall,
) -> None:
    old.create()
    before = tree(home)
    done = run(checkout, env, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert f"would remove old environment {old.venv}" in done.stdout
    assert f"would remove old launcher {old.desktop}" in done.stdout
    assert f"would remove old icon {old.icon}" in done.stdout
    assert f"would remove old link {old.bin / 'fastfoto'}" in done.stdout
    assert tree(home) == before
    assert all(line.startswith("would ") for line in done.stdout.splitlines())


def test_without_the_old_record_only_the_links_into_the_old_environment_go(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create(record=False)
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert not old.venv.exists()  # a link into it proves it is ours
    assert old.desktop.exists()  # not recorded: not provably ours
    assert old.icon.exists()


def test_without_record_or_links_nothing_old_is_removed(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create(record=False, links=False)
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert old.venv.is_dir()
    assert old.desktop.exists()
    assert old.icon.exists()


def test_a_foreign_launcher_with_the_old_name_is_not_touched(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create(links=False)
    old.bin.mkdir(parents=True)
    (old.bin / "fastfoto").write_text("someone else's")
    other = old.bin / "ffscan"
    other.symlink_to("/usr/bin/true")
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert (old.bin / "fastfoto").read_text() == "someone else's"
    assert other.readlink() == Path("/usr/bin/true")
    assert "leaving" in done.stderr


def test_a_recorded_path_that_is_not_ours_by_name_is_not_removed(
    checkout: Path,
    env: dict[str, str],
    home: Path,
    old: OldInstall,
) -> None:
    """Only the exact desktop entry and icon of the old installer go, whatever else is listed."""
    old.create()
    precious = home / "precious.txt"
    precious.write_text("mine")
    old.record.write_text(old.record.read_text() + f"{precious}\n")
    assert run(checkout, env).returncode == 0
    assert precious.read_text() == "mine"


def test_an_old_environment_folder_without_pyvenv_cfg_is_not_removed(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create()
    (old.venv / "pyvenv.cfg").unlink()
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert old.venv.is_dir()
    assert f"leaving {old.venv} alone" in done.stderr


def test_running_again_finds_nothing_more_to_clean(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create()
    assert run(checkout, env).returncode == 0
    again = run(checkout, env)
    assert again.returncode == 0, again.stderr
    assert "would" not in again.stdout
    assert "removed old" not in again.stdout


def test_uninstall_does_not_clean_the_old_install(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create()
    assert run(checkout, env, "--uninstall").returncode == 0
    assert old.venv.is_dir()
    assert old.desktop.exists()


def test_an_old_environment_folder_without_a_python_is_not_removed(
    checkout: Path,
    env: dict[str, str],
    old: OldInstall,
) -> None:
    old.create()
    (old.venv / "bin" / "python").unlink()
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert old.venv.is_dir()
    assert f"leaving {old.venv} alone" in done.stderr
