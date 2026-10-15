#!/usr/bin/env bash
# Install FastFoto Linux for the current user, without root:
#   - a virtual environment that sees the system PySide6 and Kirigami,
#   - the USB gap shim the scanner needs, built from this checkout,
#   - an application menu entry with its icon, and `fastfoto` / `ffscan` in ~/.local/bin.
# Safe to run again (it updates what it installed). --uninstall removes what it installed (it
# keeps a list in installed.txt); the settings in ~/.config/fastfoto-linux and your photos are
# never touched. The Python dependencies come from packaging/requirements-desktop.txt, which
# pins every package by hash (it is generated from uv.lock; a test keeps the two in step).
set -euo pipefail

APP_ID="io.github.bearyjd.FastFotoLinux"
LAUNCHERS=(fastfoto ffscan)

usage() {
  cat <<USAGE
Usage: install-desktop.sh [--uninstall] [--dry-run] [--help]

  --uninstall  remove what this script installed
  --dry-run    list what would be done and change nothing
  --help       show this text

Environment: HOME and XDG_DATA_HOME (when it is an absolute path) say where things go;
FASTFOTO_PYTHON is the Python used for the environment (default /usr/bin/python3, the one
that has PySide6).
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
# The XDG specification: a base directory that is not an absolute path is invalid, ignore it.
case "${XDG_DATA_HOME:-}" in
  /*) DATA_HOME=$XDG_DATA_HOME ;;
  *) DATA_HOME=$HOME/.local/share ;;
esac
PYTHON="${FASTFOTO_PYTHON:-/usr/bin/python3}"
APP_DATA="$DATA_HOME/fastfoto-linux"
VENV="$APP_DATA/venv"
RECORD="$APP_DATA/installed.txt"
REQUIREMENTS="$REPO/packaging/requirements-desktop.txt"
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

# Everything below that removes or clears the environment goes through this first.
check_venv_path() {
  [[ "$VENV" == */fastfoto-linux/venv ]] || fail "refusing to touch an unexpected path: $VENV"
}

python_version() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'
}

venv_version() {
  sed -n 's/^version *= *\([0-9]*\.[0-9]*\).*/\1/p' "$VENV/pyvenv.cfg"
}

make_venv() {
  [[ -x "$PYTHON" ]] || fail "$PYTHON not found; set FASTFOTO_PYTHON to the Python that has PySide6"
  check_venv_path
  mkdir -p "$APP_DATA"
  local mode=()
  if [[ -f "$VENV/pyvenv.cfg" ]]; then
    # An environment of another Python version cannot be upgraded in place: start it afresh.
    if [[ "$(venv_version)" == "$(python_version "$PYTHON")" ]]; then
      mode=(--upgrade)
    else
      mode=(--clear)
    fi
  fi
  "$PYTHON" -m venv ${mode[@]+"${mode[@]}"} --system-site-packages "$VENV"
}

install_package() {
  [[ -f "$REQUIREMENTS" ]] || fail "$REQUIREMENTS is missing; is this a complete checkout?"
  # The dependencies are checked against the hashes of the lock file; this checkout then goes in
  # on top without looking for dependencies again (pip would keep an installed package of the
  # same version, so it is reinstalled to make sure its code is what is installed).
  "$VENV/bin/python" -m pip install --require-hashes -r "$REQUIREMENTS"
  "$VENV/bin/python" -m pip install --force-reinstall --no-deps "$REPO"
}

build_shim() {
  command -v make > /dev/null || fail "make is needed to build the USB gap shim (and gcc)"
  make -C "$REPO/tools/usb-gap-shim"
}

INSTALLED=()

recorded() {
  [[ -f "$RECORD" ]] && grep -qxF -- "$1" "$RECORD"
}

