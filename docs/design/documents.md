# Documents to PDF — specification and design

Status: accepted 2026-10-15 (the maintainer chose "Documents to PDF" with searchable text).
The first pull request (core and `ffscan doc process`) records what it decided under
"Decisions in the core" at the end.

## Goal
Scan paper documents (letters, forms, receipts) through the FF-680W feeder into **one multi-page PDF per
batch**, with blank pages dropped and **searchable text** when OCRmyPDF is installed — from the `ffscan`
CLI and the desktop app. This replaces the document scanning done in the Windows VM today.

## User stories
1. Load a stack, pick a folder and a name, press Scan: one PDF appears; blank backs are gone; text can be
   searched and copied.
2. Choose colour, grey or black-and-white, and 200, 300 (default) or 600 dpi.
3. Re-make a PDF later from the kept raw pages (`ffscan doc process`).
4. Never lose a scan: raw pages are kept whenever a page was dropped, a step failed or the run stopped.

## Non-goals (this round)
Splitting one batch into several PDFs; PDF/A; page editing; OCR inside the Flatpak (no Tesseract in the
runtime yet); the scanner's hardware auto-crop (`--adf-crp`: the epsonds backend ignores it, checked in the
transport PR); software deskew (the scanner's own deskew stays on).

## Command line
```
ffscan doc scan    --out DIR [--mkdir] [--name NAME] [--colour colour|grey|bw] [--dpi 200|300|600]
                   [--simplex] [--keep-blank] [--ocr auto|on|off] [--lang LANGS]
                   [--keep-raw | --discard-raw] [--net HOST] [-v] [--debug]
ffscan doc process PAGE.png ... --out DIR [--mkdir] [same output options]
```
- Writes `DIR/<NAME>_NNNN.pdf`. NAME defaults to `Document` and is cleaned like album names; NNNN uses the
  same numbering as photos (never reuses a number, never overwrites a file).
- `--ocr auto` (default) adds a text layer when `ocrmypdf` is on PATH, otherwise writes the plain PDF and
  says how to get OCR. `--ocr on` refuses to start if `ocrmypdf` is missing. `--lang` is passed to
  Tesseract (default `eng`; `eng+deu` style allowed, validated against `[a-z_]+(\+[a-z_]+)*`).
- Exit codes as `ffscan`: 0 ok, 1 processing problem (the PDF is still written when possible: e.g. OCR
  failed → plain PDF + warning), 2 usage, 3 scanner/shim/required tool missing, 4 feeder empty, 130 stopped.
- The summary lists pages scanned, blank pages dropped (by page number), pages in the PDF, OCR yes/no,
  the file written and where raw pages were kept.

## Pipeline for one batch
1. **Scan** (later PR): `Color` for colour; `Gray` for grey and for black-and-white (we threshold
   ourselves — better than the backend's fixed threshold); duplex unless `--simplex`; scanner deskew on;
   **full scan length** (the scanner pads the page after the paper ends). Never a fixed paper size: Letter
   would cut Legal pages.
2. **Load** each page: RGB, 8-bit grey or 1-bit PNG — a loader of its own (the photo loader is RGB-only).
3. **Trim** only what is certainly not paper: the white tail after the paper end and, where clearly
   present, the scanner's blue-grey backing strip along an edge. Letter is the scanner's full width, so
   side edges are usually absent. **When unsure, trim nothing** — never cut content.
4. **Blank pages** (mainly duplex backs): ignore a ~5 mm margin and any backing strip; a page is blank when
   it holds fewer than a small number of dark, letter-sized marks with clear contrast to the local paper
   tone. Paper texture, dust, specks and faint show-through from the other side must not count; one line
   of text must keep the page. `--keep-blank` keeps every page. Dropped pages are reported by number and
   their raw pages kept.
5. **Black-and-white**: adaptive threshold (window scaled to dpi) to 1 bit.
6. **Encode**: colour/grey → JPEG embedded as-is (DCTDecode, quality ~85); black-and-white → lossless
   1-bit (CCITT G4 or Flate). Page size from pixels and dpi. Metadata: title = NAME, creation date,
   producer `fastfoto-linux`.
7. **OCR**: `ocrmypdf --output-type pdf --rotate-pages -l LANGS in.pdf out.pdf` on a staging file, with a
   time limit, cancellable. `--output-type pdf` avoids a Ghostscript re-encode of the images. If OCR fails
   or times out, publish the plain PDF, warn, exit 1. Never log recognised text.
8. **Publish** once with the existing safe writer (folder lock, fsync, no overwrite).

PDF library: `img2pdf` (embeds JPEG/1-bit without re-encoding) if its dependencies (pikepdf, lxml) pass the
Flatpak wheel generator and the hashed requirements; otherwise a small in-house writer for exactly these
two image kinds. Tests parse every PDF with a dev-only library (pypdf).

## Desktop app (later PR)
A **Photos | Documents** switch at the top of the form. Documents shows: name, colour (Colour / Grey /
Black and white), resolution, "Both sides (drop blank pages)", "Searchable text" (disabled with
"Install OCRmyPDF: `sudo dnf install ocrmypdf`" when missing). Results list each PDF with its page count,
dropped pages and an Open button. Settings are remembered per mode.

## Flatpak
No OCR this round; the app says searchable text needs the native install. Later: bundle Tesseract + OCRmyPDF.

## PR plan
- **D1** core + `ffscan doc process`: package `fastfoto_linux.documents` (loader, trim, blank, black-and-white,
  PDF writer, OCR runner), CLI, README, this file as `docs/design/documents.md`. No scanner/session changes.
- **D2** `ffscan doc scan`: scan request gains colour mode and length; a document session (raw pages,
  cancel, keep-raw rules) over the existing scanner runner.
- **D3** desktop app Documents mode.
- Later: Flatpak OCR, batch splitting on separator pages, PDF/A.

## Needs real hardware (the user)
Trim on real pages (backing colour, tail), blank detection on real backs, what scanimage writes for Gray,
speed at 300 dpi, OCR quality on real letters.

## Decisions in the core (D1)
What the first pull request settled where the specification left room.

- **PDF library.** `img2pdf` (and `pikepdf`, declared directly because the code imports it; both
  are imported when a PDF is made, not when `ffscan` starts). `img2pdf` pulls `pikepdf`, `lxml` and `packaging`; the x86_64 wheels add
  about 8 MB, `tools/flatpak/gen_wheel_sources.py` accepts every wheel (CPython 3.13 and 3.14
  wheels exist) and the hashed requirements regenerate. It embeds a JPEG as DCTDecode and a CCITT
  G4 TIFF as CCITTFaxDecode untouched and sizes each page from the resolution stored in the
  image. Tests assert both with `pypdf` (a dev-only dependency).
- **Black and white is CCITT G4**, not Flate: it is smaller for text, and the lossless round trip
  is checked pixel for pixel.
- **Colour modes.** `--colour` is a ceiling: a page can lose colour but never gain it.

  | page is \ asked for | colour | grey | bw |
  |---|---|---|---|
  | colour (RGB) | colour | grey | bw |
  | grey (8-bit) | grey | grey | bw |
  | bw (1-bit) | bw | bw | bw |

  A 1-bit page keeps its pixels exactly; it is never thresholded again.
- **Loader.** RGB, 8-bit grey and 1-bit PNGs that carry a resolution (50-2400 dpi, horizontal
  and vertical equal within 1 dpi; Pillow reads pixels per metre as values such as 299.9994, so
  it is rounded). `--dpi` only fills in for a file without one. Palette, alpha, 16-bit and
  non-PNG files are refused by name. Every page file is checked, header and a full decode (a
  truncated PNG is found at once, not after ten pages of work), before any page is processed, and
  nothing is written when one is unusable: a PDF with a page silently missing is worse than none.
  A cancel is honoured before each page.
- **Trim.** The tail is the run of rows at the bottom that is flat, 4 mm or longer and at least
  4 levels brighter than the paper above it; 3 mm of it stays, and always 5 mm below the lowest
  mark on the page. Only the columns that are at least 250 grey levels in the last 2 mm are
  looked at (beside a narrow item the backing runs down the whole frame), and a row's tone is its
  5th percentile, so that writing covering only part of a row, however faint (a footer, a
  watermark at 215-225 on 255), keeps its rows; the median or a high percentile would count such
  a row as tail. Paper as white as the tail is not trimmed at all. The backing strip is the
  scanner's own background colour: the one the photo cropper measured on real scans
  (`BACKGROUND_PRIOR_RGB`, tolerance `BACKGROUND_PRIOR_TOLERANCE`, imported from
  `pipeline.crop`, not copied), and blue over red. A strip is a band of columns that starts at
  the first column of the frame (touches the edge), is backing in at least 95% of its pixels,
  is 3 mm or wider and has paper at least 25 levels brighter beside it, leaving at least 30 mm
  of paper. It is measured on the rows above the tail only, because the tail may be white across
  the whole width. Only colour pages are checked, since grey and 1-bit pages have no hue to tell
  it by. The top is never trimmed. A printed sidebar in any other colour (a blue-grey of
  (140,160,185), slate, navy) is not backing and is never cut; one printed in the backing
  colour itself, edge to edge, full height, would be, and that is the one known way to lose
  printed content. The measured colour may glow brighter in the first millimetres of the frame
  (the photo cropper skips them); a strip whose edge columns are outside the tolerance is simply
  not recognised, which loses only a trim.
- **Blank pages.** Marks are found on the darkest colour channel, shrunk to at most 150 dpi
  keeping the darkest pixel: a spot is a mark when it is 45 grey levels darker than the paper
  around it (measured against an 8 mm morphological closing, so strokes thinner than that are
  ink), or 80 levels darker than the page's usual paper tone, or darker than 96, and its longer
  side is at least 1 mm and its area at least 0.3 mm². The length is judged in source pixels, less
  the factor - 1 pixels that keeping the darkest pixel of a block adds, so a 0.9 mm speck is dust
  at 200, 300 and 600 dpi alike. The 5 mm margin is ignored; it belongs to the scanner's frame, so
  rows trimmed off the bottom take their share of it with them (today the 5 mm kept below the
  lowest mark means the two never overlap). Pencil must be about 45 levels darker than the paper
  (local contrast) to count; lighter pencil is indistinguishable from show-through. A page is
  blank when it has **no** mark, so one short line, a signature, a **lone page number** (decided:
  kept, it cannot be told from content), a punch hole or a scanner streak keeps the page; the cost
  of that caution is a few blank backs kept, never a page lost.
- **Black and white.** A pixel is black when it is darker than 96 (the same level as a mark), or
  when it is 25 levels darker than the mean of an 8 mm window and than the 8 mm closing of the
  page (strokes thinner than the window removed). The mean alone follows uneven lighting but
  draws a black outline round a shaded box and leaves a big black block hollow. Decided: shading
  lighter than 96 is background, so a filled grey box (160 on 240) comes out white with its text
  black, and a black block of 40 x 20 mm is black through and through; a thin rule in mid grey is
  ink, a 6 mm bar of light grey is not.
- **Every page blank.** No PDF is written, the exit code is 1, and the message names
  `--keep-blank`.
- **OCR** runs on a staging copy in a private (mode 0700) `.ffscan-ocr-*` folder of the system
  temporary directory, not the output folder, removed on every path (success, failure, time-out,
  cancel, Ctrl-C), in its own session so that SIGTERM and, after 5 s, SIGKILL reach `ocrmypdf` and everything it
  started. Its output streams go to /dev/null: recognised text is never read, and a chatty tool
  cannot fill a pipe. The result is used only if it is a PDF with the same page count; otherwise
  the plain PDF is published, and the warning says why from the exit code alone (OCRmyPDF's
  documented return codes; code 3, a missing program or language data, names the
  `tesseract-langpack-*` and `tesseract-osd` packages). It is printed once, by the command line.
  The limit is 120 s plus 60 s a page. Ctrl-C, SIGTERM or a cancel
  stops OCR, removes the staging folder and publishes nothing; the page files are untouched.
- **Publishing** takes the folder lock only for numbering and writing, never while OCR runs
  (the lock gives up after 60 s). The number is chosen with `next_index`, shared with photos of
  the same name, with the same retry on collision as photos.

### Needs real hardware or native tools
On Fedora `ocrmypdf` alone pulls Tesseract and the English data but not `tesseract-osd`, the
orientation data that `--rotate-pages` needs (OCRmyPDF's own installation notes name it), so the
hint is `sudo dnf install ocrmypdf tesseract-osd`; without the data OCRmyPDF's rotation step can
fail the whole run, which here falls back to the plain PDF. Read from its source, not run (CI has
no `ocrmypdf`).

Trim on real pages (backing colour, tail tone), blank detection on real backs, what `scanimage`
writes for Gray, speed at 300 dpi, OCR quality on real letters, and whether real `ocrmypdf`
keeps the producer metadata (it may overwrite it; CI has no `ocrmypdf`).

