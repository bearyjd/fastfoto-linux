# Runbook

fastfoto-linux is a desktop and command-line tool, not a deployed service, so this is a
troubleshooting and operations guide for the person running it. Everything here is checked
against the README, `docs/design/documents.md` and the code. Commands use `ffscan`; from a
checkout, prefix them with `uv run`.

## The scanner is not found

Symptom: `ffscan scan` or `ffscan doc scan` exits with code 3, or the app says no scanner was found.

1. Check the scanner is switched on and connected, then run `ffscan devices`. It only reads sysfs
   and never talks to the scanner. It lists USB scanners and whether the USB gap shim was found.
2. If the scanner shows up but the shim is missing, build or reinstall it (next section).
3. If it is silent, switch it off and on, wait for it to wake, and try again. The USB address
   (bus and device number) changes when it is switched off and on; that is expected.
4. Over Wi-Fi use `--net HOST`. A scanner that is busy with another device over Wi-Fi also stays
   silent: close the other program.

Exit codes: 0 ok, 1 processing error, 2 usage, 3 scanner not found, shim missing, scanner not
answering or in use by another program, 4 no documents in the feeder.

## USB gap shim

The FF-680W ignores a bulk transfer that follows the end of its previous reply too closely. The
`LD_PRELOAD` shim `ff680w_usb_gap.so` adds a gap (`FF680W_USB_GAP_US`, default 2000 us) and keeps
sending a transfer that timed out part-way (`FF680W_OUT_FINISH_MS`). Details:
`tools/usb-gap-shim/README.md`; variables: `docs/ENV.md`.

- Build from a checkout: `make -C tools/usb-gap-shim` (needs `gcc` and `make`).
- The app looks for it in `$FF680W_SHIM`, then `~/.local/lib/fastfoto-linux/`, then the in-repo
  build. Inside the Flatpak only `$FF680W_SHIM` counts, and the manifest points it at the bundled copy.
- `tools/install-desktop.sh` builds it and copies it to `~/.local/lib/fastfoto-linux/`. If a shim
  is already there that the installer did not put there, it leaves it alone and tells you; remove
  that file and run the installer again to use the one from the checkout.
- The shim must be loaded by the process that talks to the scanner. Setting `LD_PRELOAD` in a
  different shell does nothing.

## Scanner stuck, for example after sleep

A failed send can leave the scanner half-way through a command, so that it swallows every later byte.

- Before each USB scan the app checks that the scanner answers. It prints "Waiting for the scanner
  to answer..." if that takes over 2 seconds; a scanner that is waking up gets about 15 seconds.
- If the last scan on that USB address ended badly (an I/O error, a killed or signalled
  `scanimage`), `ffscan` left a note named `scanner-unclean` in `$XDG_STATE_HOME/fastfoto-linux` (or
  `~/.local/state/fastfoto-linux`). With that note the check frees the scanner with a little padding;
  `-v` then says "scanner was stuck; freed it". The note is ignored after a reboot or after 24 hours,
  and a scanner that answers clears it.
- Silent with no note: nothing is sent, because another device may be using it. The message is
  "The scanner isn't answering. It may be busy with another device, or stuck - switch it off and on,
  then try again." (exit 3). Switch it off and on.
- Last resort, when you know nothing else uses the scanner: `FF680W_FORCE_UNSTICK=1` sends the
  padding without a note.
- `FF680W_NO_PRECHECK=1` turns the check off. The check also needs libusb and is skipped without it
  and for `--net`.
- "The scanner is in use by another program": close the other program (a scanning app, `saned`).

## Partial scans and the kept raw pages

The scanner's pages go to a hidden folder in the output folder and are deleted after a clean run.
They are kept in `DIR/.raw/<UTC time>/` when anything went wrong (a failed or degraded sheet, a
scanner error, Ctrl-C, SIGTERM or SIGHUP), when a back was dropped for lack of writing, when blank
pages were dropped from a document, when searchable text failed, and always with `--keep-raw`.
`--discard-raw` removes them after an otherwise clean run. The summary says where they are. Raw
PNGs use disk space; delete a `.raw/<time>` folder yourself when you no longer need it.

