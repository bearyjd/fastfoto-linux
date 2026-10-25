# Documents to PDF — specification and design

Status: accepted 2026-10-15 (the maintainer chose "Documents to PDF" with searchable text).
The first pull request (core and `ffscan doc process`) records what it decided under
"Decisions in the core" at the end.

## Goal
Scan paper documents (letters, forms, receipts) through the FF-680W feeder into **one multi-page PDF per
batch**, with blank pages dropped and **searchable text** when OCR is available (OCRmyPDF and Tesseract) — from the `ffscan`
CLI and the desktop app. This replaces the document scanning done in the Windows VM today.

## User stories
1. Load a stack, pick a folder and a name, press Scan: one PDF appears; blank backs are gone; text can be
   searched and copied.
2. Choose colour, grey or black-and-white, and 200, 300 (default) or 600 dpi.
3. Re-make a PDF later from the kept raw pages (`ffscan doc process`).
4. Never lose a scan: raw pages are kept whenever a page was dropped, a step failed or the run stopped.

## Non-goals (this round)
Splitting one batch into several PDFs; PDF/A; page editing; OCR languages other than English in the
Flatpak (only `eng` and `osd` are bundled); the scanner's hardware auto-crop (`--adf-crp`: the epsonds backend ignores it, checked in the
transport PR); software deskew (the scanner's own deskew stays on).

## Command line
```
ffscan doc scan    --out DIR [--mkdir] [--name NAME] [--colour auto|colour|grey|bw] [--dpi 200|300|600]
                   [--simplex] [--keep-blank] [--ocr auto|on|off] [--lang LANGS]
                   [--keep-raw | --discard-raw] [--net HOST] [-v] [--debug]
ffscan doc process PAGE.png ... --out DIR [--mkdir] [same output options]
```
- Writes `DIR/<NAME>_NNNN.pdf`. NAME defaults to `Document` and is cleaned like album names; NNNN uses the
  same numbering as photos (never reuses a number, never overwrites a file).
- `--ocr auto` (default) adds a text layer when OCR is available (`ocrmypdf` and Tesseract, see "Where
  the OCR programs are" below), otherwise writes the plain PDF and says how to get it. `--ocr on`
  refuses to start if either is missing. `--lang` is passed to
  Tesseract (default `eng`; `eng+deu` style allowed, validated against `[a-z_]+(\+[a-z_]+)*`).
- Exit codes as `ffscan`: 0 ok, 1 processing problem (the PDF is still written when possible: e.g. OCR
  failed → plain PDF + warning), 2 usage, 3 scanner/shim/required tool missing, 4 feeder empty, 130 stopped.
- The summary lists pages scanned, blank pages dropped (by page number), pages in the PDF, OCR yes/no,
  the file written and where raw pages were kept.

## Pipeline for one batch
1. **Scan** (`ffscan doc scan`): always `Color`, whatever the output colour — trimming needs colour to tell the
   scanner's blue-grey backing from pale paper; grey and black-and-white (our own adaptive threshold)
   are made after trimming. Grey PNGs given to `ffscan doc process` are trimmed very cautiously
   (white tail only; never the sides). Duplex unless `--simplex`; scanner deskew on;
   **full scan length** (the scanner pads the page after the paper ends). Never a fixed paper size: Letter
   would cut Legal pages.
2. **Load** each page: RGB, 8-bit grey or 1-bit PNG — a loader of its own (the photo loader is RGB-only).
3. **Trim** only what is certainly empty (blank white or the scanner's backing): the white tail after the paper end,
   the scanner's full-width backing band (and the pad below it) beyond the paper, and, where clearly
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
7. **OCR**: `ocrmypdf --output-type pdf --rotate-pages -l LANGS --rasterizer pypdfium in.pdf out.pdf` on a
   staging file, with a time limit, cancellable. `--output-type pdf` avoids a Ghostscript re-encode of
   the images, and `--rasterizer pypdfium` keeps Ghostscript (the host's 10.06 is in OCRmyPDF's
   known-defect range) out of the run altogether. That is `--rasterizer pypdfium` only for OCRmyPDF 17 or
   newer: older versions do not know the option and would exit with status 2 ("unrecognized arguments"),
   so for them it is left out (they use Ghostscript). The version is read from the installed
   metadata for the app's own module, and from `ocrmypdf --version` (10 s limit, in a session of its own whose group is
   killed on a time-out; an answer is remembered, a failure is asked again next run) for a
   program; a version that cannot be told gets the command without the option. A status 2 is worded
   "the installed OCRmyPDF (version X) did not accept the options it was given, or could not read the
   PDF": the exit code cannot tell the two apart and the output is never read. If OCR fails
   or times out, publish the plain PDF, warn, exit 1. Never log recognised text.
8. **Publish** once with the existing safe writer (folder lock, fsync, no overwrite).

PDF library: `img2pdf` (embeds JPEG/1-bit without re-encoding) if its dependencies (pikepdf, lxml) pass the
Flatpak wheel generator and the hashed requirements; otherwise a small in-house writer for exactly these
two image kinds. Tests parse every PDF with a dev-only library (pypdf).

## Desktop app (D3)
A **Photos | Documents** switch at the top of the form. Documents shows: name, colour (Colour / Grey /
Black and white), resolution, "Both sides (drop blank pages)", "Searchable text" (disabled with
"Install Tesseract: `sudo dnf install tesseract tesseract-osd`", or `brew install tesseract` on a Homebrew
system, when missing; "Install OCRmyPDF: run the installer again, or `pip install 'fastfoto-linux[ocr]'`
when it is OCRmyPDF that is missing, or both, Tesseract's first). Results list each PDF with its page count,
dropped pages and an Open button. Settings are remembered per mode.

## Flatpak
Searchable text works in the Flatpak (see "Where the OCR programs are" and "OCR in the Flatpak" below);
the form's box is on there, and if the bundle were broken it says so (reinstall) instead of naming a command.

## PR plan
- **D1** core + `ffscan doc process`: package `fastfoto_linux.documents` (loader, trim, blank, black-and-white,
  PDF writer, OCR runner), CLI, README, this file as `docs/design/documents.md`. No scanner/session changes.
- **D2** `ffscan doc scan`: scan request gains colour mode and length; a document session (raw pages,
  cancel, keep-raw rules) over the existing scanner runner.
- **D3** desktop app Documents mode.
- Later: batch splitting on separator pages, PDF/A.

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

  `--colour auto` is a separate request policy: each trimmed source page gets an actual
  colour/grey/B&W decision and a reason. Source PNG kind remains its storage format. Auto
  retains meaningful colour and chooses grey for continuous tones, faint marks or threshold
  risk; ambiguity retains the richer representation. The default remains `colour`.
- **Loader.** RGB, 8-bit grey and 1-bit PNGs that carry a resolution (50-2400 dpi, horizontal
  and vertical equal within 1 dpi; Pillow reads pixels per metre as values such as 299.9994, so
  it is rounded). `--dpi` only fills in for a file without one. Palette, alpha, 16-bit and
  non-PNG files are refused by name. Every page file is checked, header and a full decode (a
  truncated PNG is found at once, not after ten pages of work), before any page is processed, and
  nothing is written when one is unusable: a PDF with a page silently missing is worse than none.
  Each side must be at least 10 mm at the page's resolution (checked once the resolution is
  known, so the resolution errors keep their messages): a smaller file is refused by name, and
  `find_marks`, which a smaller page would crash in OpenCV, raises the same error rather than
  return no marks (no marks means a blank page, and a blank page is dropped).
  A cancel is honoured before each page.
- **Trim.** The tail is the run of rows at the bottom that is flat, 4 mm or longer and at least
  4 levels brighter than the 10 mm of rows directly above it; 3 mm of it stay, and always 5 mm
  below the lowest mark and the lowest ink. Only the columns that are at least 250 grey levels in
  the last 2 mm are looked at (beside a narrow item the backing runs down the whole frame), and
  a row's tone is its 5th percentile, so that writing covering a twentieth of a row, however
  faint (a watermark at 215-225 on 255), keeps its rows; the median or a high percentile would
  count such a row as tail. Where the 10 mm above are as white as the tail, or less than 4
  levels darker, nothing is trimmed; below solid content (a photo, a table) the empty paper is
  that close to the tail's white and is trimmed with it, which is why ink is looked for
  separately. **Ink** is a cluster of 0.3 mm or more (rounded up to whole pixels, at least 2) whose darkest channel
  is 12 levels or more below the tail's white (the median of the last 2 mm), in any tail column
  of the would-be tail, found by connected components on the whole region, not on sampled rows
  and not through the row tones, which cannot see one short word (a lone page number is under
  5% of a row). 12 is four times the scanner's noise and far under any pencil, so dust specks
  below 0.3 mm and noise never stop a cut, while a footer at 225 or 235 on 253-255 paper does.
  Ink fainter than 12 levels cannot be told from paper texture; it can be trimmed away together
  with the empty margin under the last visible mark. The backing strip is the
  scanner's own background colour: the one the photo cropper measured on real scans
  (`BACKGROUND_PRIOR_RGB`, tolerance `BACKGROUND_PRIOR_TOLERANCE`, imported from
  `pipeline.crop`, not copied: RGB distance at most 20 from (202, 210, 219)), and blue over red.
  A strip is a band of columns that starts at the first column of the frame (touches the edge),
  in each of which at least 99% of the rows above the tail are backing (1000 rows are sampled),
  is 3 mm or wider and has paper beside it (the median of its non-backing pixels in the next
  3 mm) at least 25 levels brighter, leaving at least 30 mm of paper. The first column that is
  not 99% backing ends the cut, so the cut of a receipt that is tilted by 2 to 5 degrees stops at
  its nearest corner (a median over the column would cut the corners off), and a tab of paper
  that sticks out stops it where the tab starts. It is measured on the rows above the tail only,
  because the tail may be white across the whole width. Only colour pages are checked, since grey
  and 1-bit pages have no hue to tell it by: a grey page is trimmed at the bottom only, never at
  a side, and a 1-bit page not at all. A grey page therefore loses the white tail only, never a
  side, and a grey receipt keeps its tail (see the last check, below). The top is trimmed only by the band rule (see **Backing band**).
  A colour page is trimmed in colour and only then made grey or black and white (`build` trims
  the loaded page, `encode_page` converts it), so `--colour grey` and `--colour bw` on colour
  pages get the colour trim; `ffscan doc scan` always scans in colour for the same reason. A printed sidebar in any
  other colour (a blue-grey of (140,160,185), slate, navy) is not backing and is never cut; one
  printed edge to edge and full height within the tolerance of the backing colour (a pale
  blue-grey such as (190,200,210), 18 from it, and 40 levels darker than the paper) would be cut
  up to its first column that is not, and that is the known way to lose printed content (see the last check, below, for the other limits). The
  measured colour may glow brighter in the first millimetres of the frame (the photo cropper
  skips them); a strip whose edge columns are outside the tolerance is simply not recognised,
  which loses only a trim.

  **Last check.** Every strip a trim would remove (the tail, each side strip) is examined once
  more over all of its columns and rows, because the tail is judged in the columns that are
  white in the last 2 mm while the cut spans every column: a pale slip or sticky note hanging
  below the paper, with pencil 15 to 40 levels darker on it, is in none of those columns. The
  examination runs on a blurred copy (3x3) of the strip, so that scanner noise (at 5 levels of
  noise, 12 levels is 2.4 sigma: about one pixel in 120 is that far down) makes no
  clusters of its own; a dark dot grows by 2 px, so one that is 2 px shorter than the cluster size
  counts (two or three pixels, under 0.3 mm, at 300 dpi). The cut is cancelled when the strip
  holds an ink-sized cluster that is neither blank white nor backing; blank white is less than
  12 levels darker than the tail's white. On a colour page backing is a backing-coloured area
  joined to a side of the strip; a backing-coloured note in the middle of a strip is not.
  A grey page has no hue, so nothing tells its backing from pastel paper or a pale slip, which
  have the same grey wherever they lie: a pastel margin is backing grey in every row from the top
  of the frame down, and a slip flush with an edge of the frame is joined to the side just as
  backing is. Neither the join to a side nor a column of backing grey tells backing from them, so
  a grey page has no backing: only blank white is exempt, and any other ink-sized cluster, backing
  grey included, is content. Beside a receipt the backing runs on below the paper, in columns
  that are not white, so a grey receipt keeps its tail: a missed trim, accepted (a missed trim
  costs nothing, a cut slip costs the scan) and the reason `ffscan doc scan` scans in colour
  and makes the grey page after trimming.
  On a colour page, pixels within 2 px of both white and backing (the blur of an edge between
  them) are neither a note nor content, but a stroke on a slip borders only one of them. A
  missed trim costs nothing, so the check errs towards keeping, and a dark dot just under the
  cluster size in the tail keeps the tail. The cluster size is 0.3 mm rounded up to whole pixels (3 at 200 dpi, 8 at
  600 dpi, never under 2), because a cluster shorter than 0.3 mm is dust; measured on the
  blurred copy a dark cluster is 2 px larger than on the clean one, while a lone pixel is
  diluted to a ninth of its depth. Known limits: on a colour page a note of the backing's
  colour that touches the side of its strip cannot be told from backing (on a grey page the
  check errs the other way: a grey receipt keeps its tail). A stroke under 3 px wide
  that lies within 2 px of both white and backing is taken for the blur of an edge. A stroke
  1 px wide is diluted to a third of its depth, so on a slip a gap below the tail's white (under
  12 levels) it counts only when more than 3 x (12 - gap) levels darker than the slip: about 21
  on a slip 5 below the white, where the unblurred check kept 15. A page that would be under 10 mm tall or wide after trimming is kept whole
  (logged at debug) so that one such page does not abort the run.
- **Backing band.** On the first real scan every page kept 15 to 21 mm of non-paper at the bottom
  and 1 to 2 mm at the top, which the white-tail rule cannot see: the paper is often pure 255,
  like the scanner's pad, so only the backing tells where it ends. Measured on real pages (numbers
  only; the tests use synthetic pages built from them). A raw frame is full length (2544 x 4642 px,
  393 mm at 300 dpi) with about 98 mm of white tail below the paper. The scanner straightens the
  paper by rotating the frame (1 to 3 degrees): the paper stays axis-aligned and the pad of pure
  white (everything outside the rotated scan) is a slanted lower edge, over about 10 mm of height,
  and the pad also forms wedges up the sides (a white strip 13 mm wide on every row of the band on
  one page, 0.6% of white in every row on another). The page is a JPEG, which leaves pixels at 243
  to 254 next to the slanted pad, neither pad (250 and up) nor backing. From the bottom edge of the
  scan up: the pad, a full-width backing band of 6 to 15 mm (99% of its pixels within 20 of the
  backing colour), darker next to the paper (a shadow of about (182-195, 188-202, 196-210), up to
  1 mm), an optional edge line of about 1 mm (24 to 64% of its pixels under 120), then the paper.
  At the top: at most 2 mm of backing, usually under 0.4 mm on a raw frame, so the top rule rarely
  fires. The rule is this.
  1. The frame has a tail, so the band is looked for above the white tail (`_tail_start`), not on
     the whole frame, and the tail goes with the band.
  2. Rows are judged by what is not white, with white as every channel at 240 or more (the pad,
     the paper at 250 to 255, the codec's ringing). A band row has non-white pixels on at least
     50% of its width and backing on at least 95% of those (backing: within 36 of the backing
     colour, blue over red), so the side wedges do not hide it. Pixels that are neither white nor
     backing but within 2 px of white are the pad's blurred edge and count for neither. A row with
     more than 10 mm of white that touches neither side of the row (a white slip, a narrow item; a
     gap of a few pixels does not split a run of white) is not a band row.
  3. The band is the first run of band rows going up from the bottom of that page, with only pad
     rows (under 50% non-white) below it, starting within 20 mm of its edge: a band of 3 to 20 mm
     at the bottom and of 1 to 4 mm at the top (the run starts within 0.5 mm of the top edge). The
     least counts from the middle of the pad's slant, the most from where it ends. A longer run,
     such as a backing-coloured header or form margin, is not a band and nothing is cut. The
     paper ends where the run ends: the run never extends into the white rows above it, because
     the paper can be pure 255, and the cut is made there, never through the edge line, which is
     not backing and so ends the run. At least 1 mm of the band stays at the bottom (none at the
     top), and up to ~4 mm when the shadow next to the paper is dark: the shadow is darker than
     the backing of the last check (within 20 of it), so the cut never takes a row of the last
     4 mm of the band in which under 95% of the non-white pixels are within 20, and a darker
     shadow stays with the paper.
  4. The last check judges the whole strip that is cut: the band, the slanted pad under it and
     the first 3 mm of the white tail, where the pad's edge rings. Ink anywhere in the rest of the
     tail keeps the page, found by the ink search of the tail rule, so a pale island in the tail
     is not joined to a side by the white around it. In the strip pad pixels are exempt one by one
     (white, and the pixels within 2 px of both white and backing, where the pad's edge passes
     into the backing, on the unblurred strip). Backing is within 20 of the backing colour, as in
     the side strips and the tail, and counts only where it is joined to a side of the strip or
     to its first row, the band next to the cut, by backing alone. The pad joins nothing: a
     separate island of the backing's colour on the pad or in the tail is not the band (one of at
     least 5% of the width moves the tail's start below itself, into the strip). The shadow gets
     more: a cluster of tone within 36 of the backing colour (blue
     over red) is backing where the shadow lies, in the first 1.5 mm of the strip, next to the
     cut, and within 2 px of the pad (the edge of a wedge), and only when it is under 2 mm long
     and bluer than red by at most 24 on average (on the blurred strip). The shadow's specks
     measured on real pages are 0.3 to 1.4 mm long and 0.3 to 19 bluer than red (median 9);
     the backing is 17 bluer than red and the shadow 14, a faded blue ink or a bluish pencil on a
     slip of the backing's colour 30 to 40, so ink in that tone, though it is within 36 of the
     backing, is not the shadow. A pale bar, a stroke of pale ink or a slip in that tone is
     longer and keeps the page. A cluster under 0.5 mm whose pixels are all within 50 of the
     backing colour, of any hue, is dust. Every other pixel goes to the last check, so a mark
     that is darker, not blue or beyond that tolerance, ink bluer than the shadow, and dust of
     ink size in the pad, keep the page, as in the tail. A light streak counts as backing too (see
     `documents/streak.py`): a fleck on the scanner's glass or backing prints as a faint light
     vertical line down the band, a pixel wide plus its blur, 12 to 15 levels brighter than the
     backing (blue minus red 23 to 25) in every row of the band, so it is not backing by colour
     and used to keep the strip, and where it splits the band the far part may reach neither a
     side of the strip (a wedge of pad is there) nor its first row (shadow tone is there). A
     pixel can be a streak's when it is not backing, backing lies 0.3 mm to its left and to its
     right (whole pixels, rounded up), it is 4 levels brighter in every channel than both of
     those two neighbours, and its blue minus red is within 12 of the backing's (17: the
     scanner's streak keeps the tint of the backing it lies on, a pink, yellow, cream or grey
     line does not). A column is a streak when that holds in
     90% of the rows that have backing on both sides of it, over at least 3 mm of such rows, and
     a run of streak columns wider than that offset is none. The streak and its blurred edge, one
     pixel each side in the same rows, count as backing before it is judged whether the backing
     joins a side, in the strict and in the shadow's wide mask alike, and only in the strip of a
     band cut. Where a mark crosses the streak, in the rows where the neighbours of a streak
     column are not both backing and that column is backing by colour (the blur of the mark with
     the streak), the run of streak columns and the pixel each side of it are not backing, so
     that the mark stays whole instead of being cut into dust-sized pieces by the streak. Below
     170 dpi (two pixels are wider than 0.3 mm) the rule is off.
     At least 30 mm of page stay after the bottom cut, and after the top cut
     as well. Where there is no band cut, because there is no band or the cut is not safe, the
     tail rule above runs as before. Colour pages only: grey and 1-bit pages are not cut by the
     band rule (a grey page has no hue to tell the backing by).
  Limits, stated exactly:
  - side slivers of up to 2 mm are left (they are slanted and the strip rule needs 3 mm);
  - a bar at least half the page wide within 20 of the backing colour, flush with the paper's end
    and with no shadow below it, is cut with the band up to the caps above, like a full-height
    sidebar of that colour at a side, and with it what is in it in the band's own hue (bluer than
    red by at most 24). The band's shadow below the bar keeps it, being beyond the 1.5 mm of the
    strip, and so does ink in another hue, or a bar in a blue-grey between 20 and 36 from the
    backing colour;
  - pale ink or pencil within 1.5 mm of the cut on a slip of the backing's colour is forgiven as
    shadow when its strokes are under 2 mm and, mixed with the slip by the blur (3x3), its tone is
    within 36 of the backing colour and bluer than red by at most 24. The hue gate is one-sided:
    it keeps out ink bluer than that, but neutral grey passes it. Measured on a slip of (195, 205,
    215): a pencil stroke 1 pixel wide of tone 170 or lighter, or 2 pixels wide of tone 190 or
    lighter, is cut with the band, and a stroke 3 pixels wide only when lighter than about 190 (about
    184 right at the cut);
  - specks under 0.5 mm within 50 of the backing colour in the strip are dust, of any hue: 0.4 mm
    dots on a slip are cut with it;
  - a dark streak keeps the strip: ink darkens, so only a lighter line is forgiven (a neutral
    grey of 150 and of 100 are tested). A light vertical line up to 0.3 mm wide down the whole
    band is taken for the scanner's; with its blurred edge it may be a little wider (a line
    painted 4 pixels wide at 200 dpi, 5 at 300 and 9 at 600 is still one), and a light line of
    0.7 mm or more (a paper-coloured strip 1 mm wide is tested) keeps the strip. So does a streak
    over under 90% of the rows that have backing on both sides of it (75% is tested), one that
    leans across the band (3 degrees moves it 0.6 mm; other slants are not tested and the result
    does not change steadily with the slant), and at the top a band under 3 mm tall (3.5 mm is
    cut, 2 mm is not). A streak 1 px wide never was a problem: the blur brings it within 20 of
    the backing. A line of pure white is pad and was exempt before. A streak in a side strip is
    not forgiven.
    Below 170 dpi the streak rule is off and a streak keeps the strip. A blank slip of the
    backing's colour that touches a streak is joined to the band by it and goes with the band
    (as a scrap that touches the band does); a slip with anything on it keeps the strip. A
    streak of the backing's tint is forgiven even when it is only 10 levels brighter in every
    channel: after the blur its lead is still over 4.
    A streak means dirt on the scanner: clean the scanner (glass and backing);
  - a scrap of the backing's colour that touches the band is taken for the band;
  - a scrap of the backing's colour that touches a side of the page in the first 3 mm of the
    white tail, which are part of the strip, is joined to the side by backing alone and goes with
    the band; further down, the ink search of the tail rule finds it and the page is kept, and so
    is a scrap that touches neither a side nor the band;
  - the last one or two pixel rows of a glyph whose bottom lies in the band rows may go (0.04 to
    0.13 mm).

  After a band cut the new edge is the paper's, so the blank-page margin is measured in full from
  the new edge (see **Blank pages**).
