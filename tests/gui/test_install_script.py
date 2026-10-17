"""tools/install-desktop.sh, run with a throwaway HOME and stand-ins for python, pip and make."""

import os
import pty
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    BREW_LANG_HINT,
    DNF_INSTALL_HINT,
)

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.bearyjd.FastFotoLinux"
SHIM = "ff680w_usb_gap.so"

STUB_PYTHON = """#!/bin/sh
# Stands in for /usr/bin/python3: `-c CODE` answers the version (STUB_PYTHON_VERSION) and
# `-m venv [--upgrade|--clear] --system-site-packages DIR` makes a venv whose python is a stub.
# Every call is noted in python3.calls: "yes ..." when it was made isolated (-I), else "no ...".
isolated=no
if [ "$1" = "-I" ]; then isolated=yes; shift; fi
echo "$isolated $*" >> "$(dirname "$0")/python3.calls"
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
echo "$PWD" >> "$dir/cwd.log"
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
        # Never the machine's own Homebrew or rpm-ostree: see ocr_env for the OCR tests
        "FASTFOTO_BREW_BIN": str(tmp_path / "no-brew"),
        "FASTFOTO_OSTREE_MARKER": str(tmp_path / "no-ostree-booted"),
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
    assert "--with-tesseract" in done.stdout


# -- Review round 1: what the installer puts where, and how safely (item 8 and 12) ----------------

REQUIREMENTS = "packaging/requirements-desktop.txt"
OCR_REQUIREMENTS = "packaging/requirements-ocr.txt"


def lib_dir(home: Path) -> Path:
    return home / ".local" / "lib" / "fastfoto-linux"


def pip_lines(home: Path) -> list[str]:
    log = home / ".local" / "share" / "fastfoto-linux" / "venv" / "bin" / "pip.log"
    return [line for line in log.read_text().splitlines() if line.startswith("-I -m pip install")]


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


def test_the_build_backend_and_dependencies_are_hashed_wheels_and_the_checkout_builds_with_them(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    build, runtime, ocr, package = pip_lines(home)
    for line in (build, runtime, ocr):
        assert "--require-hashes" in line
        assert "--only-binary=:all:" in line
    assert f"-r {checkout}/packaging/requirements-build.txt" in build
    assert f"-r {checkout}/{REQUIREMENTS}" in runtime
    assert f"-r {checkout}/{OCR_REQUIREMENTS}" in ocr  # the ocr extra: ocrmypdf and its wheels
    assert "--no-build-isolation" in package
    assert "--no-deps" in package
    assert "--force-reinstall" in package
    assert str(checkout) in package
    assert "-r" not in package.split()


def test_the_hashed_requirements_are_what_the_lock_file_says() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    command = [
        uv,
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--hashes",
        "--no-annotate",
    ]
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


STRING_ESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}  # the only valid ones


def exec_arguments(value: str) -> list[str]:
    """The arguments the Desktop Entry spec reads out of an Exec value."""
    text = re.sub(r"\\(.)", lambda m: STRING_ESCAPES[m[1]], value)
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


# -- review round 2: the installer's own hygiene ------------------------------------------------


def venv_log(home: Path, name: str) -> list[str]:
    log = home / ".local" / "share" / "fastfoto-linux" / "venv" / "bin" / name
    return log.read_text().splitlines()


def test_every_call_of_the_environments_python_is_isolated(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    assert run(checkout, env).returncode == 0
    calls = venv_log(home, "pip.log")
    assert calls
    assert all(call.startswith("-I ") for call in calls), calls


def test_every_call_of_the_system_python_is_isolated(checkout: Path, env: dict[str, str]) -> None:
    """Review round 3: the system python imports nothing from the current folder or $PYTHONPATH."""
    assert run(checkout, env).returncode == 0
    assert run(checkout, env).returncode == 0  # the second run asks the version, then upgrades
    calls = (Path(env["FASTFOTO_PYTHON"]).parent / "python3.calls").read_text().splitlines()
    assert any(" -c " in f" {call} " for call in calls), calls
    assert any(" -m venv " in f" {call} " for call in calls), calls
    assert all(call.startswith("yes ") for call in calls), calls
    assert "-I -m venv" in run(checkout, env, "--dry-run").stdout  # and the plan says so


def test_the_script_works_from_the_checkout_whatever_the_current_folder_is(
    checkout: Path, env: dict[str, str], home: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    done = subprocess.run(
        ["bash", str(checkout / "tools" / "install-desktop.sh")],
        env=env,
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert set(venv_log(home, "cwd.log")) == {str(checkout)}  # not a folder with a json.py in it


def test_files_are_made_readable_whatever_the_users_umask(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    script = str(checkout / "tools" / "install-desktop.sh")
    done = subprocess.run(
        ["bash", "-c", f'umask 077; exec bash "{script}"'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    desktop = home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    assert stat.S_IMODE(desktop.stat().st_mode) == 0o644


def test_each_file_is_recorded_as_it_is_installed_so_a_failed_run_can_be_undone(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    icons = home / ".local" / "share" / "icons" / "hicolor" / "scalable"
    icons.mkdir(parents=True)
    (icons / "apps").write_text("a file where the icon folder should be")
    done = run(checkout, env)
    assert done.returncode != 0
    record = home / ".local" / "share" / "fastfoto-linux" / "installed.txt"
    listed = record.read_text().splitlines()
    assert str(lib_dir(home) / SHIM) in listed
    assert str(home / ".local" / "share" / "applications" / f"{APP_ID}.desktop") in listed


def test_a_foreign_shim_is_left_alone_and_the_warning_says_how_to_replace_it(
    checkout: Path, env: dict[str, str], home: Path
) -> None:
    lib_dir(home).mkdir(parents=True)
    (lib_dir(home) / SHIM).write_text("built by hand")
    done = run(checkout, env)
    assert f"remove {lib_dir(home) / SHIM} and run this installer again" in done.stderr


@pytest.mark.parametrize("variable", ["HOME", "XDG_DATA_HOME"])
@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_a_control_character_in_a_base_folder_is_refused_before_anything_is_done(
    checkout: Path, env: dict[str, str], tmp_path: Path, variable: str, flags: list[str]
) -> None:
    bad = tmp_path / "line\nbreak"
    bad.mkdir()
    done = run(checkout, {**env, variable: str(bad)}, *flags)
    assert done.returncode != 0
    assert "control character" in done.stderr
    assert not any(bad.iterdir())


def test_the_launcher_survives_a_round_trip_through_glib(
    checkout: Path, env: dict[str, str], tmp_path: Path
) -> None:
    """GLib is what the desktop uses to read the file: the strongest test of the escaping."""
    try:
        from gi.repository import GLib  # noqa: PLC0415
    except (ImportError, ValueError) as error:
        pytest.skip(f"PyGObject (python3-gobject) is not available: {error}")
    nasty = tmp_path / 'my "home" $HOME `date` back\\slash 50%x'
    nasty.mkdir()
    assert run(checkout, {**env, "HOME": str(nasty)}).returncode == 0
    desktop = nasty / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    keys = GLib.KeyFile()
    keys.load_from_file(str(desktop), GLib.KeyFileFlags.NONE)
    exec_line = keys.get_string("Desktop Entry", "Exec").replace("%%", "%")  # the field codes
    argv = GLib.shell_parse_argv(exec_line)[1]
    venv = nasty / ".local" / "share" / "fastfoto-linux" / "venv"
    assert argv == [f"{venv}/bin/fastfoto"]


# -- OCR: ocrmypdf comes with the app, Tesseract (a program) comes from Homebrew or dnf ----------

BASE_TOOLS = (
    *("awk", "bash", "cat", "chmod", "cp", "dirname", "grep", "install", "ln"),
    *("mkdir", "mktemp", "mv", "readlink", "rm", "rmdir", "sed"),
)
BREW_ARGUMENTS = "install tesseract"


@pytest.fixture
def ocr_env(tmp_path: Path, env: dict[str, str]) -> dict[str, str]:
    """PATH holds only the stand-ins and the tools the script uses, so that no tesseract, brew or
    sudo of the machine can be found or run; there is no Homebrew folder and no rpm-ostree."""
    tools = tmp_path / "base-tools"
    tools.mkdir()
    for name in BASE_TOOLS:
        found = shutil.which(name)
        assert found, f"{name} is needed to run the installer"
        (tools / name).symlink_to(found)
    stubs = env["PATH"].split(":")[0]
    write_executable(
        Path(stubs) / "sudo", f'#!/bin/sh\necho "$@" >> "{tmp_path}/sudo.log"\nexit 1\n'
    )
    return {**env, "PATH": f"{stubs}:{tools}"}


def brew_log(tmp_path: Path) -> Path:
    return tmp_path / "brew.log"


def add_brew(tmp_path: Path, env: dict[str, str], *, fail: bool = False) -> None:
    """A stand-in Homebrew in its own folder; it only notes its arguments."""
    folder = tmp_path / "linuxbrew" / "bin"
    folder.mkdir(parents=True)
    status = 1 if fail else 0
    write_executable(
        folder / "brew", f'#!/bin/sh\necho "$@" >> "{brew_log(tmp_path)}"\nexit {status}\n'
    )
    env["FASTFOTO_BREW_BIN"] = str(folder)


def add_tesseract(tmp_path: Path, env: dict[str, str]) -> None:
    write_executable(Path(env["PATH"].split(":")[0]) / "tesseract", "#!/bin/sh\nexit 0\n")


def run_on_tty(checkout: Path, env: dict[str, str], answer: str, *args: str) -> tuple[int, str]:
    """The installer with a terminal for input and output; ``answer`` is typed to it."""
    master, slave = pty.openpty()
    script = str(checkout / "tools" / "install-desktop.sh")
    process = subprocess.Popen(
        ["bash", script, *args], env=env, stdin=slave, stdout=slave, stderr=slave
    )
    os.close(slave)
    os.write(master, answer.encode())
    output = b""
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:  # the other end is closed
            break
        if not chunk:
            break
        output += chunk
    os.close(master)
    return process.wait(timeout=60), output.decode(errors="replace")


def test_the_dry_run_names_the_ocr_requirements_once(
    checkout: Path, ocr_env: dict[str, str]
) -> None:
    done = run(checkout, ocr_env, "--dry-run")
    assert done.returncode == 0, done.stderr
    lines = [line for line in done.stdout.splitlines() if OCR_REQUIREMENTS in line]
    assert len(lines) == 1
    assert lines[0].startswith("would install")


def test_without_tesseract_or_brew_a_dry_run_says_the_dnf_command(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    done = run(checkout, ocr_env, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert all(line.startswith("would ") for line in done.stdout.splitlines())
    assert f"would tell how to get Tesseract: {DNF_INSTALL_HINT}" in done.stdout
    assert BREW_INSTALL_HINT not in done.stdout


def test_on_an_immutable_system_without_brew_the_hint_is_still_brew(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    marker = tmp_path / "ostree-booted"
    marker.touch()
    done = run(checkout, {**ocr_env, "FASTFOTO_OSTREE_MARKER": str(marker)}, "--dry-run")
    assert f"would tell how to get Tesseract: {BREW_INSTALL_HINT}" in done.stdout
    assert "dnf" not in done.stdout


def test_with_brew_and_no_tesseract_a_dry_run_offers_the_option_and_changes_nothing(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path, home: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    done = run(checkout, ocr_env, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert all(line.startswith("would ") for line in done.stdout.splitlines())
    assert f"would tell how to get Tesseract: {BREW_INSTALL_HINT}" in done.stdout
    assert "--with-tesseract" in done.stdout
    assert not brew_log(tmp_path).exists()
    assert tree(home) == []


def test_a_dry_run_with_the_option_shows_the_brew_command_and_does_not_run_it(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    done = run(checkout, ocr_env, "--dry-run", "--with-tesseract")
    assert done.returncode == 0, done.stderr
    assert all(line.startswith("would ") for line in done.stdout.splitlines())
    assert f"would install Tesseract with Homebrew: {BREW_INSTALL_HINT}" in done.stdout
    assert not brew_log(tmp_path).exists()


def test_a_dry_run_with_tesseract_present_leaves_it_alone(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    add_tesseract(tmp_path, ocr_env)
    done = run(checkout, ocr_env, "--dry-run", "--with-tesseract")
    assert "would leave Tesseract alone" in done.stdout
    assert BREW_INSTALL_HINT not in done.stdout
    assert not brew_log(tmp_path).exists()


def test_a_tesseract_in_the_brew_folder_counts_as_present(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    write_executable(Path(ocr_env["FASTFOTO_BREW_BIN"]) / "tesseract", "#!/bin/sh\nexit 0\n")
    done = run(checkout, ocr_env, "--dry-run")
    assert "would leave Tesseract alone" in done.stdout


def test_the_option_runs_brew_install_tesseract_and_never_sudo(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    done = run(checkout, ocr_env, "--with-tesseract")
    assert done.returncode == 0, done.stderr
    assert brew_log(tmp_path).read_text().splitlines() == [BREW_ARGUMENTS]
    assert BREW_LANG_HINT in done.stdout  # for the other languages
    assert not (tmp_path / "sudo.log").exists()


def test_without_the_option_nothing_is_installed_and_the_hint_is_printed(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    done = run(checkout, ocr_env)
    assert done.returncode == 0, done.stderr
    assert not brew_log(tmp_path).exists()
    assert BREW_INSTALL_HINT in done.stdout
    assert "--with-tesseract" in done.stdout


def test_without_brew_the_hint_is_printed_and_the_option_is_explained(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    done = run(checkout, ocr_env, "--with-tesseract")
    assert done.returncode == 0, done.stderr
    assert DNF_INSTALL_HINT in done.stdout + done.stderr
    assert "Homebrew" in done.stderr
    assert not (tmp_path / "sudo.log").exists()


def test_tesseract_that_is_present_is_not_installed_again(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    add_tesseract(tmp_path, ocr_env)
    done = run(checkout, ocr_env, "--with-tesseract")
    assert done.returncode == 0, done.stderr
    assert not brew_log(tmp_path).exists()
    assert "Tesseract" not in done.stdout


def test_a_failing_brew_is_a_warning_not_a_failed_install(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path, home: Path
) -> None:
    add_brew(tmp_path, ocr_env, fail=True)
    done = run(checkout, ocr_env, "--with-tesseract")
    assert done.returncode == 0, done.stderr
    assert "Tesseract could not be installed" in done.stderr
    assert (home / ".local" / "bin" / "ffscan").is_symlink()


def test_on_a_terminal_yes_installs_tesseract_with_brew(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    status, output = run_on_tty(checkout, ocr_env, "y\n")
    assert status == 0, output
    assert brew_log(tmp_path).read_text().splitlines() == [BREW_ARGUMENTS]


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n"])
def test_on_a_terminal_anything_but_yes_installs_nothing(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path, answer: str
) -> None:
    add_brew(tmp_path, ocr_env)
    status, output = run_on_tty(checkout, ocr_env, answer)
    assert status == 0, output
    assert not brew_log(tmp_path).exists()
    assert BREW_INSTALL_HINT in output


def test_a_dry_run_on_a_terminal_asks_nothing(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    status, output = run_on_tty(checkout, ocr_env, "y\n", "--dry-run")
    assert status == 0, output
    assert not brew_log(tmp_path).exists()
    assert "?" not in output


def test_uninstall_never_touches_brew_or_tesseract(
    checkout: Path, ocr_env: dict[str, str], tmp_path: Path
) -> None:
    add_brew(tmp_path, ocr_env)
    assert run(checkout, ocr_env, "--with-tesseract").returncode == 0
    brew_log(tmp_path).unlink()
    for extra in ((), ("--dry-run",), ("--with-tesseract",)):
        done = run(checkout, ocr_env, "--uninstall", *extra)
        assert done.returncode == 0, done.stderr
        assert "Tesseract" not in done.stdout + done.stderr
    assert not brew_log(tmp_path).exists()
    assert not (tmp_path / "sudo.log").exists()
