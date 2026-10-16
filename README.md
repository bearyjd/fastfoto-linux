# fastfoto-linux

Native Linux support for the **Epson FastFoto FF-680W** photo scanner — scanning over USB or
Wi-Fi via SANE, plus the FastFoto-style features people actually buy it for: photo backs with
handwriting, auto-upright, colour restore, red-eye, albums and dates.

> Status: early development. Not affiliated with Seiko Epson.

## Why

The SANE `epsonds` backend already speaks the scanner's ESC/I-2 protocol, but over USB the
FF-680W stalls: its firmware ignores a command sent back-to-back with the end of its previous
reply. A ≥0.5 ms gap fixes it (`tools/usb-gap-shim`). Everything FastFoto does on the PC side —
cropping, pairing backs, orientation, restoration — this project re-implements as open code.

## Developer CLI (preview)

`ffscan` wires the pieces together end to end. It is a developer tool for now; the polished
command line and the watched folder come later.

```sh
uv sync
uv run ffscan devices                     # USB scanners and whether the USB gap shim is found
uv run ffscan scan --out ~/Scans --mkdir --album "Family Trips" --date 1975-06
uv run ffscan scan --out ~/Scans --net scanner.local --backs always --keep-raw
uv run ffscan process page-*.png --out ~/Scans --album "Family Trips" --feed face-up
```

- `devices` only reads sysfs; it never talks to the scanner. Over USB the scanner needs the gap
  shim: build it with `make -C tools/usb-gap-shim`.
- `scan` scans the document feeder (both sides, 600 dpi) and processes the pages. Photos are
  loaded face down by default (`--feed face-down`: the back is scanned first); use
  `--feed face-up` if yours are loaded the other way. `--simplex` scans fronts only.
- `process` handles raw pages scanned earlier, in natural filename order.
- Per photo it writes `Album_0001.jpg` (the original, turned upright by its faces), an enhanced
  copy `Album_0001_a.jpg` (colour restoration) and `Album_0001_b.jpg` when the back has
  handwriting (`--backs auto|always|never`; with `auto` the summary lists the backs it dropped).
  An enhanced copy that would be identical to the original is not written (the summary says
  `enhanced: N (M unchanged)`). If the orienter or an enhancer fails, the sheet keeps its
  original, loses only the `_a` copy and the exit code is 1. `--no-orient`, `--no-restore` and
  `--enhanced-only` switch parts off; `--redeye` adds red-eye removal to the enhanced copy and is off by default
  because roughly one fix in six is visibly wrong.
- A sheet whose photo cannot be found (two items fed together, say) is not lost or skipped: its
  whole pages are saved in its place in the sequence as `Album_0004_unprocessed.jpg` (the front)
  and `Album_0004_unprocessed_b.jpg` (the back, unless `--backs never`; with `auto` the back is
  kept, because nothing was cropped to judge its writing). Each page is saved as the whole
  scanner page, white area included, so that nothing is hidden while you look for the photo.
  If just one of the two pages can be read, that page is saved alone (a back keeps its `_b` name,
  whatever `--backs` says) and the summary says which side is missing. The next sheet gets the
  next number, so the files stay in the order the photos were fed, and the summary says which one
  it was: `photo 4 of 6 fed: the photo's edges were not found
  (two items fed together?) — whole page saved as Album_0004_unprocessed.jpg`. The desktop app
  shows the image in the results with a "Not processed" label and the reason; the heading counts
  these apart ("Photos (5), 1 photo needs checking"). Such a sheet still
  counts as failed (exit code 1) and its raw pages are kept as below.
- `--out` must exist unless `--mkdir` is given. A sheet that cannot be processed never stops the
  others: it is listed at the end and the exit code is 1. `scan` keeps the raw pages in
  `DIR/.raw/<UTC time>/` (so nothing needs rescanning) when anything went wrong (a failed or
  degraded sheet, a scanner error, Ctrl-C, SIGTERM or SIGHUP), when a back was dropped for lack
  of writing (the run says so; raw PNGs use disk space), and always with `--keep-raw`;
  `--discard-raw` deletes them after an otherwise clean run even if a back was dropped.