- **Blank pages.** Marks are found on the darkest colour channel, shrunk to at most 150 dpi
  keeping the darkest pixel: a spot is a mark when it is 45 grey levels darker than the paper
  around it (measured against an 8 mm morphological closing, so strokes thinner than that are
  ink), or 80 levels darker than the page's usual paper tone, or darker than 96, and its longer
  side is at least 1 mm and its area at least 0.3 mm². The length is judged in source pixels, less
  the factor - 1 pixels that keeping the darkest pixel of a block adds, so a 0.9 mm speck is dust
  at 200, 300 and 600 dpi alike. The 5 mm margin is ignored; it belongs to the scanner's frame, so
  rows trimmed off the bottom take their share of it with them (today the 5 mm kept below the
  lowest mark means the two never overlap). After a band cut the new
  bottom edge is the paper's own, so only white-tail rows are passed as `trimmed_bottom`
  (`Trimmed.tail_rows`, 0 after a band cut): the kept edge line is margin, not a mark, and a
  blank back stays blank, while a line 6 mm above the new edge keeps the page. Pencil must be about 45 levels darker than the paper
  (local contrast) to count; lighter pencil is indistinguishable from show-through. A page is
  blank when it has **no** mark, so one short line, a **lone page number** (decided: kept, it
  cannot be told from content), a punch hole with no mirror on the other side (below) or a scanner streak keeps the page; the cost of that
  caution is a few blank backs kept. The one thing the rule lets go is a faint straight thin line with
  nothing beside it (next point), so a lone faint straight stroke can be lost.
