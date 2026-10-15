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

- `check` walks the folder (symlinks are not followed; `.jpg`/`.jpeg` in any case), prints how
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
  permissions, and a `fastfoto-reorient-manifest.csv` listing old and new tags. It refuses a row
  whose file changed since `check` (size, modification time or content hash), never overwrites a
  file in `DEST` and refuses a `DEST` that is inside the library or contains it.
- Then review `DEST` in your photo viewer and, once you are happy, copy it over the library
  yourself. Running `check` on `DEST` again proposes nothing to rotate.

## Planned interfaces

1. KDE desktop app (native + Flatpak)
2. Local web page (127.0.0.1)
3. CLI + watched folder

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
