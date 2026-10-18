# Environment variables

Every environment variable the code, the shim and the install script read. Nothing here is
required: all have a default.

<!-- AUTO-GENERATED: collected from src/, tools/ and tests/ (grep environ, getenv, "${...}") -->
## App and `ffscan`

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `FF680W_SHIM` | no | Path to the USB gap shim (`ff680w_usb_gap.so`). A leading `~/` is expanded from `HOME`. Inside a Flatpak it is the only place looked at (the manifest sets it to the bundled shim). | unset: `~/.local/lib/fastfoto-linux/`, then the in-repo build |
| `FF680W_NO_PRECHECK` | no | `1` skips the check that a USB scanner answers before each scan. | unset (check runs) |
| `FF680W_FORCE_UNSTICK` | no | `1` sends the padding that frees a stuck scanner even without a note about an unclean end. Last resort. | unset |
| `XDG_STATE_HOME` | no | Base folder for the `scanner-unclean` note (`$XDG_STATE_HOME/fastfoto-linux`). Ignored if not absolute. | `~/.local/state` |
| `XDG_CONFIG_HOME` | no | Base folder for the desktop app's settings (`fastfoto-linux/gui.json`). Ignored if not absolute. | `~/.config` |
| `HOME` | yes (by the OS) | Home folder, used for the defaults above. | set by the login |
| `PATH` | no | Searched for `scanimage`, Tesseract and `brew`; OCR also adds the Flatpak's own folder, the interpreter's folder and Homebrew's. | the system's |
| `QT_QUICK_CONTROLS_STYLE` | no | If set, the app keeps that Qt Quick Controls style; otherwise it selects `org.kde.desktop`. | unset |

Set by the app for `scanimage` (not for you to set): `LC_ALL=C`, `LANGUAGE` removed,
`LD_PRELOAD` gets the shim prepended, `SANE_CONFIG_DIR` is set for `--net` and removed for USB.
`PYTHONSAFEPATH=1` is set in the app's own environment while the library commands run their helper processes, so they do not import from the current folder.

## USB gap shim (`tools/usb-gap-shim`)

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `FF680W_USB_GAP_US` | no | Gap in microseconds before a bulk OUT: integer `0` to `10000000`. `0` turns it off. Invalid values fall back to the default. Read once. | `2000` |
| `FF680W_OUT_FINISH_MS` | no | How long a bulk OUT that timed out part-way keeps sending the rest, in milliseconds: integer `0` to `600000`. `0` turns it off. Read once. | `30000` |

## Install script (`tools/install-desktop.sh`)

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `HOME` | yes | Where `~/.local/lib` and `~/.local/bin` are. Refused if it holds a control character. | none |
| `XDG_DATA_HOME` | no | Base for the environment, menu entry and icon. Ignored if not absolute or if it holds a control character. | `$HOME/.local/share` |
| `FASTFOTO_PYTHON` | no | Python used to create the environment; it must see PySide6. | `/usr/bin/python3` |
| `FASTFOTO_BREW_BIN` | no | Homebrew's bin folder, searched for `brew` and `tesseract` besides `PATH`, only if owned by root or you and not writable by others. | `/home/linuxbrew/.linuxbrew/bin` |
| `FASTFOTO_OSTREE_MARKER` | no | File whose presence means an immutable (rpm-ostree) system; selects the Tesseract install hint. | `/run/ostree-booted` |

Flags: `--dry-run`, `--uninstall`, `--with-tesseract`, `--help`.

## Tests and CI

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `FASTFOTO_REAL_SCANS` | no | Folder of private scans for `real_scans` tests. Never in CI. | `test-scans/` in the checkout |
| `FASTFOTO_HARDWARE` | no | `1` runs `hardware` tests against a connected scanner. | unset (skipped) |
| `FASTFOTO_REQUIRE_QT` | no | `1` makes missing PySide6 or Kirigami fail the Qt tests instead of skipping them (set by the `gui (fedora)` job). | unset |
| `CI` | no | If set, `real_scans` and `hardware` tests are skipped. | unset |
| `QT_QPA_PLATFORM`, `QT_QUICK_BACKEND` | no | Qt tests default them to `offscreen` and `software`. | as stated |
| `XDG_RUNTIME_DIR` | no | Qt tests create a temporary one when it is missing. | temporary folder |
| `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `OPENCV_FOR_THREADS_NUM` | no | CI sets them to `1` so xdist workers do not each start a thread per CPU. | unset |
<!-- END AUTO-GENERATED -->

## Notes

- `scanimage` runs with `LC_ALL=C` because its error texts are matched in English.
- The shim variables must be in the environment of the process that loads libsane; see
  `tools/usb-gap-shim/README.md`.