- **Fold creases.** The blank back of a letter folded in thirds was kept: its two rows of creases
  are marks. The blank rule (not trimming: `find_marks` has a flag, `ignore_faint_lines`, that
  only `is_blank` sets) ignores faint fold creases, the marks that are faint lines. A line is
  straight, thin and elongated, judged on the principal axis of its pixels (so a slanted one is
  as good as an upright one) in source pixels, less the growth of keeping the darkest pixel of each
  block. Straight: at least 90% of its pixels (`STRAIGHT_SHARE`) lie within 0.4 mm of its axis
  (`STRAIGHT_TOLERANCE_MM`, half of the widest line). Thin: its mean width, the area over its
  length along the axis, is at most 0.8 mm (`STROKE_MAX_MM`). Elongated: it is at least 2.5 times
  longer than wide (`ELONGATION_MIN`). Writing is not straight for long: a loop or a wave is not
  within 0.4 mm of any axis, however thin the pen or faint the pencil, which the earlier thickness
  proxy (area over long side) could not tell at 200 dpi from a crease. A pale highlighter band is
  not thin, and a pencil comma or a dot is not elongated. A line is faint
  when no part of it darker than 140 on the darkest-channel grey (`FAINT_DARKEST`) is a mark by
  itself, judged with the same size and area rule as any mark (`MARK_MIN_MM`, a millimetre long,
  and a third of a square millimetre). A line is judged without its dark specks, the dark parts
  at least 0.5 mm wide (`SPECK_MIN_MM`; thinner ones are the grain of the line itself), each grown
  by `DUST_HALO_MM` (0.3 mm) for its blur, so a speck under a millimetre on a crease is dust,
  and dark ink touching one keeps the page when it would be a mark on its own: its dark parts, and
  whatever of the component lies off the strip that the line (away from the dark parts) follows,
  are judged with the same mask and the same rule. A hairline stem or a "7" that is a mark alone
  is one on a crease; a stroke on its own has no line to follow and is all ink.
  A faint line is ignored only when it has nothing beside it. Light type that the scanner has
  blurred clears the contrast mask only along the stems of its letters, and each stem alone is a
  faint straight line: a page of them was called blank. Writing has other marks beside every stroke
  and a crease has none: a faint line with nothing beside it is a crease. Any other mark with a
  pixel more than 0.8 mm and at most 4.0 mm off the line's axis (`INNER_MM` and `OUTER_MM`),
  alongside it (the pixel's position along the axis inside the line's own length), makes the line a
  mark. The inner limit and the length keep out the neighbours a crease does have: the pieces of one
  crease lie end to end, near the axis and outside each other's length. The neighbours are all the
  mark-sized components, faint lines included, so the stems of pale type are each other's; a
  neighbour must itself be mark-sized, so thin fragments beside the slanted artefact count only
  when they are mark-sized. The any-spot variant, which took any dark spot beside the line, was
  tried and kept a real blank back, whose long artefact has thin fragments 1.9 to 3.8 mm beside it
  (1.0 to 1.2 mm long, 0.17 thick, darkest 194 to 197). The real page is 300 dpi, and fragments of
  that size sit at the mark-size edge: on the real page they are no marks and the back is blank,
  while synthetic ones of 1.0 to 1.2 mm are marks and keep the page at 300 dpi (darkest 176 or
  195) and at 600 dpi when darkest 176, which is pinned as the conservative side; at darkest 195
  they are no marks at 200 or 600 dpi, and ones of 0.8 mm or less are dust. The rule only ever
  turns an ignored line back into a mark: it can keep a page
  that the straight-line rule dropped and never drops one that rule kept. Two real creased
  backs gave the numbers: creases 0.17 to 0.51 mm thick, darkest 152 to 204, in segments 2 to
  23 mm long in two rows at a third and two thirds of the height; one faint tall artefact
  7.6 x 153 mm (about 2.8 degrees off vertical, darkest 176) along the slanted edge of the deskew
  pad; text darkest 0 to 12 on every mark, never above 120. So 140 sits 12 below the darkest
  crease and 20 above the lightest text, and 0.8 mm is just over the thickest crease. On the test
  fixtures at 200, 300 and 600 dpi, crisp, soft and tinted, every crease and the artefact have all
  their pixels within 0.25 mm of their axis (the tolerance is 0.4 mm) and are at least 3.6 times
  longer than wide; the squattest real one, 2 mm long and 0.51 thick, is 3.9. The tolerance
  absorbs a bow of 0.3 mm over 153 mm at every resolution with a 0.4 mm pen (with a 0.5 mm pen
  at 200 dpi it already counts); a bow of 0.4 to 0.6 mm
  passes or not depending on the resolution and the pen, and one of 0.8 mm or more is not straight
  and counts. A wave swinging 0.15 mm either side of a line is that line at every resolution and pen
  tried; one swinging 0.3 mm either side (0.6 mm peak to peak) counts with a 0.3 mm pen, and with a
  0.5 mm pen from about 0.2 mm; a millimetre either side is writing.
  The tests use pencil-like strokes darkest 110 to 150; that is a test value, not a measurement of
  real pencil.
  Known limits, in two groups. **A page may be called blank**, because what is on it is a faint
  straight line with nothing beside it: a lone faint straight stroke ("l", "I", "1", "-", "!", the
  stem of an "i" or "j"); dashed or ruled lines (pieces end to end, or rules more than 4.0 mm
  apart); the stems of a tally more than about 4.0 mm apart (`OUTER_MM`, measured to the nearest
  pixel of the next stem: 3.5 mm keeps the page, 4.5 mm does not, 4.2 mm depends on the resolution);
  a bare tick whose hook is about 2 mm or shorter (on a stroke 8 to 16 mm long: the hook is the
  pixels off the stroke's axis, so at least 90% of the tick, `STRAIGHT_SHARE`, is still straight
  and a longer stroke allows a longer hook; 1.0 mm is ignored, 3.0 mm keeps the page, 1.6 to 2 mm
  depends on the resolution); text so pale (darkest about 190 to 196) that only a few
  isolated stems register (in the probes up to about 7 stems, 5 to 18 mm apart, at sizes from 6
  to 14 pt; the tests pin 6 to 12 pt); two strokes so close that the far one
  lies within 0.8 mm of the near one's axis (a tight "=" in 10 pt, a crease drawn twice); a line
  bowed or waved so little that it counts as straight (above); and ink lying along a crease counts
  only where it leaves it, so a stroke that is a mark only thanks to the part inside the crease can
  be missed. **A page is kept, on the conservative side**: a crease with a mark beside it keeps the
  page, so do two creases less than 4.0 mm apart; creases that cross are one big mark and keep the
  page; a speck under a millimetre next to a crease segment under 2 mm long can keep the page, at
  300 dpi and finer (a stub that short shows nothing of the crease's course, and real segments are
  2 to 23 mm); a speck on a crease counts when the scan is soft enough to grow it past a
  millimetre; fragments of 1.0 mm or more beside the artefact keep the page at 300 dpi.