- Exit codes: 0 ok, 1 processing error, 2 usage, 3 scanner not found or shim missing, 4 no
  documents in the feeder. `-v` logs progress, `--debug` adds tracebacks.

## Fix sideways photos in an existing library

Scans made by other software (or by earlier runs) are often stored sideways or upside-down. Two
commands find them and fix them *without re-encoding a single pixel*: only the EXIF Orientation
tag changes, every other byte of the JPEG stays as it was. Your library is only ever read.

```sh
# 1. Look: decide each JPEG's orientation from its faces and write a plan you can read.
uv run ffscan library check ~/Pictures/MyLibrary --plan ~/Documents/library-plan.csv

# 2. Write corrected copies into a separate, empty folder (never into the library).
uv run ffscan library fix ~/Documents/library-plan.csv \
    --source ~/Pictures/MyLibrary --out ~/Pictures/MyLibrary-fixed --mkdir
```

- `check` walks the folder (symlinks are not followed; hidden folders and `@eaDir` are skipped;
  `.jpg`/`.jpeg` in any case), prints how
  many files it would rotate by 90, 180 and 270 degrees, how many look upright already, how many
  it cannot decide (no faces, or faces that disagree) and why others were skipped. The plan is a
  CSV with one row per JPEG (`path` relative to the library, `action`, `rotate_cw`, the old and
  new tag, a score, the reason and what `fix` needs to detect a changed file). Edit it freely:
  change a `rotate` row to `keep` to leave that photo alone. `--jobs N` sets the worker
  processes.
- Photos whose name ends in `_b` (FastFoto backs) are never rotated; the summary counts the ones
  that show a face, in case a front was filed as a back. Photos stored mirrored (EXIF
  orientation 2, 4, 5 or 7) are skipped.
- `fix` writes `DEST/<same relative path>` for every `rotate` row, keeping the file's times and
  permissions (not setuid bits or extended attributes), and a new
  `fastfoto-reorient-manifest-<UTC time>.csv` for each run listing old and new tags. It refuses a
  row whose file changed since `check` (size, modification time or content hash), never overwrites
  a file in `DEST` and refuses a `DEST` that is inside the library or contains it (also when it
  is the same folder under another name, a bind mount of one of the library's folders, or is
  reached through a link or a rename that was swapped in while it ran). If some folders of the
  library cannot be read, a bind mount of one of them cannot be ruled out, so `check` and `fix`
  then refuse a plan or `DEST` folder on the library's own drive: fix those folders' permissions
  or use a folder on another drive. (That guard is coarse by design: it does not cover a separate
  filesystem mounted under an unreadable folder.) Folders `fix` creates get
  the mode of the library's folder (always writable for you). A copy left by an interrupted run
  counts as done when you run `fix` again (it also gets the source's mode and times if the run
  was killed before giving them; an identical file that someone else owns is left as it is,
  counted as done and mentioned with a note), and is listed in that run's manifest. Staging files (`.name.<hex>.tmp`) that a killed run left behind are
  counted in the summary and left for you to delete. The plan and manifest are plain CSV: if you
  open them in a spreadsheet, a file name that starts with `=`, `+`, `-` or `@` may be taken as a
  formula.
- A photo is skipped, with the reason shown in the summary, when it cannot be changed safely:
  malformed Exif, more than one Orientation entry in it, an Exif block too large to grow, more
  than 1024 markers before the image data, or an XMP packet (Extended XMP included) with its own
  Orientation in the `tiff` namespace (viewers may prefer either tag, and the two must never
  disagree). Ctrl-C, SIGTERM or SIGHUP stops `check` at once and writes no plan. `check` reads
  the library's files without changing their access times where the system allows it (the access
  times of its folders still change when they are listed).
- Then review `DEST` in your photo viewer and, once you are happy, copy it over the library
  yourself. Running `check` on `DEST` again proposes nothing to rotate.

## Desktop app (preview)

