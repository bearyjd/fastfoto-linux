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
uv run ffscan process page-*.png --out ~/Scans --album "Family Trips"
```

- `devices` only reads sysfs; it never talks to the scanner. Over USB the scanner needs the gap
  shim: build it with `make -C tools/usb-gap-shim`.
- `scan` scans the document feeder (both sides, 600 dpi) and processes the pages. Load photos
  face up, top edge first, as the loading label on the scanner says (the back is scanned first);
  with `--feed face-down` the front is scanned first. These two names changed meaning in this
  version (`face-down` used to mean the back first); the default behaviour is the same.
  `--simplex` scans fronts only.
- Before each USB scan `scan` checks that the scanner answers (it says "Checking the scanner…" in
  the app, and "Waiting for the scanner to answer…" on the terminal if that takes over 2 seconds;
  a scanner that is waking up is given about 15 seconds). A scanner that a failed send left
  half-way through a command, which then swallows every byte, is freed with a little padding and
  `-v` says "scanner was stuck; freed it". The padding is only sent when `ffscan` itself left a
  note that its last scan on this USB address ended badly: an I/O error, a scanimage that had to
  be killed, or one that died of a signal (a busy, jammed or cover-open reply does not count). The
  note is a small file, `scanner-unclean`, in `$XDG_STATE_HOME/fastfoto-linux` or
  `~/.local/state/fastfoto-linux`; it is ignored after a reboot or after 24 hours, and a scanner
  that answers clears it. A scanner that is silent without such a note may be busy with another
  device over Wi-Fi, so nothing is sent to it:
  "The scanner isn't answering. It may be busy with another device, or stuck — switch it off and
  on, then try again." (exit 3). `FF680W_FORCE_UNSTICK=1` sends the padding without a note; use it
  only as a last resort, when you know nothing else is using the scanner. One that still does not
  answer, or that another program holds, also stops the scan before scanimage starts (exit 3).
  The check needs libusb and is skipped without it, for `--net`, and with `FF680W_NO_PRECHECK=1`.
  scanimage runs in the C locale, so its error messages are the English ones the app recognises.
  It stops waiting at its first real error (I/O error, jam, cover open); Cancel gives scanimage up
  to 10 seconds to stop the scanner cleanly, then ends it.
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
- Exit codes: 0 ok, 1 processing error, 2 usage, 3 scanner not found, shim missing, scanner not
  answering or in use by another program, 4 no documents in the feeder. `-v` logs progress,
  `--debug` adds tracebacks.

## Documents to PDF (preview)

Letters, forms and receipts to one multi-page PDF, with blank pages dropped and, when OCRmyPDF is
installed, searchable text. `ffscan doc scan` takes the pages from the document feeder in one go;
`ffscan doc process` makes the same PDF from PNGs you already have. The desktop app has a
Documents mode too (see [Desktop app](#desktop-app-preview)). The design is in
[`docs/design/documents.md`](docs/design/documents.md).

```sh
uv run ffscan doc scan --out ~/Documents/Scans --name "Tax Return" --colour grey --dpi 300
uv run ffscan doc scan --out ~/Documents/Scans --simplex --ocr on --lang eng+deu
uv run ffscan doc process page-*.png --out ~/Documents/Scans --name "Tax Return" --colour grey
uv run ffscan doc process back-*.png front-*.png --out ~/Documents/Scans --ocr on --lang eng+deu
```

- Writes `DIR/<NAME>_NNNN.pdf` (`NAME` defaults to `Document`), numbered like photos: a number is
  never reused and nothing is overwritten. The page files are never changed or deleted. Pages are
  taken in natural filename order and must be RGB, 8-bit grey or 1-bit PNGs that carry their
  resolution (`--dpi` supplies one for a PNG that does not; a file that says otherwise wins) and
  measure at least 10 mm each way at it (a smaller page is refused by name).
- `--colour colour|grey|bw` (default `colour`) is a limit, not a conversion to force: a grey page
  stays grey when `colour` is asked for, and a page already 1-bit stays as it is. Colour and grey
  pages are stored as JPEG and black and white as lossless CCITT G4, all embedded in the PDF
  as they are, and each page gets its physical size from its resolution. In black and white a
  solid dark area (darker than 96 of 255) is black all the way through, and shading lighter than
  that is treated as paper: a grey box comes out white, with its text still black. Dark shading
  is the limit: black text printed on a fill darker than 96 is lost in the black area (light
  text on it stays white), so scan such pages in grey or colour.
- Only what is certainly empty is trimmed, blank white or the scanner's backing; when in doubt
  nothing is cut. Below the paper that is the scanner's white tail: flat rows at the bottom, 4 mm or longer and at least 4 levels
  brighter than the 10 mm above them, of which 3 mm stay. Anything in the tail columns that is
  12 or more levels darker than that white and 0.3 mm or larger, in whole pixels rounded up (a lone
  page number, a faint footer, a watermark) keeps its rows and 5 mm below it, as does every mark; only ink fainter
  than 12 levels, which cannot be told from paper texture, can be trimmed away with the empty
  margin under it. On colour pages it is also the scanner's own backing strip beside a narrow
  item such as a receipt: the blue-grey the photo cropper measured on real scans (RGB distance
  of at most 20 from (202, 210, 219), blue above red), in columns that start at the edge of the
  scan and are backing in at least 99% of their rows, 3 mm or wider, next to paper at least 25
  levels brighter. A tilted receipt is therefore cut only up to its nearest corner. A sidebar
  printed in any other colour is never cut; one printed edge to edge, full height, within that
  distance of the backing colour (a pale blue-grey such as (190, 200, 210)) would be. A grey
  page has no hue to tell backing, pastel paper and a pale slip apart, so it is trimmed at the
  bottom only, never at a side: it loses the white tail only, never a side, and a grey receipt
  keeps its tail (a missed trim, by design; `ffscan doc scan` always scans in colour and makes
  the grey page after trimming). A colour page is trimmed in colour and only then made grey or
  black and white, so `--colour grey` and `--colour bw` trim a colour page exactly as `colour` does.
  Every strip a trim would remove, the tail and each side strip, is then checked over all of its
  columns, on a blurred copy (3x3) so that scanner noise makes no clusters of its own, and a
  dark dot that is 2 pixels shorter than the cluster size counts (two or three pixels at 300
  dpi): if it holds a cluster of 0.3 mm or more that is neither blank
  white nor backing (less than 12 levels darker than the tail's white; a pale slip or sticky
  note hanging below the paper, with pencil on it, is neither), that cut is cancelled and the
  strip stays. Backing there is backing-coloured and joined to a side of the strip; a grey page
  has no backing, since pastel paper and a pale slip look just like it: only blank white is
  exempt. The limits of that check: on a colour page a note of the backing's colour that touches
  the side of its strip cannot be told from backing, a stroke under 3 pixels wide within 2 pixels of both white and backing is taken for the blur of an edge, and a
  stroke 1 pixel wide is diluted to a third of its depth by the blur, so on a slip only 5 levels
  below the tail's white it must be about 21 levels darker than the slip to count. A page
  that would be under 10 mm tall or wide after trimming is kept whole instead of stopping the
  run.
- A page is blank only when it has no mark at all inside its 5 mm margin: dust, paper texture
  and faint show-through from the other side do not count, while a single short line, a
  signature, a lone page number or pencil at least about 45 grey levels darker than the paper
  keep the page (a faint straight line is the exception: see the next point). Pencil fainter than
  that cannot be told from show-through and does not.
  `--keep-blank` keeps every page. The summary lists the dropped pages by number. If every page looks blank nothing is
  written and the exit code is 1.
- The blank rule ignores faint fold creases. A letter folded in thirds has two rows of them on
  its blank back, and a deskewed scan can leave a faint line along the page edge. A mark does
  not count toward "not blank" when it is a faint line. A line is straight (at least 90% of its
  pixels lie within 0.4 mm of its axis, so a slanted one counts), thin (0.8 mm wide on average:
  its area over its length) and at least 2.5 times longer than wide. It is faint when no part of
  it darker than 140 (of 255, on the darkest colour channel) is a mark by itself, which takes a
  dark part at least a millimetre long: a dark speck on a crease is dust, and dark ink touching
  one counts. Real creases measured 0.17 to 0.51 mm thick and 152 to 204 at their darkest; text
  measured 120 or darker. Everything that is not a faint straight line counts however
  faint: a dark ruled line, a page number, round letters, cursive in the thinnest pen, a
  signature wave, a curved line, a pale highlighter band. Limits: a faint straight single stroke
  ("l", "I", "-", "!", a ruled line) is a line too and may be ignored, and so are the stems of a
  faint "i", "j" or "ii"; creases that cross are one big mark and keep the page; a speck under a
  millimetre next to a crease segment under 2 mm long keeps the page; ink lying along a crease
  counts only where it leaves it. Trimming is not affected.
- Searchable text needs `ocrmypdf` and, for its page rotation, Tesseract's orientation data:
  `sudo dnf install ocrmypdf tesseract-osd`. `--ocr auto` (default) uses it
  when present and otherwise writes the plain PDF and says so; `--ocr on` refuses to start
  without it (exit 3); `--ocr off` never runs it. `--lang` takes Tesseract codes (`eng`,
  `eng+deu`). If OCR fails or times out the plain PDF is still written, with one warning and exit
  code 1; the warning says why from `ocrmypdf`'s exit code (for a missing language it names the
  `tesseract-langpack-*` packages to install). OCR works in a private temporary folder, not in
  the output folder. The Flatpak build has no OCR yet.
- Exit codes are those of `ffscan`: 0 ok, 1 a processing problem (an unusable page stops the run
  before anything is written, and a file that is cut off or corrupt counts as unusable), 2 usage,
  3 a required tool is missing (`doc scan`: also the scanner or its shim, which is missing, not
  answering or in use), 4 the feeder is empty (`doc scan` only), 130 stopped (Ctrl-C, SIGTERM or
  SIGHUP).

### Scanning with `ffscan doc scan`

- Load the stack face down, top edge first: the printed side is then scanned first and comes out
  upright, and a one-sided scan (`--simplex`) reads that side (checked on the FF-680W). Both sides
  of every page are scanned unless `--simplex`, and one PDF comes out. `--out`, `--mkdir`, `--name`, `--colour`, `--keep-blank`, `--ocr` and `--lang`
  mean what they mean for `doc process` (so do the summary and its lines, with "pages scanned"
  for "pages read"). `--dpi` is the scan resolution: 200, 300 (default) or 600 dpi. `--net HOST`
  uses a Wi-Fi scanner, as in `ffscan scan`.
- `ffscan doc scan` always scans in colour, whatever `--colour` says: trimming needs colour to
  tell the scanner's backing from pale paper, and the page is made grey or black and white only
  after it has been trimmed. The scan is the scanner's full length, never a fixed paper size, so
  a Legal page is not cut at Letter. The scanner's own deskew stays on. The scanner's PNG carries its
  resolution (checked on the FF-680W); a page that does not say its resolution is taken at the one
  you asked for.
- The scanner's pages go to a hidden folder in `DIR` and are deleted after a clean run. They are
  kept in `DIR/.raw/<UTC time>/` when a page was dropped as blank, searchable text failed, a
  step failed, the run was stopped, or `--keep-raw` says so (`--discard-raw` deletes them even
  then, but only when blank pages dropped are the one reason: a failure or a stop always keeps
  them). The summary says where they are. Kept document pages are in a folder only you can
  read.
- If the scanner stops part-way (a jam, the cover opened), no PDF is made from part of a stack:
  a PDF with its last pages missing is too easy to take for the whole. The pages already scanned
  are kept, the error says where and prints the exact `ffscan doc process` command that makes a
  PDF from the finished pages when you want one. If every page looks blank nothing is written
  and the exit code is 1, with the raw pages kept. `--ocr on` without `ocrmypdf` is refused
  (exit 3) before anything is scanned.
- Needs the scanner (not checked in CI): the Gray PNG that scanimage writes (`doc scan` does not
  ask for it, but pages given to `doc process` may be grey), trimming on real pages, blank
  detection on real backs, speed at 300 dpi, and OCR quality on real letters.

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

A **Photos | Documents** switch at the top of the form chooses what the feeder holds. **Documents**
makes one PDF of the stack, like `ffscan doc scan`: a name, Colour / Grey / Black and white,
200 / 300 / 600 dpi (300 is the default), **Both sides (drop blank pages)** (off scans one side),
**Keep blank pages**, and **Searchable text** with its language (`eng`, or `eng+deu`). The output
folder is the same as in Photos mode; every other setting is remembered separately for each mode.
The window says what it is doing ("Checking the scanner…", "Scanning page 3", "Making the PDF
(page 2 of 5)", "Adding searchable text…") and **Cancel** works at every one of those steps. The
results list shows each PDF with its page count, the blank pages left out (by number), whether it
has searchable text (or why not), and an **Open** button. If the scan stops part-way, or you cancel,
no PDF is made on its own from part of the stack: the pages are kept and **Process them now** makes
the PDF from just those pages with the same settings (it is offered again after a full disk or a
folder that cannot be written to, once that is fixed). Each form says how to load the feeder, as
the label on the scanner does. **Searchable text** needs OCRmyPDF; without it the box is off
and says `Install OCRmyPDF: sudo dnf install ocrmypdf tesseract-osd`. The Flatpak has no OCR yet
and says that searchable text needs the native install; everything else in Documents mode works
there.

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