- **Holes through the paper.** A back with nothing on it was kept for the holes of a staple, which
  show as small dark marks (real ones: neutral, darkest about 90 to 97, 1.5 mm long, 11 to 15 mm
  from one edge and 5 mm from the top, with the same marks mirrored on the front). A hole through
  the paper does not keep a page. On a duplex document a counted mark (as `is_blank` counts it) is a
  hole when its whole shape is the size of a staple hole or of a punched hole, it lies within 25 mm
  of an edge of the page (`EDGE_ZONE_MM`), and the other side of the same sheet has a dark shape of
  the same size at the mirrored spot. A staple hole is at most 1.8 mm long (`STAPLE_MAX_MM`; real
  ones are 0.6 to 1.35 mm). A punched hole is a round disc 4 to 8 mm long (`PUNCH_MIN_MM`,
  `HOLE_MAX_MM`; punched holes are about 6 mm) whose box has a short side at least 0.8 of its long
  one (`PUNCH_ASPECT_MIN`) and is at least 0.6 filled (`PUNCH_FILL_MIN`; a disc fills 0.78).
  Anything in between, and a long thin or hollow mark over 1.8 mm (a "0", an "o" of print), is never
  a hole, on either side. The back of a sheet is its front flipped left to right, so x becomes the
  frame width less x and y stays, taken in the scanner's frame with each side's trim offsets added
  back (`Trimmed.left`, `right`, `top`; the frame width is the trimmed width plus both). Two sides
  of a different resolution, or of frames more than `SHIFT_MM` apart in width, are not a sheet. The
  shapes are the pixels darker than 160 on the darkest colour channel (`HOLE_TONE`; a hole shows the
  dark backing, ink that is only 55 levels darker than the paper is not one). A mark's shape is the
  whole dark shape that meets its box, cropped to its own bounding box, not clipped by the box or by
  the 5 mm blank margin: the margin is not looked at, so a hole that straddles it is counted as a
  mark only where it lies inside, and its box starts at the margin while its dark shape starts
  before it (a real one: 1.19 x 0.68 mm, starting at 4.8 mm from the top, its box at 5.1 mm). A
  shape that is not a hole's size and shape is not a hole (one longer than 8 mm, `HOLE_MAX_MM`,
  say): a small mark joined to a long dark line is content. Only the window of 8 mm round the box is
  labelled, since a shape that reaches its edge is longer than that. They match when each side of
  the other shape's box is within 1.5 times that of the mark's (`SIZE_RATIO`) and, shifted by up to
  2.0 mm in either direction (`SHIFT_MM`; the sides line up to about 1.2 mm on real pages), they
  overlap by at least 0.5 (intersection over union), `MATCH_IOU`. The other side's shape is the
  whole connected dark shape, not what lies in the mark's box: a 6 mm disc over a big dark block
  would otherwise overlap by 0.78. One shape explains one mark (greedy, best overlap first, the
  marks in reading order), so the "1" of "11" is not explained by the one "1" of "10". A hole shows
  the grey backing and print is black, so a hole's darkest pixel is no darker than 60 on both sides
  (`HOLE_DARKEST_MIN`: print is darkest 0 to 12, real holes 89 to 106), the darkest pixels of the
  two sides are within 30 of each other (`HOLE_TONE_MATCH`: real holes 15), and the mean blue less
  red of its shape is within 12 of 0 (`HOLE_TINT`: real holes 4), so black print, pen, stamps and
  ink of a colour are not holes. A page number in Arabic digits set at 8 pt or more in a
  proportional Sans or Serif font has digits 2 to 3 mm tall (tested at 8 to 12 pt), over a staple
  hole, and not round discs, so in no grey is it a hole.
  When a page has two or more holes they share one registration: their offsets from the mirrored
  spot agree within 0.5 mm (`OFFSET_SPREAD_MM`: real holes 0.1), because marks that only look alike
  land at arbitrary offsets inside the window. The window is 2.0 mm (`SHIFT_MM`), and a hole is
  found as far out as its overlap allows, so a bigger hole is found further: as measured, up to 2.5
  mm for a staple hole of 1.8 mm and up to 3.5 mm for a punched hole of 6 mm. A page is blank when
  it has no counted mark, or when every counted mark is a hole; any other mark keeps the page as
  before. The overlap of all shifts is one `cv2.matchTemplate` (sums of products), not a loop: at
  600 dpi a loop is 9000 shifts per mark. Only a page whose every mark is small and near an edge
  gets that far, so a text page costs nothing extra. On real pages the prototype of the rule dropped
  the two backs that were kept for staple holes (overlap 0.84 to 0.88, and 0.59 to 0.87 for three
  marks near a corner), kept every text page, and explained one real hole on a text page of 1128
  marks. That was measured with the prototype. The first shipped version took the shape from the
  dark pixels in the mark's box and kept the app back, one of whose two marks straddles the margin
  (the box cut it short, and the whole shape opposite then failed the size and the overlap); the
  shape is now the whole dark shape. Re-run on the real pages, the rule as shipped before the tone,
  tint and registration checks left both real stapled backs blank and kept every text page.
