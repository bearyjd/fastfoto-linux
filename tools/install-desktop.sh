#!/usr/bin/env bash
# Install FastFoto Linux for the current user, without root:
#   - a virtual environment that sees the system PySide6 and Kirigami,
#   - the USB gap shim the scanner needs, built from this checkout,
#   - an application menu entry with its icon, and `fastfoto` / `ffscan` in ~/.local/bin.
# Safe to run again (it updates what it installed). --uninstall removes it; the settings in
# ~/.config/fastfoto-linux and your photos are never touched.
set -euo pipefail

APP_ID="io.github.bearyjd.FastFotoLinux"
LAUNCHERS=(fastfoto ffscan)

usage() {
  cat <<USAGE
Usage: install-desktop.sh [--uninstall] [--dry-run] [--help]

  --uninstall  remove what this script installed
  --dry-run    list what would be done and change nothing
  --help       show this text

Environment: HOME and XDG_DATA_HOME say where things go; FASTFOTO_PYTHON is the Python used
for the environment (default /usr/bin/python3, the one that has PySide6).
USAGE
}

DRY_RUN=0
UNINSTALL=0
for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "install-desktop.sh: unknown option: $argument" >&2; usage >&2; exit 2 ;;
  esac
done

: "${HOME:?HOME is not set}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PYTHON="${FASTFOTO_PYTHON:-/usr/bin/python3}"
APP_DATA="$DATA_HOME/fastfoto-linux"
VENV="$APP_DATA/venv"
LIB_DIR="$HOME/.local/lib/fastfoto-linux"
SHIM="$LIB_DIR/ff680w_usb_gap.so"
BIN_DIR="$HOME/.local/bin"
DESKTOP="$DATA_HOME/applications/$APP_ID.desktop"
ICON="$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"

# act "what it does" command...: say it (dry run) or do it.
act() {
  local what=$1
  shift
  if ((DRY_RUN)); then
    echo "would $what"
  else
    "$@"
  fi
}

fail() {
  echo "install-desktop.sh: $*" >&2
  exit 1
}

make_venv() {
  [[ -x "$PYTHON" ]] || fail "$PYTHON not found; set FASTFOTO_PYTHON to the Python that has PySide6"
  mkdir -p "$APP_DATA"
  "$PYTHON" -m venv --system-site-packages "$VENV"
}

install_package() {
  # Twice: the first brings the dependencies up to date, the second makes sure this checkout's
  # code is what is installed (pip would keep an installed package of the same version).
  "$VENV/bin/python" -m pip install --upgrade "$REPO"
  "$VENV/bin/python" -m pip install --force-reinstall --no-deps "$REPO"
}

build_shim() {
  command -v make > /dev/null || fail "make is needed to build the USB gap shim (and gcc)"
  make -C "$REPO/tools/usb-gap-shim"
}

copy_shim() {
  mkdir -p "$LIB_DIR"
  cp "$REPO/tools/usb-gap-shim/ff680w_usb_gap.so" "$SHIM"
}

write_desktop() {
  mkdir -p "$(dirname "$DESKTOP")"
  awk -v exec_line="Exec=\"$VENV/bin/fastfoto\"" \
    '/^Exec=/ { print exec_line; next } { print }' \
    "$REPO/packaging/$APP_ID.desktop" > "$DESKTOP"
}

copy_icon() {
  mkdir -p "$(dirname "$ICON")"
  cp "$REPO/packaging/$APP_ID.svg" "$ICON"
}

link_launcher() {
  local name=$1 link="$BIN_DIR/$1"
  if [[ -e "$link" || -L "$link" ]] && [[ "$(readlink "$link" 2> /dev/null || true)" != "$VENV/bin/"* ]]; then
    echo "install-desktop.sh: leaving $link alone: it is not a link made by this installer" >&2
    return 0
  fi
  mkdir -p "$BIN_DIR"
  ln -sfn "$VENV/bin/$name" "$link"
}

check_qt() {
  if ! "$VENV/bin/python" -c 'import PySide6.QtQml' 2> /dev/null; then
    echo "warning: PySide6 was not found; the app will not start until it is installed," >&2
    echo "  e.g. on Fedora: sudo dnf install python3-pyside6 kf6-kirigami" >&2
  fi
}

install_all() {
  act "create the environment $VENV ($PYTHON -m venv --system-site-packages)" make_venv
  act "install $REPO into it ($VENV/bin/python -m pip install --upgrade $REPO)" install_package
  act "build the USB gap shim: make -C $REPO/tools/usb-gap-shim" build_shim
  act "copy the shim to $SHIM" copy_shim
  act "write the launcher $DESKTOP" write_desktop
  act "copy the icon to $ICON" copy_icon
  local name
  for name in "${LAUNCHERS[@]}"; do
    act "link $BIN_DIR/$name -> $VENV/bin/$name" link_launcher "$name"
  done
  if ((!DRY_RUN)); then
    check_qt
    echo "Installed. Start FastFoto Linux from the application menu, or run: fastfoto"
    echo "(make sure $BIN_DIR is in your PATH to use the commands from a terminal)"
  fi
}

REMOVED=0

# remove "what" path...: remove it (or say so on a dry run) when it exists.
remove() {
  local what=$1 path=$2
  [[ -e "$path" || -L "$path" ]] || return 0
  REMOVED=1
  if ((DRY_RUN)); then
    echo "would remove $what $path"
  else
    rm -rf -- "$path"
    echo "removed $what $path"
  fi
}

remove_launchers() {
  local name link
  for name in "${LAUNCHERS[@]}"; do
    link="$BIN_DIR/$name"
    if [[ -L "$link" && "$(readlink "$link")" == "$VENV/bin/"* ]]; then
      remove "link" "$link"
    fi
  done
}

uninstall_all() {
  remove_launchers
  remove "launcher" "$DESKTOP"
  remove "icon" "$ICON"
  remove "shim" "$SHIM"
  [[ "$VENV" == */fastfoto-linux/venv ]] || fail "refusing to remove an unexpected path: $VENV"
  remove "environment" "$VENV"
  if ((!DRY_RUN)); then
    rmdir "$APP_DATA" "$LIB_DIR" 2> /dev/null || true
  fi
  ((REMOVED)) || echo "nothing to remove"
}

if ((UNINSTALL)); then
  uninstall_all
else
  install_all
fi
