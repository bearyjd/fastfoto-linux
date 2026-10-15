"""tools/install-desktop.sh, run with a throwaway HOME and stand-ins for python, pip and make."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.bearyjd.FastFotoLinux"
SHIM = "ff680w_usb_gap.so"

STUB_PYTHON = """#!/bin/sh
# Stands in for /usr/bin/python3: only `-m venv --system-site-packages DIR` is supported.
[ "$1 $2 $3" = "-m venv --system-site-packages" ] || { echo "unexpected: $*" >&2; exit 64; }
mkdir -p "$4/bin"
cat > "$4/bin/python" <<'INNER'
#!/bin/sh
# Stands in for the venv's python: `-m pip install ...` leaves the two console scripts.
dir=$(dirname "$0")
for name in fastfoto ffscan; do
  printf '#!/bin/sh\\necho %s\\n' "$name" > "$dir/$name"
  chmod +x "$dir/$name"
done
echo "$@" >> "$dir/pip.log"
INNER
chmod +x "$4/bin/python"
"""
STUB_MAKE = """#!/bin/sh
# Stands in for make: `make -C DIR` leaves the shim in DIR.
[ "$1" = "-C" ] || exit 64
: > "$2/ff680w_usb_gap.so"
"""


def write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A copy of the files the script reads, so a stand-in make leaves nothing in the repo."""
    repo = tmp_path / "checkout"
    (repo / "tools" / "usb-gap-shim").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "install-desktop.sh", repo / "tools" / "install-desktop.sh")
    shutil.copytree(ROOT / "packaging", repo / "packaging")
    for name in ("Makefile", "ff680w_usb_gap.c"):
        shutil.copy(ROOT / "tools" / "usb-gap-shim" / name, repo / "tools" / "usb-gap-shim" / name)
    return repo


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def env(tmp_path: Path, home: Path) -> dict[str, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(stubs / "python3", STUB_PYTHON)
    write_executable(stubs / "make", STUB_MAKE)
    return {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "HOME": str(home),
        "FASTFOTO_PYTHON": str(stubs / "python3"),
    }


def run(checkout: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(checkout / "tools" / "install-desktop.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def tree(home: Path) -> list[str]:
    return sorted(str(p.relative_to(home)) for p in home.rglob("*"))


def test_dry_run_lists_every_action_and_touches_nothing(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    done = run(checkout, env, "--dry-run")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines
    assert all(line.startswith("would ") for line in lines)
    text = done.stdout
    for expected in (
        f"{home}/.local/share/fastfoto-linux/venv",
        "--system-site-packages",
        "make -C",
        f"{home}/.local/lib/fastfoto-linux/{SHIM}",
        f"{home}/.local/share/applications/{APP_ID}.desktop",
        f"{home}/.local/share/icons/hicolor/scalable/apps/{APP_ID}.svg",
        f"{home}/.local/bin/fastfoto",
        f"{home}/.local/bin/ffscan",
    ):
        assert expected in text
    assert tree(home) == []


def test_dry_run_respects_xdg_data_home(
    checkout: Path, env: dict[str, str], home: Path, tmp_path: Path
) -> None:
    data = tmp_path / "xdg-data"
    done = run(checkout, {**env, "XDG_DATA_HOME": str(data)}, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert f"{data}/fastfoto-linux/venv" in done.stdout
    assert f"{data}/applications/{APP_ID}.desktop" in done.stdout
    assert f"{home}/.local/share" not in done.stdout


def test_install_makes_the_venv_shim_launcher_icon_and_links(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    venv = home / ".local" / "share" / "fastfoto-linux" / "venv"
    assert (venv / "bin" / "python").is_file()
    assert "install" in (venv / "bin" / "pip.log").read_text()
    for name in ("fastfoto", "ffscan"):
        link = home / ".local" / "bin" / name
        assert link.is_symlink()
        assert link.resolve() == (venv / "bin" / name).resolve()
    assert (home / ".local" / "lib" / "fastfoto-linux" / SHIM).is_file()
    assert (
        home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    ).is_file()
    desktop = home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    assert f'Exec="{venv}/bin/fastfoto"' in desktop.read_text().splitlines()


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="desktop-file-utils")
def test_the_installed_launcher_is_valid(checkout: Path, env: dict[str, str], home: Path) -> None:
    assert run(checkout, env).returncode == 0
    desktop = home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    done = subprocess.run(
        ["desktop-file-validate", str(desktop)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_installing_twice_changes_nothing_and_succeeds(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    first = tree(home)
    again = run(checkout, env)
    assert again.returncode == 0, again.stderr
    assert tree(home) == first


def test_uninstall_removes_what_install_made_and_nothing_else(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "other-tool").write_text("x")
    config = home / ".config" / "fastfoto-linux" / "gui.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}")
    assert run(checkout, env).returncode == 0
    planned = run(checkout, env, "--uninstall", "--dry-run")
    assert planned.returncode == 0, planned.stderr
    assert all(line.startswith("would remove") for line in planned.stdout.splitlines())
    assert (home / ".local" / "bin" / "fastfoto").is_symlink()
    done = run(checkout, env, "--uninstall")
    assert done.returncode == 0, done.stderr
    remaining = tree(home)
    installed = ("venv", ".desktop", ".svg", SHIM, "ffscan", ".local/bin/fastfoto")
    assert not [path for path in remaining if any(mark in path for mark in installed)]
    assert (home / ".local" / "bin" / "other-tool").is_file()
    assert config.is_file()


def test_uninstall_leaves_a_foreign_file_with_our_name_alone(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    (home / ".local" / "bin").mkdir(parents=True)
    foreign = home / ".local" / "bin" / "fastfoto"
    foreign.write_text("someone else's")
    done = run(checkout, env, "--uninstall")
    assert done.returncode == 0, done.stderr
    assert foreign.read_text() == "someone else's"


def test_uninstall_with_nothing_installed_says_so(checkout: Path, env: dict[str, str]) -> None:
    done = run(checkout, env, "--uninstall")
    assert done.returncode == 0
    assert "nothing to remove" in done.stdout


def test_an_unknown_option_is_a_usage_error(checkout: Path, env: dict[str, str]) -> None:
    done = run(checkout, env, "--frobnicate")
    assert done.returncode == 2
    assert "usage" in done.stderr.lower()


def test_help_describes_the_options(checkout: Path, env: dict[str, str]) -> None:
    done = run(checkout, env, "--help")
    assert done.returncode == 0
    assert "--uninstall" in done.stdout
    assert "--dry-run" in done.stdout