- **Print is not a hole.** The rule matched any dark shape, so a back with only a page number was
  dropped when the front's number lay at the mirrored spot and was alike (the overlap of the digits
  of "5" and "6", "15" and "16", "35" and "36" is 0.5 or more): with Liberation Sans and Serif at 9
  to 12 pt and 200 and 300 dpi, 251 of 3168 synthetic sheets lost their back. A back with one small
  pen note was dropped by its chance resemblance to the dense text opposite (1.2 to 4.3 % of
  trials), and a front with only a dark stamp was dropped for its lighter ghost on the back. What
  tells a hole from print is its grey, its colour and its registration. Measured on the five real
  holes of two sheets: darkest 89 to 100 on the judged side and 97 to 106 on its partner (at most 15
  apart), mean colour 122 to 139, blue less red at most 4, 0.68 to 1.19 mm, overlap 0.59 to 0.87,
  and every hole of a sheet at the same offset from its partner to within 0.1 mm ((+1.27, -0.68) and
  (+1.19, -0.68) mm on one sheet, (+0.68, +0.25), (+0.68, +0.17) and (+0.76, +0.17) mm on the
  other). Printed text on the same pages is darkest 0 to 12 (5th, 50th and 95th percentile 0, 0 to 2
  and 9 to 12). So the limits are set between them: `HOLE_DARKEST_MIN` 60 (print is darker, holes
  are 89 or more), `HOLE_TONE_MATCH` 30 (twice what real holes differ by), `HOLE_TINT` 12 (three
  times), `OFFSET_SPREAD_MM` 0.5 (five times). The offset of a hole is where its counterpart's
  centre lies from the mirrored spot's, on each axis, and a page with a single hole has no
  registration to compare. The tone and tint are measured over the pixels darker than 160 of the
  whole shape, on both sides. Decided: a hole on a page that is only black and white is not
  recognised (nothing on it is grey), the safe side; pencil is left to shape and registration alone.
- **A staple hole is small; only a punched hole is round.** The round-2 rule told a hole from print
  by its grey, its colour and its registration alone, and a lone grey page number was dropped when
  the front had a grey one at the mirrored spot (tone 89 to 150, Liberation Sans 10 pt, centred at
  the foot: the overlap of the "5" and the "6" is 0.543 against 0.5; over 200 pairs of numbers, back
  only, 7 backs were dropped at tone 89, 5 to 6 at 102, 2 at 128 and 1 at 150, none at 60 to 64 and
  none in Serif). What tells grey print from a hole is its size. Measured on 17 matched real staple
  holes across 5 scans: whole shape 0.59 to 1.35 mm long and 0.42 to 0.93 mm short, aspect 0.57 to
  1.0, fill 0.29 to 0.78, darkest 86 to 108; the digits of a page number at 8 to 12 pt are 2.0 to
  3.0 mm tall. So a mark can be a hole only if its whole shape is at most 1.8 mm long
  (`STAPLE_MAX_MM` 1.8 is a third above the largest real hole), or if it is a round disc: 4 to 8 mm
  long (`PUNCH_MIN_MM`, `HOLE_MAX_MM`), its box with a short side at least 0.8 of the long
  (`PUNCH_ASPECT_MIN`) and at least 0.6 filled (`PUNCH_FILL_MIN`; a disc fills 0.78, a ring such as
  a "0" or an "o" much less). Anything in between is never a hole. A digit is 0.65 to 0.70 em tall,
  1.8 mm at 7.3 to 7.8 pt, but the dark shape of a light digit is smaller than its glyph, so the
  claim starts at 8 pt: probed with 2400 sheets (tones 89 to 150, three fonts, 200 and 300 dpi), 14
  backs were dropped at 7.5 pt (0.6 %) and 32 at 7 pt (1.3 %), none at 8 pt and up. The digits of a
  page number in Arabic digits at 8 pt and more in a proportional Sans or Serif font are over the
  staple size and are not discs; grey monospace digits at 8 to 9 pt can be dropped (the limits,
  below). The size is judged on both sides: the shape opposite must be a hole's size too. Re-run on
  the same 200 pairs (Sans and Serif, 10 and 12 pt, tones 40 to 150, 200 dpi) no back is dropped,
  and none of the 7200 sheets of a grid of tones 89 to 150, three fonts, 8 to 12 pt, 200 and 300 dpi
  loses its back (225 did before). What is left is smaller grey marks, glyphs only x-height tall and
  monospace digits (the limits, below).
- **Pairing.** Pages are paired in order, 1+2, 3+4 and so on, as the two sides of sheets
  (`DocumentSettings.duplex`, default true). `doc scan` pairs the pages it scans unless
  `--simplex`, and `doc process` pairs the pages it is given unless `--simplex`, because raw pages
  from a duplex scan come in pairs: give it pages that start with a front. The desktop app pairs
  when "Both sides" is on. A scan request whose `duplex` and settings disagree is refused (as for
  photos), and the command printed after a scanner failure says `--simplex` for a one-sided scan.
  An odd last page has no partner. A sheet is worked on at a time (two pages in memory at most);
  The two pages of a sheet are loaded together to be judged by each other (a cancel is honoured before each is decoded), then `on_page` and the cancel check run for each page in turn, just before it is judged and encoded. Without pairing, or without a
  partner, there are no holes and a page is judged as it always was.
- **Limits of the hole rule:** pencil and grey marks rely on size, shape, tint and registration: the
  same symmetric mark at the mirrored spots of both sides, within 25 mm of an edge, on an otherwise
  blank back is taken for a hole when it is grey and neutral, and the back is dropped. That includes
  smaller grey marks: a grey "." or "-" or "o" of pencil or of grey print (a whole shape of at most
  1.8 mm, as the digits of a numeral set under 8 pt can be) at the mirrored spot of a grey mark on
  the other side (a lone symmetric pencil dot or dash at the same spot of both sides, on a back with
  nothing else). It also includes grey glyphs only x-height tall, lowercase roman folios such as
  "x", "v" and "o", up to about 9 pt in Sans or 11 pt in Serif, at the mirrored spot of a similar
  grey glyph on a grey front (as measured, "ix" on the front and "x" on the back), and grey
  monospace digits at 8 to 9 pt. Each of these drops only the lone folio of an otherwise blank back.
  Black print and ink are never holes, and a page number in Arabic digits set at 8 pt or more in a
  proportional Sans or Serif font keeps its page in any grey. A 1-bit page has no greys (a hole is
  as black as print), so on one nothing is a hole. A rotation between the sides spreads the offsets
  of holes in proportion to the distance between them, so holes 216 mm apart (a three-hole punch on
  Letter paper) are holes only while the sides are within about 0.15 degrees of each other; staple
  holes close together are not affected. Beyond that the page is kept (the safe side). Pairing is by
  page order, so `doc process` given pages that do not start with a front pairs them wrongly: a back
  then meets another front, and is kept unless that front has a shape at the mirrored spot too (the
  safe side; a stapled stack has one, and a back it shows the holes of is dropped all the same,
  rightly).
