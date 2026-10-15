"""tools/install-desktop.sh, run with a throwaway HOME and stand-ins for python, pip and make."""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.bearyjd.FastFotoLinux"
SHIM = "ff680w_usb_gap.so"

STUB_PYTHON = """#!/bin/sh
# Stands in for /usr/bin/python3: `-c CODE` answers the version (STUB_PYTHON_VERSION) and
# `-m venv [--upgrade|--clear] --system-site-packages DIR` makes a venv whose python is a stub.
if [ "$1" = "-c" ]; then echo "${STUB_PYTHON_VERSION:-3.14}"; exit 0; fi
[ "$1 $2" = "-m venv" ] || { echo "unexpected: $*" >&2; exit 64; }
shift 2
echo "venv $*" >> "$(dirname "$0")/python3.log"
mode=create
while [ "$#" -gt 1 ]; do
  case "$1" in
    --upgrade) mode=upgrade ;;
    --clear) mode=clear ;;
    --system-site-packages) ;;
    *) echo "unexpected: $*" >&2; exit 64 ;;
  esac
  shift
done
dir=$1
[ "$mode" = clear ] && rm -rf "$dir"
mkdir -p "$dir/bin"
printf 'home = /usr/bin\nversion = %s.1\n' "${STUB_PYTHON_VERSION:-3.14}" > "$dir/pyvenv.cfg"
cat > "$dir/bin/python" <<'INNER'
#!/bin/sh
# Stands in for the venv's python: `-m pip install ...` leaves the two console scripts.
dir=$(dirname "$0")
for name in fastfoto ffscan; do
  printf '#!/bin/sh\necho %s\n' "$name" > "$dir/$name"
  chmod +x "$dir/$name"
done
echo "$@" >> "$dir/pip.log"
INNER
chmod +x "$dir/bin/python"
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


# -- Review round 1: what the installer puts where, and how safely (item 8 and 12) ----------------

REQUIREMENTS = "packaging/requirements-desktop.txt"


def lib_dir(home: Path) -> Path:
    return home / ".local" / "lib" / "fastfoto-linux"


def pip_lines(home: Path) -> list[str]:
    log = home / ".local" / "share" / "fastfoto-linux" / "venv" / "bin" / "pip.log"
    return [line for line in log.read_text().splitlines() if line.startswith("-m pip install")]


def python_calls(env: dict[str, str]) -> list[str]:
    return (Path(env["FASTFOTO_PYTHON"]).parent / "python3.log").read_text().splitlines()


def test_the_library_folder_is_private_and_the_shim_is_executable(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    assert stat.S_IMODE(lib_dir(home).stat().st_mode) == 0o700
    assert stat.S_IMODE((lib_dir(home) / SHIM).stat().st_mode) == 0o755


def test_an_existing_library_folder_is_made_private(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    lib_dir(home).mkdir(parents=True, mode=0o755)
    lib_dir(home).chmod(0o755)
    assert run(checkout, env).returncode == 0
    assert stat.S_IMODE(lib_dir(home).stat().st_mode) == 0o700


def test_the_shim_is_replaced_by_a_new_file_never_written_over(
    checkout: Path, env: dict[str, str], home: Path, tmp_path: Path
) -> None:
    """A running scan has the old shim mapped: writing into that file would crash it."""
    assert run(checkout, env).returncode == 0
    shim = lib_dir(home) / SHIM
    shim.write_text("the shim a running scan has mapped")
    before = shim.stat().st_ino
    os.link(shim, tmp_path / "held-open")
    assert run(checkout, env).returncode == 0
    assert shim.stat().st_ino != before
    assert (tmp_path / "held-open").read_text() == "the shim a running scan has mapped"
    assert sorted(path.name for path in lib_dir(home).iterdir()) == [SHIM]


def test_dependencies_come_from_the_hashed_requirements_and_the_checkout_has_none(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    first, second = pip_lines(home)
    assert "--require-hashes" in first
    assert f"-r {checkout}/{REQUIREMENTS}" in first
    assert "--no-deps" in second
    assert str(checkout) in second
    assert "-r" not in second.split()


def test_the_hashed_requirements_are_what_the_lock_file_says() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    command = [uv, "export", "--locked", "--no-dev", "--no-emit-project", "--hashes"]
    exported = subprocess.run(
        [*command, "--no-header", "--quiet"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert exported.returncode == 0, exported.stderr
    shipped = (ROOT / REQUIREMENTS).read_text()
    assert "--hash=sha256:" in shipped
    assert shipped == exported.stdout


def test_a_first_run_creates_the_environment_and_a_second_upgrades_it(
    checkout: Path, env: dict[str, str]
) -> None:
    assert run(checkout, env).returncode == 0
    assert "--upgrade" not in python_calls(env)[0]
    assert run(checkout, env).returncode == 0
    assert "--upgrade" in python_calls(env)[1]
    assert "--clear" not in python_calls(env)[1]


def test_a_new_python_version_gets_a_new_environment(checkout: Path, env: dict[str, str]) -> None:
    assert run(checkout, env).returncode == 0
    assert run(checkout, {**env, "STUB_PYTHON_VERSION": "3.15"}).returncode == 0
    assert "--clear" in python_calls(env)[1]


def test_the_install_is_recorded_and_uninstall_removes_only_what_is_recorded(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    record = home / ".local" / "share" / "fastfoto-linux" / "installed.txt"
    listed = record.read_text().splitlines()
    assert str(lib_dir(home) / SHIM) in listed
    assert all(Path(line).is_absolute() for line in listed)
    precious = home / "keep-me"
    precious.write_text("mine")
    with record.open("a") as stream:
        stream.write(f"{precious}\n{home}\n")
    assert run(checkout, env, "--uninstall").returncode == 0
    assert precious.read_text() == "mine"
    assert not (lib_dir(home) / SHIM).exists()


def test_a_shim_the_installer_did_not_put_there_is_left_alone(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    lib_dir(home).mkdir(parents=True)
    own = lib_dir(home) / SHIM
    own.write_text("built by hand")
    done = run(checkout, env)
    assert done.returncode == 0, done.stderr
    assert "leaving" in done.stderr
    assert own.read_text() == "built by hand"
    assert run(checkout, env, "--uninstall").returncode == 0
    assert own.read_text() == "built by hand"


def test_uninstall_refuses_an_environment_that_is_not_one_and_removes_nothing(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    venv = home / ".local" / "share" / "fastfoto-linux" / "venv"
    (venv / "pyvenv.cfg").unlink()
    done = run(checkout, env, "--uninstall")
    assert done.returncode != 0
    assert "pyvenv.cfg" in done.stderr
    assert (lib_dir(home) / SHIM).is_file()
    assert (home / ".local" / "bin" / "fastfoto").is_symlink()
    assert venv.is_dir()


@pytest.mark.parametrize("relative", ["data", "./data", "../data", "~/data"])
def test_a_relative_xdg_data_home_is_ignored(
    checkout: Path, env: dict[str, str], home: Path, relative: str
) -> None:
    done = run(checkout, {**env, "XDG_DATA_HOME": relative}, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert f"{home}/.local/share/fastfoto-linux/venv" in done.stdout


# -- the launcher: the path goes in as data, not as awk or shell syntax -----------------------


def exec_arguments(value: str) -> list[str]:
    """The arguments the Desktop Entry spec reads out of an Exec value."""
    text = re.sub(
        r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r"}.get(m[1], m[1]), value
    )
    arguments, current, quoted, started = [], "", False, False
    characters = iter(text)
    for character in characters:
        if quoted and character == "\\":
            current += next(characters)
        elif character == '"':
            quoted, started = not quoted, True
        elif character == " " and not quoted:
            if started:
                arguments.append(current)
            current, started = "", False
        else:
            current += character
            started = True
    if started:
        arguments.append(current)
    return [argument.replace("%%", "%") for argument in arguments]


NASTY_HOME = 'my "home" 50%x $HOME `date` back\\slash'


def test_a_home_full_of_special_characters_is_launched_as_one_argument(
    checkout: Path, env: dict[str, str], tmp_path: Path
) -> None:
    nasty = tmp_path / NASTY_HOME
    nasty.mkdir()
    done = run(checkout, {**env, "HOME": str(nasty)})
    assert done.returncode == 0, done.stderr
    desktop = nasty / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    venv = nasty / ".local" / "share" / "fastfoto-linux" / "venv"
    entries = dict(line.split("=", 1) for line in desktop.read_text().splitlines() if "=" in line)
    assert exec_arguments(entries["Exec"]) == [f"{venv}/bin/fastfoto"]
    assert "%%" in entries["Exec"]
    assert entries["TryExec"].replace("\\\\", "\\") == f"{venv}/bin/fastfoto"
    if shutil.which("desktop-file-validate"):
        checked = subprocess.run(
            ["desktop-file-validate", str(desktop)], capture_output=True, text=True, check=False
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr


def test_the_installed_launcher_checks_that_the_program_is_there(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    desktop = home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    venv = home / ".local" / "share" / "fastfoto-linux" / "venv"
    assert f"TryExec={venv}/bin/fastfoto" in desktop.read_text().splitlines()