`fastfoto` is a KDE desktop app over the same scan session as `ffscan`: pick an output folder, album
and date, press **Scan**, and the photos appear in the window as they are saved (originals or
enhanced copies, with each back beside its front; a sheet whose photo could not be found is shown
as a "Not processed" page with the reason). **Cancel** stops the scan; the pages scanned
so far are kept and **Process them now** turns them into photos later. Closing the window during
a scan asks to cancel first, and the settings you used are remembered for next time.

Install it for your user (no root; nothing to do with `uv` or pip):

```sh
sudo dnf install python3-pyside6 kf6-kirigami     # Fedora; the app needs the distribution's Qt
tools/install-desktop.sh --dry-run                # list what it would do
tools/install-desktop.sh                          # install; run it again to update
tools/install-desktop.sh --uninstall              # remove it again
```

The installer creates a virtual environment that can see the system PySide6 and installs the
dependencies into it from `packaging/requirements-desktop.txt`, which pins every package by hash
(it is generated from `uv.lock`), after the build backend from `packaging/requirements-build.txt`
(also pinned by hash); only wheels are installed, and the checkout is built with that backend. It builds the USB gap shim (`make` and `gcc` are needed) into
`~/.local/lib/fastfoto-linux/` (a folder only you can use), adds an application menu entry and
icon, and links `fastfoto` and `ffscan` into `~/.local/bin`. What it installed is listed in
`~/.local/share/fastfoto-linux/installed.txt`; `--uninstall` removes only that. PySide6 is not a pip
dependency on purpose: the PyPI wheel bundles its own Qt and cannot load the system Kirigami
plugin. Without PySide6 and Kirigami, `fastfoto` says what to install and exits with status 3.

Not done yet: editing photos after the scan (rotate, fix the date, re-run the enhancement), the
scanner's Start button, and processing while still scanning. A scan through the app on real
hardware is still to be tried.

### Flatpak

The Flatpak brings its own Qt and Kirigami, so it needs no distribution packages, and carries
the SANE `epsonds` backend and the USB gap shim, built from this checkout (x86_64 only). The
manifest is `packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml`. You need `flatpak` and
`flatpak-builder` and the Flathub remote, which has the KDE 6.11 runtime and the PySide6 base app.

```sh
flatpak-builder --user --install-deps-from=flathub --force-clean --repo=repo build-dir \
  packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml
flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo repo \
  fastfoto-linux.flatpak io.github.bearyjd.FastFotoLinux
flatpak --user install fastfoto-linux.flatpak                  # install
flatpak run io.github.bearyjd.FastFotoLinux                    # the desktop app
flatpak run --command=ffscan io.github.bearyjd.FastFotoLinux devices   # the developer CLI
flatpak uninstall --user io.github.bearyjd.FastFotoLinux      # remove it again
```

The CI job `flatpak` builds the same bundle and uploads it as an artifact. What the sandbox may
do:

- **USB**: `--device=all`, which exposes all device nodes of the host to the app, not only the
  scanner's. It is needed because libusb and SANE open `/dev/bus/usb/...` themselves and do not
  use the USB portal.
- **Network**: for the Wi-Fi fallback.
- **Files**: your Pictures folder. You can pick any folder under Pictures as the output folder
  and the app writes there directly, with file locks. Any other folder is chosen in the app's folder
  dialog, which grants that folder through the desktop portal (photos are written there as usual;
  the portal's file system has no file locks, so two scans into one such folder at once are not
  serialised).
- **Display**: Wayland, X11 as a fallback, and IPC.
- **From the PySide6 base app (`io.qt.PySide.BaseApp`)**: talk access to a few session-bus names
  (`org.kde.KGlobalSettings`, `org.kde.kconfig.notify`, `com.canonical.AppMenu.Registrar`) and
  read-only access to the KDE settings file (`--filesystem=xdg-config/kdeglobals:ro`).

The settings are kept in `~/.var/app/io.github.bearyjd.FastFotoLinux/`.

## Planned interfaces

1. KDE desktop app (native and Flatpak previews above)
2. Local web page (127.0.0.1)
3. CLI + watched folder

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