- **Black and white.** A pixel is black when it is darker than 96 (the same level as a mark), or
  when it is 25 levels darker than the mean of an 8 mm window and than the 8 mm closing of the
  page (strokes thinner than the window removed). The mean alone follows uneven lighting but
  draws a black outline round a shaded box and leaves a big black block hollow. Decided: shading
  lighter than 96 is background, so a filled grey box (160 on 240) comes out white with its text
  black, and a black block of 40 x 20 mm is black through and through; a thin rule in mid grey is
  ink, a 6 mm bar of light grey is not. **Known limit:** the absolute rule also holds for text
  on the dark fill, so black text printed on a fill darker than 96 (say text at 20 on a fill at
  80) is lost in a solid black area, while light text on it stays white (a reversed heading).
  Black and white turns dark shaded areas solid; a page like that should be scanned in grey or
  colour. A fix that tells text from fill (apply the rule only to large regions with no lighter
  strokes inside) was left out as more than this PR needs.
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

### Where the OCR programs are
`ocrmypdf` is the `ocr` extra of the package (`packaging/requirements-ocr.txt` holds its hashed wheels, and
the Flatpak installs that same file), so the native install has it whatever the distribution packages. It
is run as `python -P -m ocrmypdf` of the app's own interpreter when that can import it (`-P`, safe-path
mode, so that the folder `ffscan` is run in is never searched for modules), else the
`ocrmypdf` on PATH, else the one in Homebrew's folder. Tesseract is a program: on PATH, else in
`/home/linuxbrew/.linuxbrew/bin`, which the PATH of a menu launcher lacks. `ocrmypdf` is started with
the PATH it was started with, then the interpreter's folder, then Homebrew's: the order of the
search, so that Homebrew's folder never shadows the system's own programs, and an unset PATH is
the default path. Homebrew's folder is used (by the search and by the run) only when it is owned by
root or by the user and is not writable by its group or by others; otherwise it is left out and
the reason goes to the `--debug` log. OCR is available only with both programs, and every
message that says it is not names what is missing: Tesseract, OCRmyPDF or both.

Tesseract comes from Homebrew (`brew install tesseract`, `brew install tesseract-lang` for other
languages; it includes `osd`, the orientation data that `--rotate-pages` needs) on an rpm-ostree
system or wherever `brew` is present, from `rpm-ostree install tesseract tesseract-osd` (then
reboot) on an immutable system (`/run/ostree-booted` exists) where `brew` is not, and from
`sudo dnf install tesseract tesseract-osd` on classic Fedora. `ocrmypdf` is not installed from
Homebrew: its formula pulls in Ghostscript and its own Python. Without the orientation data
OCRmyPDF's rotation step can fail the whole run, which here falls back to the plain PDF. Read from
the documentation, run only against stand-ins (CI has no Tesseract, except the real one the Flatpak
job runs in its own sandbox).