# The shim is loaded into scanimage: its folder is private to the user and the file is put in
# place by renaming a new one over the old, never by writing into a file a scan may have mapped.
copy_shim() {
  if [[ -e "$SHIM" || -L "$SHIM" ]] && ! recorded "$SHIM"; then
    echo "install-desktop.sh: leaving $SHIM alone: this installer did not put it there" >&2
    return 0
  fi
  install -d -m 0700 "$LIB_DIR"
  chmod 0700 "$LIB_DIR" # install -d keeps the mode of a folder that was already there
  local staged
  staged=$(mktemp "$LIB_DIR/.shim.XXXXXX")
  install -m 0755 "$REPO/tools/usb-gap-shim/ff680w_usb_gap.so" "$staged" || {
    rm -f -- "$staged"
    return 1
  }
  mv -f -- "$staged" "$SHIM"
  INSTALLED+=("$SHIM")
}

# The Exec line goes in as data (ENVIRON, not `awk -v`, which would read backslashes as escapes).
# In a quoted Exec argument the Desktop Entry specification wants " ` $ and \ escaped with a
# backslash and % doubled; the file format then wants every backslash doubled again.
write_desktop() {
  mkdir -p "$(dirname "$DESKTOP")"
  EXEC_PATH="$VENV/bin/fastfoto" awk '
    function quoted(path,   out, i, c) {
      out = ""
      for (i = 1; i <= length(path); i++) {
        c = substr(path, i, 1)
        if (c == "\\") out = out "\\\\\\\\"
        else if (c == "\"" || c == "`" || c == "$") out = out "\\" c
        else if (c == "%") out = out "%%"
        else out = out c
      }
      return out
    }
    function plain(path,   out, i, c) {
      out = ""
      for (i = 1; i <= length(path); i++) {
        c = substr(path, i, 1)
        out = out (c == "\\" ? "\\\\" : c)
      }
      return out
    }
    /^Exec=/ { print "Exec=\"" quoted(ENVIRON["EXEC_PATH"]) "\""; next }
    /^TryExec=/ { print "TryExec=" plain(ENVIRON["EXEC_PATH"]); next }
    { print }
  ' "$REPO/packaging/$APP_ID.desktop" > "$DESKTOP"
  INSTALLED+=("$DESKTOP")
}

copy_icon() {
  mkdir -p "$(dirname "$ICON")"
  cp "$REPO/packaging/$APP_ID.svg" "$ICON"
  INSTALLED+=("$ICON")
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

# What was installed, one path per line: --uninstall removes these and nothing else.
write_record() {
  mkdir -p "$APP_DATA"
  printf '%s\n' "${INSTALLED[@]}" > "$RECORD"
}

check_qt() {
  if ! "$VENV/bin/python" -c 'import PySide6.QtQml' 2> /dev/null; then
    echo "warning: PySide6 was not found; the app will not start until it is installed," >&2
    echo "  e.g. on Fedora: sudo dnf install python3-pyside6 kf6-kirigami" >&2
  fi
}

install_all() {
  act "create the environment $VENV ($PYTHON -m venv --system-site-packages)" make_venv
  act "install the dependencies from $REQUIREMENTS (hashes checked), then $REPO without them" install_package
  act "build the USB gap shim: make -C $REPO/tools/usb-gap-shim" build_shim
  act "copy the shim to $SHIM (a private folder, replaced atomically)" copy_shim
  act "write the launcher $DESKTOP" write_desktop
  act "copy the icon to $ICON" copy_icon
  local name
  for name in "${LAUNCHERS[@]}"; do
    act "link $BIN_DIR/$name -> $VENV/bin/$name" link_launcher "$name"
  done
  act "record what was installed in $RECORD" write_record
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

# Only the exact files this installer creates are ever removed, and only when it recorded them.
remove_recorded() {
  local what=$1 path=$2
  recorded "$path" || return 0
  remove "$what" "$path"
}

# Checked before anything is removed: the environment folder is deleted whole.
check_uninstall() {
  check_venv_path
  if [[ -e "$VENV" && ! -f "$VENV/pyvenv.cfg" ]]; then
    fail "$VENV has no pyvenv.cfg, so it is not an environment this installer made; nothing was removed"
  fi
}

uninstall_all() {
  check_uninstall
  remove_launchers
  remove_recorded "launcher" "$DESKTOP"
  remove_recorded "icon" "$ICON"
  remove_recorded "shim" "$SHIM"
  remove "environment" "$VENV"
  remove "record" "$RECORD"
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