If the scanner stops part-way (a jam, the cover opened) during `ffscan doc scan`, no PDF is made
from part of a stack. The pages already scanned are kept and the error prints the exact
`ffscan doc process` command that makes a PDF from them.

## Rerun a failed run from the raw pages

Photos (nothing needs rescanning):

    ffscan process DIR/.raw/<time>/page-*.png --out DIR --album "Name"

`process` reads the pages in natural filename order.

Documents:

    ffscan doc process DIR/.raw/<time>/*.png --out DIR --name "Name"

Use the command the error printed if there is one: it has the right file names. Add
`--ocr on --lang eng` to require searchable text, `--keep-blank` to keep every page.

## Blank-page, trim and OCR messages

- Blank pages are dropped by number and listed in the summary. If every page looks blank nothing is
  written, the exit code is 1 and the raw pages are kept. `--keep-blank` keeps every page.
- Trimming removes only what is certainly empty. When in doubt the page is kept whole.
- Searchable text needs OCRmyPDF and Tesseract. `--ocr auto` (the default) writes a plain PDF and
  says how to get OCR if one is missing. `--ocr on` without both is refused before scanning
  (exit 3). If OCR fails or times out, the plain PDF is still written with one warning (exit 1).
- Native install (installer or checkout): OCRmyPDF comes with the app's environment (`uv sync
  --extra ocr` from a checkout). Tesseract is a program: `brew install tesseract` where Homebrew
  is installed, `rpm-ostree install tesseract tesseract-osd` (then reboot) on an immutable system
  without it, `sudo dnf install tesseract tesseract-osd` on classic Fedora. For other languages:
  `brew install tesseract-lang` or the `tesseract-langpack-*` packages. `tools/install-desktop.sh
  --with-tesseract` runs the Homebrew command for you.
- Tesseract is looked for on `PATH`, then in Homebrew's bin folder, but only if that folder is
  owned by root or by you and not writable by others; otherwise the installer and the app say why
  they ignore it.
- Flatpak: Tesseract (`eng` and `osd` data only) and OCRmyPDF are built in. If the app says the OCR
  that comes with the Flatpak is missing, the installation is damaged: reinstall the Flatpak. Do
  not install Tesseract with `brew` or `dnf` for it; they do not reach into the sandbox.

## Reinstall the desktop app

    tools/install-desktop.sh --dry-run        # list what it would do, change nothing
    tools/install-desktop.sh                  # install; run it again to update
    tools/install-desktop.sh --with-tesseract # also install Tesseract with Homebrew
    tools/install-desktop.sh --uninstall      # remove only what it installed

It needs the distribution's PySide6 and Kirigami (`sudo dnf install python3-pyside6
kf6-kirigami` on Fedora), plus `make` and `gcc` for the shim. It creates a virtual environment under
`$XDG_DATA_HOME/fastfoto-linux/venv` (default `~/.local/share`), installs hashed wheels only, adds a menu
entry and icon, and links `fastfoto` and `ffscan` into `~/.local/bin` (put that on `PATH`). What
it installed is listed in `installed.txt` in the same folder. It never uses `sudo`, and it keeps your
settings in `~/.config/fastfoto-linux` and your photos. Environment variables it reads: `docs/ENV.md`.
Without PySide6 and Kirigami, `fastfoto` says what to install and exits with status 3; `ffscan`
needs neither.

## Flatpak

Build, install and run (needs `flatpak`, `flatpak-builder` and the Flathub remote); the commands
are in the README section "Flatpak". Manifest: `packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml`.

- Settings live in `~/.var/app/io.github.bearyjd.FastFotoLinux/`.
- The CI job `flatpak` builds the bundle in a pinned builder image (`kde-6.11`), installs it,
  and runs `tools/ci/flatpak-ocr-smoke.sh` inside the sandbox: Tesseract lists `eng` and `osd`,
  OCRmyPDF runs, and a generated page of text becomes a PDF whose text layer holds the words.
- A failing `flatpak` job: open the job log for the first error. The image is pinned by digest;
  to update it, look up the new digest of the tag and edit `.github/workflows/ci.yml`.
- The sandbox has `--device=all` for USB, network access, and your Pictures folder; any other
  output folder is granted through the desktop portal.
- CLI inside the Flatpak: `flatpak run --command=ffscan io.github.bearyjd.FastFotoLinux devices`.