### OCR in the Flatpak
The KDE 6.11 runtime has no Tesseract, so the manifest builds Leptonica and Tesseract from the same release
archives as Flathub's `org.kde.skanpage` (hashed, with `x-checker-data`, cmake-ninja, no training tools, no
curl or archive support), before the Python modules so that editing the app reuses their build. The data
is two single files of tessdata_fast 4.1.0: `eng.traineddata` and `osd.traineddata` (the whole data
repository is about 340 MB), installed to `/app/share/tessdata`, which `TESSDATA_PREFIX` names in
`finish-args` (since Tesseract 4 it is the folder of the `.traineddata` files itself). OCRmyPDF 17 needs
Tesseract 4.1.1 or newer and pdfium (a wheel), and `--output-type pdf --rasterizer pypdfium` needs no other
program, so nothing else is built. Its wheels come from `packaging/requirements-ocr.txt`, which the
`python-deps` module installs (it holds the desktop's pins as well);
`tools/flatpak/gen_wheel_sources.py` resolves the environment markers of that closure for CPython 3.13 on
Linux x86_64 and still refuses a marker it cannot decide.

In the sandbox `ocr_tools` looks in `/app/bin` first (the PATH of a Flatpak has it too, but a launcher may
not), never in Homebrew's folder, and runs OCRmyPDF as the module of the app's interpreter. A part that is
missing there is a broken bundle, so the one hint is "reinstall the Flatpak" and no message names brew,
rpm-ostree, dnf or pip. Only English comes with the Flatpak: for another `--lang` the exit-code hint says
so. "In a Flatpak" is `inside_flatpak()` (`/.flatpak-info`), as in the shim code, not `FLATPAK_ID`. The CI
job installs the built bundle and runs `tools/ci/flatpak-ocr-smoke.sh` in its sandbox.

### Needs real hardware or native tools
Trim on real pages (backing colour, tail tone), blank detection on real backs, what `scanimage`
writes for Gray, speed at 300 dpi, OCR quality on real letters, and whether real `ocrmypdf`
keeps the producer metadata (it may overwrite it; CI has no `ocrmypdf`).

## Decisions in `ffscan doc scan` (D2)
What the second pull request settled where the specification left room.

- **One scan job, two sessions.** A photo request carries `mode` and `max_length_mm` to the
  scanimage job, defaulting to colour and the scanner's full length, which is what `ScanJob`
  always used, so a photo scan's argv is unchanged (a test pins it as a literal). A document
  request has no such settings: `mode` and `max_length_mm` are read-only on
  `DocumentScanRequest` (passing them is a `TypeError`), so a document is always scanned
  `--mode Color` (tested for every `--colour` and every resolution), with deskew on and no
  paper size.
- **The document session.** `DocumentScanRequest`, `run_document_session` and
  `DocumentSessionResult` sit beside the photo ones in `fastfoto_linux.session`. What is
  shared lives in `session/scanning.py`: building the scan job, the scanner check with its
  CHECKING and WAITING stages, the scan with its partial pages, the list of pages the scanner
  finished, settling the raw pages, the abort path that keeps them and the DONE callback.
  What differs stays in each session: the photo one pairs sheets into photos, the document one
  makes one PDF; each has its own reasons for keeping the raw pages (`RawReason` is pinned by
  the photo tests and the desktop app, so `DocumentRawReason` is a separate enum). The scanner
  check and the scan runner are looked up in each session's own module when it runs, which is
  also where a test replaces them. The command line shares the `--net` address (a private
  SANE config folder, removed afterwards), the raw policy flags and the stage lines
  (`cli/scan_support.py`).
- **Raw pages.** A document session scans into a hidden folder of the output folder, or
  straight into `DIR/.raw/<UTC time>/` with `--keep-raw`. After the run they are kept when,
  in this order, the run was cancelled or interrupted, the scanner failed, anything else went
  wrong (an unusable page, every page blank, a crash), searchable text failed or timed out,
  `--keep-raw` says so, or a page was dropped as blank (unless `--discard-raw`). Otherwise
  they are deleted. `--discard-raw` therefore only overrides dropped blank pages: a failure,
  a stop or a failed OCR keeps them whatever the flag says. A missing `ocrmypdf` under
  `--ocr auto` is not a failure and does not keep them. The folder of a document's raw pages
  is owner-only (mode 0700; a letter or a bill may be on them), unlike the photo one.
- **A scanner that stops part-way** (a jam, the cover opened) leaves the pages it finished,
  and no PDF is made from part of a stack: the design note's own rule is that a PDF with a
  page missing is worse than none, and a document, unlike photos, is one ordered whole. The
  pages are kept, the error is raised (exit 1) and the command line prints the exact
  `ffscan doc process` command for making a PDF from the finished pages (their names, `--out`,
  `--dpi` and every option that is not the default, quoted for the shell). A page the scanner
  was writing when it stopped is not among them. A cancel during the scan makes no PDF either,
  as it never did for photos.
- **Fallback resolution.** The scanner's PNG carries its resolution (checked on the FF-680W).
  The session still gives the loader the resolution it asked the scanner for as the fallback
  resolution (`DocumentSettings.fallback_dpi`), for a file that does not say: a page that does not
  say its resolution is taken at it, a page that does keeps its own.
- **Loading the feeder.** Load documents face down, top edge first: the printed side is then
  scanned first and comes out upright, and a one-sided scan (`--simplex`) reads that side
  (checked on the FF-680W).
- **Order of checks.** The options are checked first (a usage error costs nothing), then
  `--ocr on` is checked before anything is scanned (before the output folder is made, the
  scanner looked for or checked), then the output folder, the scanner and the scan. The
  session checks the same settings again itself (`check_settings`, shared with
  `build_document`: the name, the OCR languages, `--ocr on` without `ocrmypdf`) and that the
  output folder exists, before it makes the raw folder or reaches for the scanner, so a front
  end that calls it directly cannot start a scan of a stack of paper for a PDF that cannot be
  made. It raises a `DocumentError` (`DocumentSettingsError` or `OcrMissingError`) whose
  message can be shown as it is; the command line keeps its exit codes (2 and 3). An output
  folder that goes away after the options were checked is a problem like any other (exit 1, as
  for `doc process`), not a usage error.
- **Stopping.** Ctrl-C, SIGTERM and SIGHUP are the same cancel as for photos: scanimage is
  stopped, nothing is published, the raw pages are kept and the exit code is 130. A cancel is
  honoured before each page is made and during OCR (the OCR process and its children are
  gone when the command returns).
- **Exit codes.** 0 ok; 1 a problem (OCR failed and the plain PDF was written, every page
  blank, an unusable page, the scanner failed part-way); 2 usage; 3 the scanner or its shim is
  missing, does not answer or is in use, or `--ocr on` has no `ocrmypdf`; 4 the feeder is
  empty; 130 stopped.

### Needs real hardware
The Gray PNG that `scanimage` writes (`doc scan` does not ask for it), trimming on real
pages, blank detection on real backs and speed at 300 dpi.


## Decisions in the desktop app (D3)
What the third pull request settled where the specification left room.

- **One page, two modes.** The scan page keeps one state machine. The controller knows the
  mode (`Photos` or `Documents`), a form per mode and the results of each mode, which it sets
  aside while the other mode is on the page; switching never loses either, and is refused
  while a job runs. The output folder is the Photos form's, so there is one folder for both.
- **The session is reused, not copied.** A document run is `run_document_session`, with its
  pre-scan check, its cancel and its raw-page rules. The form checks the same rules again
  (`check_settings`' name and languages, the folder) only to show a mistake as the user types;
  what the session raises is shown as it is: a `DocumentSettingsError` or `OcrMissingError` as
  "The scan did not start: ...", an `OSError` for the raw folder as "The scan failed. <what the
  system said>". Nothing was scanned either way, and the page is ready to try again. Once pages
  are kept, the same refusals are "No PDF was made. ...", because the scan did start.
- **Stage texts.** `build_document` takes two optional hooks, `on_page(number, total)` and
  `on_ocr()`, which the worker passes through the session's `build=` seam. "Checking the
  scanner…" and "Scanning page N" come from the session's own callbacks.
- **Searchable text.** The box asks for `OcrMode.ON` only when it is ticked and `ocrmypdf` was
  found (looked for at start, at "Check again" and at a mode switch), so a tool that vanished
  since is refused before the stack is scanned. Missing, the box is off with the install hint
  (native) or the "reinstall the Flatpak" text (Flatpak, where the OCR comes with it), and the PDF is made without.
- **Kept pages.** After a cancel, a scanner that stopped part-way, or a PDF that could not be
  saved for a reason the user can fix (a full disk, a folder that cannot be written to or is
  gone), "Process them now" builds the PDF from `kept_pages` with the run's settings and the scan
  resolution as the fallback resolution, and the pages stay on offer until a PDF exists. Searchable
  text that the scan required is only asked for then (`OcrMode.AUTO`): a tool that vanished since
  gives a plain PDF and the usual warning, not a failure. An `OSError` while the PDF is made comes
  back as a result in plain words, without the temporary file's name. A cancel keeps the pages and
  offers them again; an error that another go would repeat (every page blank, an unusable page)
  is not offered again.
- **Loading hints.** Each form says how to load the feeder in the words of the scanner's own
  label: "Load photos face up, top edge first" and "Load pages face down, top edge first".
- **One error for a missing output folder.** `build_document`, `publish_pdf` and
  `run_document_session` raise `OutputFolderMissingError`, a `DocumentSettingsError` that is
  also the `OutputRootMissingError` older callers catch, with one message; `check_settings` finds
  it before a page is read or a stack scanned.
- **A raw folder that is a link.** The private `.raw/<stamp>` folder is opened with
  `O_NOFOLLOW`, so a link planted there is refused (an `OSError`, before anything is scanned)
  and its target's mode is never changed.
- **Settings.** `gui.json` keeps the Photos settings flat as before, the Documents settings
  under `"documents"` and the last mode under `"mode"`. Each save reads the file, changes its
  part and writes it again atomically, so neither mode wipes the other and what a newer
  version wrote is kept; an old file without the new keys loads as it did.

### Needs real hardware
A document scan through the app on the FF-680W, the Open button on a PDF in a Flatpak (it goes
through the desktop portal), and OCRmyPDF on real letters.


## Decisions in editing and several PDFs (review, part C)
What the third review pull request settled where the plan left room.

- **Edits are data, keyed by raw number.** A `DocumentDraft` carries `edits` (a page left out or
  brought back, its turns), `order`, `splits` and `part_names`; `documents/draft_edit.py` changes
  them with pure functions that return a new draft, and `parts(draft)` gives the PDFs. A page is
  named by its raw number, which survives a move of the files.
- **Splits are anchored on a page.** "Page n starts a new PDF". A left-out anchor passes to the
  next page that stays, an empty part disappears, a split on the first page that stays does
  nothing, and a split travels with its page when the order changes.
- **A name for each part.** The plan's one name with consecutive numbers was replaced on the
  maintainer's word: every part has its own name, `NAME (part N)` when there are several and none
  was given (`NAME (part N)` is `PART_NAME_TEMPLATE`), cleaned like an album name, and it is
  the PDF's title. `publish_pdfs` takes the folder lock once and gives each part its own next
  number for its name (two parts of one name get consecutive numbers); it is all parts or none:
  the files are written together or not at all.
- **Writing.** `write_document` reads a page again only when it is turned or carries no bytes: cut
  with its `TrimBox`, turned with `numpy.rot90` (clockwise 90, 180 or 270; exact) and encoded,
  with one decoded page held at a time. Every part is built, with its OCR, before anything is
  published, so a cancel or an error publishes all parts or none. The OCR limit of a part is
  `OCR_BASE_S + OCR_PER_PAGE_S` times that part's pages.
- **Nothing selected.** No page left after edits is `NothingSelectedError`; with no edits all
  pages blank is `AllPagesBlankError` as before.
- **The result.** `DocumentResult` holds `parts` (`PartResult(pdf, name, pages, ocr)`) and
  `removed`; `pdf`, `pages_in_pdf`, `ocr` (the worst outcome) and `ok` are derived. The summary and
  the banner of the app name each PDF.
- **Command line.** `--drop`, `--keep`, `--rotate`, `--split`, `--order`, `--page-colour`, `--part-name` and
  `--dry-run` belong to `ffscan doc process` only, are checked before any page is read where the
  page count is enough, and `--drop` wins over `--keep-blank`. A raw folder as the input is part D.
- **Per-page colour.** `--page-colour 2:grey,5:colour,7:auto,8:default` is keyed by the
  original raw page number. It sets a manual or Auto override; `default` clears the override.
  Reordering, rotation, splitting and restoring a dropped page retain that page's choice.
  Reuse encoded bytes only when their actual mode matches the new resolved output mode;
  otherwise decode the retained source, apply the stored trim/rotation and encode again.
  A conversion requires one retained raw folder; a choice already matching cached actual
  bytes can be applied without rereading. Global Auto still works with arbitrary input paths.
- **Limits.** The page files are left as they were. A page that is turned or brought back is read
  again from its file, so `--rotate` and `--keep` need the pages in one folder (`raw_dir`), and
  are refused with a usage error otherwise. Searchable text uses OCRmyPDF's
  `--rotate-pages`, which may turn a page back that was turned on purpose; checking that with the
  real tool is left to the maintainer.

## Decisions in the review sidecar and a raw folder as input (review, part D)
- **The sidecar.** `draft_store.save_draft` writes `review.json` into the raw folder
  (`.raw/<UTC time>/`, mode 0700) with mode 0600, through a temporary file and `os.replace`, so a
  crash leaves the old file. It holds, for each page, its file name, size and modification time,
  resolution, trim box, verdict, flags, marks (as shares of the page), partner and detail, and the
  document's `duplex`, `keep_blank`, name, colour, OCR mode and languages, the reviewer's edits,
  order, splits and part names, and the `ANALYSIS_VERSION`. Not the pixels and not the ink maps
  (the neighbour flags are settled before it is saved). `list_pages` finds neither the file nor
  the thumbnails.
- **Colour decisions and versioning.** Review format 2 stores each page's source kind,
  recommended mode/reason and optional output-policy override. Format 1 remains readable;
  its missing decisions trigger fresh analysis while existing edits are retained. Unsupported
  future formats are refused. Algorithm changes that affect decisions advance the analysis
  version; a stored user override is independent of the automatic recommendation.
- **Thumbnails.** `analyse_document(..., thumbs=dir)` writes `thumbs/page-NNNN.jpg` (NNNN is the
  raw number) from the trimmed page it already decoded: 480 px on the long side at most, JPEG
  quality 80, mode 0600 in a 0700 folder, the same bytes every time. A thumbnail that cannot be
  written is logged and the page has none.
- **The sidecar is untrusted input.** The file may be damaged, from another version or planted.
  `draft_json.decode_review` reads at most 8 MiB, only from a regular file that is not a link
  (a pipe cannot hang it), checks each value by type (a bool is no number), range and meaning,
  bounds every list, and refuses the whole file at the first fault: a page name that is not the
  name `list_pages` gives at that place (so no path, `..` or other file can be named), a number
  out of range, turns outside 0 to 3, an `order` that is not a permutation, NaN, unknown flags, a
  part name that is not a clean name. Then it is logged as a warning and the folder is analysed
  afresh; the pages are never changed.
- **When the analysis is reused.** Only when the `ANALYSIS_VERSION`, the pairing and blank rule
  (`duplex`, `keep_blank`) and every page's (name, size, modification time) are the ones now.
  Otherwise the pages are analysed again and the edits are put back by raw number
  (`open_draft`, `restore_edits`).
- **Review mode of the session.** `DocumentScanRequest.review` makes `run_document_session` keep
  the raw folder, private from the start, analyse instead of building, save the sidecar and return
  the draft (`DocumentSessionResult.draft`, reason `DocumentRawReason.REVIEW`). The policy
  DISCARD cannot be combined with it. Saving is the separate job `write_document(draft)`. The
  analysis keeps no encoded bytes, so a fresh and a re-opened draft behave alike.
- **What is deleted.** nothing is deleted automatically. A clean run that left pages out, as blank
  or in a review, keeps the raw pages (the fix for pages removed in a review); after a Save the
  desktop app offers "Delete the original pages", and the user decides.
- **A raw folder as the input.** `ffscan doc process RAWDIR` takes a folder with `list_pages`
  (counted from 1). The saved edits apply first and the command-line edits on top; `--fresh`
  ignores the sidecar. The command never writes into the folder.


## Desktop review screen (parts E1 and E2)

The desktop Documents workflow analyses the retained originals, then enters REVIEWING before any
PDF is written. The review grid includes keep/remove, clockwise rotation, reorder, split anchors,
flag filtering, mark overlays and per-part names. Reordering filtered rows uses each page's position
in the full draft order. A bounded asynchronous preview decodes one page on demand.

The review coordinator keeps edits through failed or cancelled Saves. Part names remain local while
typing and are committed before Save, Back or window close; invalid names veto Save. Autosave is
flushed at those boundaries, and a failed flush vetoes closing the window. Open a past scan uses the
same analysis and sidecar validation as the CLI, and Review again reopens the last saved originals.

Successful Save offers "Delete the original pages" with explicit confirmation. Declining leaves the
originals and review edits available; nothing is deleted automatically. Deletion uses the backend's
validated snapshot and never runs from an automatic state transition. The QML components are wheel
package data and the real-window offscreen tests exercise the review actions and deletion choice
using generated synthetic pages.


## Paper cleanup

Paper cleanup lightens the paper tone of grey and colour pages. It has three levels, Off, Light
and Strong, and it is off by default. It lives on the draft: the document has a level
(`DocumentDraft.cleanup`, seeded by `DocumentSettings.cleanup` when a scan is analysed) and a page
may override it (`PageEdit.cleanup`, None follows the document). `write_document` reads the
level from the draft, never from the settings, so a past scan never takes the level from a form.
The command line keeps Off but honours a level stored in the review file.

- **Where it runs.** `render_page` and `encode_page` take the level and clean after the mode is
  rendered, only for grey or colour output. A page is turned before it is cleaned (the work grid
  is anchored at the top left, so the order matters). Blank, hole and colour analysis keep seeing
  the raw pixels; cleanup shows only in the PDF and in an output preview. `ANALYSIS_VERSION`
  stays 3: cleanup is a render-time recipe, not analysis.
- **What it does.** The background is the brightest pixel of each block (the page is reduced to about 150 dpi), closed
  over a window of 10 mm, which is wider than any text stroke, then smoothed over 5 mm. The paper
  level is the 90th percentile of that background. A pixel gets a gain of at most 1.10 (Light, target
  245) or 1.25 (Strong, target 255) that grows from none at 80% (Light) or 75% (Strong) of the paper
  level to the whole gain at 88% or 85%. A pixel at or below 78% of its local paper is ink and is
  never changed, and the weight rises to the full gain at 90%. No pixel gets darker, the order of
  tones is never reversed (a lighter pixel never comes out darker than a darker one, though
  both can reach 255), and the contrast of a mark to its paper never drops. All of it is integer
  arithmetic, so a repeat run gives the same bytes.
- **What it leaves alone.** Black-and-white output is byte for byte what it was:
  black-and-white pages are not changed, and coloured paper is left unchanged when the page is written in
  colour: a colour page whose paper chroma is above 16 is skipped whole (in grey the hue is
  gone, so cream or yellowed paper is whitened by choosing grey). A page whose paper level is
  below 160 is skipped as too dark. Coloured marks keep their colour, because the gain fades with
  the chroma over the paper's own. Photographs are protected in the page: cells of 4 mm in which
  at least 20% of the pixels sit between 78% and 92% of the paper are protected with their
  neighbours.
- **Memory and time.** The full-resolution passes run in bands of 512 rows (the banded result is
  the whole-page result) and a cancel is honoured before each band. The peak is the page, the
  output and the low-resolution maps. The integer box sums of the work grid cost about 42 bytes
  per work pixel at the peak (the page at 150 dpi, or at its own resolution when that is lower),
  so a page whose work grid has more than 12 million pixels (for example 6600 x 4680 pixels at
  200 dpi, which peaked at 1.2 GiB) is left as it is, with the status `too_large`, noted in the
  debug log; an A4 page at up to 300 dpi is cleaned (about 360 MiB at 299 dpi). The check comes
  after Off and black and white, and before the paper level is looked at.
- **The sidecar.** The review file is format version 3 only when the draft holds a cleanup level
  or an override, and version 2 (byte for byte as before) otherwise. The decoder accepts versions
  1, 2 and 3 strictly: version 3 has a required document level and edits with exactly the keys
  include, turns, colour and cleanup; a cleanup key in version 1 or 2 is refused. Older files
  open with cleanup Off, and a stale re-analysis keeps the saved level.
- **Cached bytes.** A page that carries encoded bytes is reused only when its mode and its
  effective cleanup level (Off for black and white) match what the draft now asks for.
- **OCR.** OCRmyPDF still reads the assembled PDF, whose images are now the cleaned pages. There
  is no OCR-only image, and no claim is made that OCR gets better or worse.
- **Known limits.** A shaded box wider than 10 mm may lighten under Strong. A high-key photograph
  lighter than 92% of the paper, or smaller than a 4 mm cell, is not detected. A protected region
  has a less-whitened rim of about 4 to 8 mm. The quality evidence is synthetic pages only.

## Manual crop

- **What it is.** In the desktop review a reviewer drags a rectangle on a page's source view
  (the trimmed, unturned page) to keep only that area. Crop is a per-page edit, `PageEdit.crop`;
  the command line has none. Rotation stays in 90 degree steps; there is no straighten.
- **Order.** `load_page`, `trim.apply`, `edited_page` (crop, then the quarter turns), then
  `render_page` or `encode_page`, where the paper cleanup runs. The preview and the PDF both call
  `edited_page` (`documents/page_crop.py`), so they share one transform.
- **Not analysed again.** A crop never re-runs the blank, flag, colour or hole analysis; the
  page is not analysed again and `ANALYSIS_VERSION` stays 3. An Auto colour page keeps its
  stored decision.
- **Units.** A crop is `PageCrop(left, top, right, bottom)`, whole numbers from 0 to 10 000 of the
  trimmed page's width and height, half open. Units, not pixels, so a stale sidecar that is
  analysed again with another trim box or dpi still lands inside the page. `to_units` rounds a
  pixel box outward and `crop_box` rounds inward, which gives the same pixels back for a page of
  up to 10 000 pixels a side. A side shorter than 5 mm (only after a re-analysis shrank the page)
  grows around its centre to at least 5 mm, or to the whole axis if the page is smaller; a crop
  is never dropped. The whole page is no crop.
- **Size and dpi.** The cropped page keeps the page's dpi, so the PDF page is the crop's physical
  size. The encoded bytes made at analysis are reused only for an uncropped page.
- **Cleanup on a crop.** The paper level, the `too_large` limit and the `dark` verdict are judged
  on the cropped pixels, so a crop can turn a `too_large` page into an applied one, or a crop that
  is mostly photograph into `dark`. Preview and PDF agree because both use `edited_page`.
- **The sidecar.** The review file is format version 4 only when a page is cropped (else 3 for
  cleanup, else 2, byte for byte as before). Version 4 has a required document cleanup level and
  edits with exactly the keys include, turns, colour, cleanup and crop; crop is null or four
  whole numbers. A crop key in version 1, 2 or 3 is refused. Older files never gain a crop, and a
  stale re-analysis keeps the saved crop.
- **Known limits.** OCRmyPDF reads the cropped page, so a crop with little text may rotate
  oddly. The quality evidence is synthetic pages only.
