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
