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
7. **OCR**: `ocrmypdf --output-type pdf --rotate-pages -l LANGS in.pdf out.pdf` on a staging file, with a
   time limit, cancellable. `--output-type pdf` avoids a Ghostscript re-encode of the images. If OCR fails
   or times out, publish the plain PDF, warn, exit 1. Never log recognised text.
8. **Publish** once with the existing safe writer (folder lock, fsync, no overwrite).

PDF library: `img2pdf` (embeds JPEG/1-bit without re-encoding) if its dependencies (pikepdf, lxml) pass the
Flatpak wheel generator and the hashed requirements; otherwise a small in-house writer for exactly these
two image kinds. Tests parse every PDF with a dev-only library (pypdf).

## Desktop app (D3)
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
     the backing is 17 bluer than red and the shadow 14, a faded blue ink or a pencil on a slip
     of the backing's colour 30 to 40, so ink in that tone, though it is within 36 of the
     backing, is not the shadow. A pale bar, a stroke of pale ink or a slip in that tone is
     longer and keeps the page. A cluster under 0.5 mm whose pixels are all within 50 of the
     backing colour, of any hue, is dust. Every other pixel goes to the last check, so a mark
     that is darker, not blue or beyond that tolerance, ink bluer than the shadow, and dust of
     ink size in the pad, keep the page, as in the tail. At least 30 mm of page stay after the
     bottom cut, and after the top cut
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
  - pale ink in the band's own blue-grey (within 36 of the backing colour and bluer than red by
    at most 24), within 1.5 mm of the cut on a slip of the backing's colour, is forgiven as
    shadow when its strokes are under 2 mm;
  - specks under 0.5 mm within 50 of the backing colour in the strip are dust, of any hue: 0.4 mm
    dots on a slip are cut with it;
  - a scrap of the backing's colour that touches the band is taken for the band;
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
  cannot be told from content), a punch hole or a scanner streak keeps the page; the cost of that
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

### Needs real hardware or native tools
On Fedora `ocrmypdf` alone pulls Tesseract and the English data but not `tesseract-osd`, the
orientation data that `--rotate-pages` needs (OCRmyPDF's own installation notes name it), so the
hint is `sudo dnf install ocrmypdf tesseract-osd`; without the data OCRmyPDF's rotation step can
fail the whole run, which here falls back to the plain PDF. Read from its source, not run (CI has
no `ocrmypdf`).

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
  (native) or "Searchable text needs the native install" (Flatpak), and the PDF is made without.
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
