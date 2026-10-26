<!-- glowup:hero start -->
<div align="center">
<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner.svg">
    <img src="docs/assets/banner-light.svg" alt="fastfoto-linux" width="880">
  </picture>
</h1>

[![CI](https://img.shields.io/github/actions/workflow/status/bearyjd/fastfoto-linux/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/bearyjd/fastfoto-linux/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/bearyjd/fastfoto-linux?style=for-the-badge)](LICENSE)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/Qt%20%2F%20PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![KDE](https://img.shields.io/badge/KDE%20Kirigami-1D99F3?style=for-the-badge&logo=kde&logoColor=white)
![Flatpak](https://img.shields.io/badge/Flatpak-4A90D9?style=for-the-badge&logo=flatpak&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-0A0A0A?style=for-the-badge&logo=linux&logoColor=white)
</div>
<!-- glowup:hero end -->

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

## Scanner power settings

In the desktop app, open **Scanner settings**, then **Read settings** to read the
FF-680W's current sleep and AC power-off timers over USB. Choose a supported delay
and use **Apply changes** to write it and verify the returned values. Opening the
page and changing a selection do not write settings; **Off** appears only when the
scanner advertises it. See the [settings guide](docs/SCANNER_SETTINGS.md) for usage
and recovery, and the [capability and API inventory](docs/SCANNER_CAPABILITIES.md)
for documented vendor features, application coverage and remaining gaps.

## Documents to PDF (preview)

Letters, forms and receipts to one multi-page PDF, with blank pages dropped and, when OCR is
available (OCRmyPDF and Tesseract), searchable text. `ffscan doc scan` takes the pages from the document feeder in one go;
`ffscan doc process` makes the same PDF from PNGs you already have. The desktop app has a
Documents mode too (see [Desktop app](#desktop-app-preview)). The design is in
[`docs/design/documents.md`](docs/design/documents.md).

```sh
uv run ffscan doc scan --out ~/Documents/Scans --name "Tax Return" --colour grey --dpi 300
uv run ffscan doc scan --out ~/Documents/Scans --simplex --ocr on --lang eng+deu
uv run ffscan doc process page-*.png --out ~/Documents/Scans --name "Tax Return" --colour grey --cleanup light
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
- `--colour auto` chooses an output mode for each trimmed page. Meaningful colour keeps
  colour; continuous tones, faint marks or uncertain thresholding keep grey. Black and white
  is chosen only when the analysis finds it safe. The default remains `colour`, and scanning
  still captures colour before output conversion. Auto does not change blank-page decisions.
- **Paper cleanup** (`Off`, `Light` or `Strong`; off by default) lightens the paper tone of grey
  and colour pages by a capped amount (at most 1.10x under Light, 1.25x under Strong) and never
  darkens a pixel. Dark ink and strongly coloured marks are not touched at all; faint marks such
  as pencil, grey stamps and pale rules are lightened a little but keep their contrast to the
  paper; a photograph is protected only when it is detected;
  black-and-white pages are not changed, a page with dark paper is left alone, a very large page (a work grid above 12 million pixels, such as 6600 x 4680 pixels at 200 dpi) is left alone to bound memory, and coloured paper is left unchanged when the
  page is written in colour (in grey the hue is gone, so it is lightened). It is a setting of the
  document with an optional override for one page, kept in the review file (format version 3);
  documents saved earlier open with cleanup Off. `--cleanup off|light|strong` sets the level for
  `ffscan doc scan` and `doc process`; without it, `doc process` applies the level a review file
  holds (else Off), and a page's own override in the review file still wins. The design note lists
  the limits; no claim is made about OCR results.
- **Remove specks** (`--despeckle`; off by default) deletes tiny isolated dots from black and
  white pages only: a dot is removed when it is at most 0.30 mm across and no other mark lies
  within 2.5 mm, so full stops, i-dots and other punctuation next to text are kept. Grey and
  colour pages are not changed, and a dot with colour in the source (a red tick) is kept. It is
  a setting of the document (review file format version 5); `--no-despeckle` turns it off, and
  without either flag `doc process` keeps what a review file holds. No claim is made about OCR.
- **Crop** (desktop review, source view): drag a rectangle on a page to keep only that area, at
  least 5 mm on each side. The crop is cut from the trimmed page before the page is turned and
  cleaned, so the preview and the PDF agree. The page is not analysed again, so its blank,
  flag and colour verdicts stay; **Reset crop** brings the whole page back. A crop is kept in the
  review file (format version 4, written only when a page is cropped); there is no command-line
  option to set one; `ffscan doc process RAWDIR` applies a stored crop (`--fresh` ignores it).
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
- The scanner's backing band is cut too, on colour pages. A raw frame is full length, with about
  98 mm of white tail below the paper, so the band is looked for above the white tail and the
  tail goes with it. The scanner straightens the paper by rotating the frame, so the pad of pure
  white (everything outside the rotated scan) is a slanted lower edge and the pad also forms
  wedges up the sides; then come a full-width backing band of 6 to 15 mm (darker next to the
  paper), an optional dark edge line of about 1 mm, and the paper, which is often pure 255 like
  the pad. Rows are judged by what is not white (white is every channel at 240 or more): a band row
  has non-white pixels on at least 50% of its width and backing on at least 95% of those (the
  backing colour or its shadow, within 36 of it), so the wedges do not hide it; a row with more
  than 10 mm of white that touches neither side of the row is not a band row. The band is the
  first run of band rows going up from the bottom of the page above the tail, starting within
  20 mm of its edge: a band of 3 to 20 mm at the bottom and of 1 to 4 mm at the top, and a longer
  run is not a band. The cut is made at the
  band's border with the paper, never through the edge line. At least 1 mm of the band stays at
  the bottom (none at the top), up to ~4 mm when the shadow next to the paper is dark. The last
  check judges the strip that is cut (the band, the pad under it, the first 3 mm of the tail; the
  rest of the tail by the ink search of the tail rule), where pad pixels are exempt one by one
  (white, and the pixels where the pad blends with the backing) and the backing is within 20 of
  the backing colour, joined to a side of the strip or to its first row, the band next to the cut,
  by backing alone: the pad joins nothing, so an island of the backing's colour in the tail is
  not the band. Only the shadow gets more: tone within 36 of the backing colour and bluer than red
  by at most 24 counts as backing in the first 1.5 mm of the strip next to the cut and at the
  pad's edge, and only in a speck, and a pale cluster under 0.5 mm that is within 50 of the
  backing colour is dust. Every other pixel counts, a pale bar, ink bluer than the shadow or a
  darker or not blue mark too; 30 mm of page stay, and grey and 1-bit pages are not cut by the
  band rule. A fleck on the scanner's glass or backing prints as a faint light vertical line
  down the band; in the strip of a band cut a light vertical line up to 0.3 mm wide (a pixel
  or two) is taken for the scanner's, and counts as backing, when it is at least 4 levels
  brighter, in every channel, than the backing beside it and its blue minus red is within 12 of
  the backing's (a pink, yellow, cream or grey line is not one), in at least 90% of the rows
  that have backing on both sides of it, over at least 3 mm of such rows. It joins the parts of
  the band it splits, and a mark that crosses it stays whole. If you see one, clean the scanner
  (glass and backing).
  Limits:
  - a dark streak keeps the strip (ink darkens, so only a lighter line is forgiven); so does a
    light line 0.7 mm wide or more, a light streak over under 90% of the band's rows, one that
    leans across the band (3 degrees moves it 0.6 mm), and, at the top, a band under 3 mm tall;
    a streak with its blurred edge may be a little wider than 0.3 mm (up to about 0.4 to 0.5 mm,
    by resolution), a line of pure white is pad and was never a problem, and a side strip has no
    streak rule;
  - the streak rule is off below 170 dpi, where two pixels are wider than 0.3 mm, and a streak
    keeps the strip; a blank slip of the backing's colour that touches a streak goes with the
    band, as a scrap that touches the band does, but a slip with anything on it keeps the strip;
  - side slivers of up to 2 mm are left (slanted, under the 3 mm of the strip rule);
  - a bar at least half the page wide within 20 of the backing colour, flush with the paper's end
    and with no shadow below it, is cut with the band, like a sidebar of that colour at a side,
    and with it what is in it in the band's own hue; the band's shadow below the bar, ink in
    another hue or a bar in another blue-grey (20 to 36 from the backing colour) keeps it;
  - pale ink or pencil within 1.5 mm of the cut on a slip of the backing's colour is forgiven as
    shadow when its strokes are under 2 mm and, mixed with the slip by the blur, its tone is
    within 36 of the backing colour and bluer than red by at most 24. The hue gate keeps out ink
    bluer than that, not neutral grey: a pencil stroke 1 pixel wide of tone 170 or lighter, or 2
    pixels wide of tone 190 or lighter, is cut with the band, and a stroke 3 pixels wide only
    when lighter than about 190 (about 184 right at the cut);
  - specks under 0.5 mm within 50 of the backing colour in the strip are dust (0.4 mm dots on a
    slip are cut with it);
  - a scrap of the backing's colour that touches the band is taken for the band;
  - a scrap of the backing's colour that touches a side of the page in the first 3 mm of the
    tail is joined to the side and goes with the band (further down, the ink search of the tail
    rule finds it and the page is kept, and so is a scrap that touches neither a side nor the
    band);
  - the last pixel row or two of a glyph whose bottom lies in the band rows may go (0.04 to
    0.13 mm).
- A page is blank only when it has no mark at all inside its 5 mm margin: dust, paper texture
  and faint show-through from the other side do not count, while a single short line, a
  signature, a lone page number or pencil at least about 45 grey levels darker than the paper
  keep the page (a faint straight line is the exception: see the next point). Pencil fainter than
  that cannot be told from show-through and does not. After a band cut the blank-page margin is
  measured in full from the new edge, so the kept edge line is margin, not a mark.
  `--keep-blank` keeps every page. The summary lists the dropped pages by number. If every page looks blank nothing is
  written and the exit code is 1.
- The blank rule ignores faint fold creases. A letter folded in thirds has two rows of them on its
  blank back, and a deskewed scan can leave a faint line along the page edge. A mark does not count
  toward "not blank" when it is a faint line with nothing beside it. A line is straight (at least
  90% of its pixels lie within 0.4 mm of its axis, so a slanted one counts), thin (0.8 mm wide on
  average: its area over its length) and at least 2.5 times longer than wide. It is faint when no
  part of it darker than 140 (of 255, on the darkest colour channel) is a mark by itself, which
  takes a dark part at least a millimetre long: a dark speck on a crease is dust, and dark ink
  touching one counts. It has nothing beside it when no other mark has a pixel more than 0.8 mm and
  at most 4.0 mm off its axis, alongside it: light type that the scanner has blurred leaves only the
  stems of its letters, each a faint straight stroke, but every stem has other stems beside it,
  while the pieces of one crease lie end to end and dust is too small to be a mark. Real creases
  measured 0.17 to 0.51 mm thick and 152 to 204 at their darkest; text measured 120 or darker.
  Everything that is not a faint straight line with nothing beside it counts however faint: a dark
  ruled line, a page number, pale type, a tally, round letters, cursive in the thinnest pen, a
  signature wave, a curved line, a pale highlighter band. A tally counts while its stems are about
  4.0 mm apart or closer. Limits: a lone faint straight stroke ("l", "I", "1", "-", "!", the stem of
  an "i" or "j") and dashed or ruled lines are lines too and may be ignored; so are the stems of a
  tally more than about 4.0 mm apart (each is alone) and a bare tick whose hook is about 2 mm or
  shorter; so is text so pale (darkest about 190 to 196) that only a few isolated stems register,
  in the probes up to about 7 stems, 5 to 18 mm apart, at sizes from 6 to 14 pt (the tests pin 6
  to 12 pt); so are two strokes so close that the far one lies within 0.8 mm
  of the near one's axis (a tight "=" in 10 pt); and ink lying along a crease counts only where it
  leaves it. Kept, on the conservative side: a crease with a mark beside it keeps the page, and
  creases that cross are one big mark and keep the page; a speck under a millimetre next to a
  crease segment under 2 mm long can keep the page (at 300 dpi and finer). Trimming is not
  affected.
- A hole through the paper does not keep a page. A staple, a punch or a clip leaves dark marks that
  show on both sides of the sheet, and a back with nothing else on it was kept for them. On a duplex
  document a counted mark is a hole when its whole shape is the size of a staple hole or of a
  punched hole, it lies within 25 mm of an edge of the page, and the other side of the same sheet
  has a dark shape of the same size at the mirrored spot. A staple hole is at most 1.8 mm long
  (`STAPLE_MAX_MM`; real ones are 0.6 to 1.35 mm). A punched hole is a round disc 4 to 8 mm long
  (`PUNCH_MIN_MM`, `HOLE_MAX_MM`; punched holes are about 6 mm) whose box has a short side at least
  0.8 of its long one (`PUNCH_ASPECT_MIN`) and is at least 0.6 filled (`PUNCH_FILL_MIN`; a disc
  fills 0.78). Anything in between, and a long thin or hollow mark over 1.8 mm (a "0", an "o" of
  print), is never a hole, on either side. The back of a sheet is its front flipped left to right,
  so x becomes the frame width less x and y stays, taken in the scanner's frame with each side's
  trim offsets added back. The shapes are the pixels darker than 160 on the darkest colour channel.
  A mark's shape is the whole dark shape that meets its box, cropped to its own bounding box, not
  clipped by the box or by the 5 mm blank margin (a hole that straddles the margin is cut by it),
  and a shape that is not a hole's size and shape is not a hole (one longer than 8 mm, say): a small
  mark joined to a long dark line is content. They match when each side of the other shape's box is
  within 1.5 times that of the mark's and, shifted by up to 2.0 mm in either direction, they overlap
  by at least 0.5 (intersection over union). One shape explains one mark: two marks side by side do
  not both match the one opposite. A hole shows the grey backing and print is black, so a hole's
  darkest pixel is no darker than 60 on both sides (`HOLE_DARKEST_MIN`: print is darkest 0 to 12,
  real holes 89 to 106), the darkest pixels of the two sides are within 30 of each other
  (`HOLE_TONE_MATCH`: real holes 15), and the mean blue less red of its shape is within 12 of 0
  (`HOLE_TINT`: real holes 4), so black print, pen, stamps and ink of a colour are not holes. A page
  number in Arabic digits set at 8 pt or more in a proportional Sans or Serif font has digits 2 to 3
  mm tall (tested at 8 to 12 pt), over a staple hole, and not round discs, so in no grey is it a
  hole. When a page has two or more holes they share one
  registration: their offsets from the mirrored spot agree within 0.5 mm (`OFFSET_SPREAD_MM`: real
  holes 0.1), because marks that only look alike land at arbitrary offsets inside the window. The
  window is 2.0 mm (`SHIFT_MM`), and a hole is found as far out as its overlap allows, so a bigger
  hole is found further: as measured, up to 2.5 mm for a staple hole of 1.8 mm and up to 3.5 mm for
  a punched hole of 6 mm. A page is blank when it has no counted mark, or when every counted mark is
  a hole; any other mark keeps the page as before.
- Pages are paired in order, 1+2, 3+4 and so on, as the two sides of sheets. `doc scan` pairs the
  pages it scans unless `--simplex`, and `doc process` pairs the pages it is given unless
  `--simplex`, because raw pages from a duplex scan come in pairs: give it pages that start with a
  front. The desktop app pairs when "Both sides" is on. An odd last page has no partner. Pages are
  worked on a sheet at a time, so at most two are in memory. Without pairing, or without a
  partner, there are no holes and a page is judged as it always was.
- Limits of the hole rule: pencil and grey marks rely on size, shape, tint and registration, so the
  same symmetric mark at the mirrored spots of both sides, within 25 mm of an edge, on an otherwise
  blank back is taken for a hole when it is grey and neutral, and the back is dropped. That includes
  smaller grey marks: a grey "." or "-" or "o" of pencil or of grey print (a whole shape of at most
  1.8 mm, as the digits of a numeral set under 8 pt can be) at the mirrored spot of a grey mark on
  the other side. It also includes grey glyphs only x-height tall, lowercase roman folios such as
  "x", "v" and "o", up to about 9 pt in Sans or 11 pt in Serif, at the mirrored spot of a similar
  grey glyph on a grey front (as measured, "ix" on the front and "x" on the back), and grey
  monospace digits at 8 to 9 pt. Each of these drops only the lone folio of an otherwise blank back.
  Black print and ink are never holes. A 1-bit page has no greys (a hole is as black as print), so
  on one nothing is a hole. A rotation between the sides spreads the offsets of holes in proportion
  to the distance between them, so holes 216 mm apart (a three-hole punch on Letter paper) are holes
  only while the sides are within about 0.15 degrees of each other; staple holes close together are
  not affected. Beyond that the page is kept (the safe side). Pairing is by page order, so `doc
  process` given pages that do not start with a front pairs them wrongly: a back then meets another
  front, and is kept unless that front has a shape at the mirrored spot too (the safe side; a
  stapled stack has one, and a back it shows the holes of is dropped all the same, rightly). Pale
  marks (not darker than 160), marks between a staple hole and a punched one in size (1.8 to 4 mm),
  long thin or hollow marks, holes larger than 8 mm or further than 25 mm from every edge, and small
  marks joined to a dark line longer than 8 mm keep the page.
- Searchable text: `ocrmypdf` comes with the app (the installer puts it in the app's own
  environment; from a checkout, `uv sync --extra ocr`), so only Tesseract, the program it drives,
  is left to install. Wherever Homebrew is installed (Bazzite ships it), run
  `brew install tesseract` (English and the orientation data that page rotation needs) and, for
  other languages, `brew install tesseract-lang`. On an immutable system without Homebrew
  (Bazzite, Silverblue: `/run/ostree-booted` exists) run `rpm-ostree install tesseract tesseract-osd`
  (then reboot), or install Homebrew. On classic Fedora run
  `sudo dnf install tesseract tesseract-osd` (`tesseract-langpack-*` for other languages).
  Tesseract is looked for on PATH, then in Homebrew's own bin folder, which the PATH of a menu
  launcher does not have; that folder is used only when it is owned by root or by you and
  nobody else can write to it. With OCRmyPDF 17 or newer (the app's own copy) pages are
  rasterized with pdfium, never Ghostscript; an older `ocrmypdf` found on PATH does not know
  that option and is run without it. `--ocr auto` (default) uses OCR
  when it is all there and otherwise writes the plain PDF and says so; `--ocr on` refuses to start
  without it (exit 3); `--ocr off` never runs it. `--lang` takes Tesseract codes (`eng`,
  `eng+deu`). Download additional language models first with the desktop app's language picker,
  or install the system language packs above. For example, `--lang eng+deu` uses English and German
  models already available locally; the CLI never downloads models. If OCR fails or times out the
  plain PDF is still written, with one warning and exit code 1; a missing-language warning names
  the models needed. OCR works in a private temporary folder, not in the output folder. The
  Flatpak brings Tesseract and OCRmyPDF itself, with English and page-orientation data bundled;
  additional language downloads are available in its desktop app too (see "Flatpak").
- Exit codes are those of `ffscan`: 0 ok, 1 a processing problem (an unusable page stops the run
  before anything is written, and a file that is cut off or corrupt counts as unusable), 2 usage,
  3 a required tool is missing (`doc scan`: also the scanner or its shim, which is missing, not
  answering or in use), 4 the feeder is empty (`doc scan` only), 130 stopped (Ctrl-C, SIGTERM or
  SIGHUP).

### Editing before saving with `ffscan doc process`

Page numbers are counted from 1 in the order the pages are read (the numbers "blank pages
dropped" reports). Without these options nothing changes.

```sh
uv run ffscan doc process page-*.png --out ~/Documents/Scans --drop 2,4,6 --rotate 3:90,5:180
uv run ffscan doc process page-*.png --out ~/Documents/Scans --split 5,9 \
  --part-name "1=Tax return,2=Receipts,3=Letters"
uv run ffscan doc process page-*.png --out ~/Documents/Scans --order 1,3,2,4 --dry-run
```

- `--drop 2,4,6` leaves pages out. `--keep 3` brings back a page that was dropped as blank
  (`--keep-blank` with `--drop` on the same page: the page is left out). A page in both is a usage
  error. `--rotate 3:90,5:180` turns a page clockwise 90, 180 or 270 degrees (the pixels move,
  nothing is resampled). `--order 1,3,2,4` puts the pages in that order and must name every page
  once.
- `--page-colour 2:grey,5:colour,7:auto,8:default` changes individual raw page numbers.
  `auto` requests the page's recommendation; `default` clears its override and follows
  `--colour`. Overrides survive saved review sessions and page reordering. Output is rebuilt
  from retained originals when the chosen mode changes, never from a previous JPEG.
- `--split 5,9` starts a new PDF at pages 5 and 9. If a split page is left out, the next page that
  stays starts the new PDF; a split on the first page that stays does nothing, and a PDF whose
  pages are all left out is not made.
- Every PDF has a name. `--part-name "1=Tax return,2=Receipts"` names the PDFs counted from 1 in
  output order (a name has no comma; it is cleaned like an album name). An unnamed PDF is called
  `NAME` (`--name`), or `NAME (part N)` when there are several. Each is published as
  `<name>_NNNN.pdf` with its own next number for that name, all under one lock on the folder,
  and the name is the PDF's title. It is all parts or none: a cancel or an error before the end
  publishes nothing. OCR runs for each part, with a limit set by that part's page count.
- `--dry-run` prints a table (page, verdict, flags, part, what happens) and writes nothing; the
  output folder must exist. A bad number, an unknown angle, a page given twice, an `--order`
  that is not a permutation or a `--part-name` for a PDF that does not exist is a usage error
  (exit 2), found before any page is read where the page count is enough. If every page is left out
  nothing is written and the exit code is 1.
- Limits: the page files are left as they were. `--rotate` and `--keep` read a page again from
  its file, so they need all the pages in one folder. A `--page-colour` change also needs that
  retained raw folder when conversion requires reading the source again; a choice matching
  the cached actual mode can reuse its bytes. The other edits do not need another source
  read. `ffscan doc scan` has no edit options. Searchable text
  runs afterwards with OCRmyPDF's `--rotate-pages`, which may turn a page back if its text reads
  sideways; a page turned on purpose can therefore come out turned again in a searchable PDF (not
  yet checked with the real tool).

### Reviewing a scan later: `review.json` and a raw folder as the input

```sh
uv run ffscan doc process ~/Documents/Scans/.raw/20261013T230000Z --out ~/Documents/Scans
uv run ffscan doc process ~/Documents/Scans/.raw/20261013T230000Z --out ~/Documents/Scans --fresh
```

- `ffscan doc process RAWDIR` takes a raw folder (`DIR/.raw/<UTC time>/`) in place of page files;
  the pages are the folder's `page-NNNN.png`, counted from 1. A folder with no pages is a usage
  error, and a folder cannot be mixed with page files.
- A raw folder can hold a `review.json`, which the review mode of a scan writes beside the pages
  (owner-only, written atomically), with a thumbnail of every page in `thumbs/page-NNNN.jpg` (480 px
  at most, owner-only). It holds the analysis of the pages and what was edited. The edits in it
  apply first and the options of the command line (`--drop`, `--rotate`, ...) on top of them;
  `--fresh` ignores the file. The saved analysis is used only while the pages and the analysis are
  the ones it was made from; otherwise the pages are analysed again and the edits are put back.
- `ffscan doc process` never writes into the raw folder: no `review.json`, no thumbnails.
- `review.json` is untrusted input: it is read only from a regular file of at most 8 MiB and
  checked completely (names must be the folder's page names, numbers in range, turns 0 to 3, an
  `--order` that is a permutation). If anything is wrong it is ignored with a warning and the
  folder is analysed afresh.
- The raw pages are kept after a review, and nothing is deleted automatically: the desktop app
  offers "Delete the original pages" after a Save, and only then.

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
  and the exit code is 1, with the raw pages kept. `--ocr on` without OCR (`ocrmypdf` and
  Tesseract) is refused (exit 3) before anything is scanned.
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

For a processed photo with its retained original, **Edit photo** opens a separate editor.
Select a suggested eye and **Accept** or **Reject** it; suggestions start unaccepted. Use
**Add eye: click or draw ellipse** for a missed eye, adjust **Strength**, and compare
**Before / After** or **Selected eye · 1:1**. **Undo** restores the previous edit and **Reset**
restores the recipe as it was opened. The editor works from the retained cropped, upright JPEG, rather
than raw scanner data or the enhanced `_a` copy. Missing originals and unprocessed sheets
cannot be edited.

**Brightness** and **Contrast** range from -50 to 50; **Saturation** ranges from -100
(grayscale at full adjustment strength) to 100. Their neutral value is 0. **Adjustment strength** blends these three
adjustments from 0 to 100; it leaves eye-correction strength separate. You can adjust tone
when no eyes were detected. **Reset adjustments** restores neutral tone values and strength
100 while keeping eye corrections. Each slider drag is one Undo step. The page's **Reset**
still restores the recipe as it was opened, including saved adjustments.

Adjustments operate on the retained JPEG's stored RGB channels after accepted red-eye
corrections. They can clip highlights or shadows and do not recover lost detail. Both preview
and export render from the retained source. Existing version-1 red-eye recipes reopen with
neutral adjustments; a tone edit uses the new version-2 recipe. See the
[photo adjustment contract](docs/design/photo-tone.md) for replay and compatibility details.

**Crop and rotate** turns the photo in 90° steps (**Rotate left** / **Rotate right**) and crops it
to a rectangle you drag on the picture or set with the **Left / Top / Right / Bottom** boxes. Cropping
and turning use exact pixels with no resampling, and happen after red-eye correction and before tone
adjustments. While Crop and rotate is open, red-eye editing is disabled; **Show result** previews the
saved framing and size. **Clear crop** removes the crop, **Reset geometry** removes crop and turns,
and each change is one Undo step. Existing saved edits reopen unchanged; using crop or rotate saves a
new version-3 recipe. See the [photo geometry contract](docs/design/photo-geometry.md).

**Straighten**, inside Crop and rotate, levels a slightly tilted photo with the slider or the angle
box, from -15.0° to 15.0° in 0.1° steps (positive turns the picture clockwise). The result is trimmed
to the largest upright rectangle that fits inside the turned picture, so there are no empty corners.
Unlike turns and crops, straightening resamples the pixels. Changing the angle clears any crop, and
a whole slider drag is one Undo step. **Reset straighten** returns to 0.0°. It needs equal horizontal
and vertical resolution and is disabled otherwise; using it saves a new version-4 recipe.

**Save new copy** writes a numbered `_edit-0001.jpg` and matching JSON recipe beside the
source, without replacing the original, enhanced copy or back. Keep both new files to reopen
that edit through **Open saved photo edit**. Leaving with unsaved changes asks before
discarding them. These edits combine accepted red-eye corrections and manual tone adjustments; they do not
inherit earlier colour restoration from the enhanced copy. Automatic red-eye correction during scanning
remains experimental and off by default.

A **Photos | Documents** switch at the top of the form chooses what the feeder holds. **Documents**
reviews the scanned stack before saving PDFs: a name, Auto / Colour / Grey / Black and white,
200 / 300 / 600 dpi (300 is the default), **Both sides (drop blank pages)** (off scans one side),
**Keep blank pages**, and **Searchable text** with a searchable checkbox picker for 124 OCR
languages. Choose one or more languages by name; the picker shows which models are installed,
which need downloading, and their download sizes. The output folder is the same as in Photos mode;
every other setting is remembered separately for each mode.

Use the explicit download action to fetch the missing models for the selected languages before
scanning. If page-orientation data is missing, it is shown separately and must also be explicitly
downloaded. Opening the picker, selecting a language, installing the app, or starting OCR never
starts a model download. Downloads use pinned official `tessdata_fast` models, checked against
expected sizes and Git blob identities before installation in the app's private data directory
under `$XDG_DATA_HOME/fastfoto-linux/tessdata/<revision>/` (`$XDG_DATA_HOME` normally defaults
to `~/.local/share`; Flatpak uses its own app data directory).
Once the required models are installed, recognition works offline. Bundled or system models can
be combined with downloaded models in native and Flatpak installs; downloaded models are also
available to `ffscan doc scan` and `ffscan doc process` in the same installation.

The window says what it is doing ("Checking the scanner…", "Scanning page 3", "Making the PDF
(page 2 of 5)", "Adding searchable text…") and **Cancel** works at every one of those steps. The
results list shows each PDF with its page count, the blank pages left out (by number), whether it
has searchable text (or why not), and an **Open** button. If the scan stops part-way, or you cancel,
no PDF is made on its own from part of the stack: the pages are kept and **Process them now** opens
the review of those pages with the same settings (it is offered again after a full disk or a
folder that cannot be written to, once that is fixed). Each form says how to load the feeder, as
the label on the scanner does. **Searchable text** needs Tesseract (OCRmyPDF comes with the app);
without it the box is off and says `Install Tesseract: sudo dnf install tesseract tesseract-osd`,
or `Install Tesseract: brew install tesseract` on systems with Homebrew (Bazzite has it), or
`Install Tesseract: rpm-ostree install tesseract tesseract-osd (then reboot), or install Homebrew
and run brew install tesseract` on an immutable system without it. If OCRmyPDF is the part that
is missing (a checkout without the OCR extra), the box says `Install OCRmyPDF: run the installer again,
or pip install 'fastfoto-linux[ocr]' for a development install` instead, and when both are missing it
gives both, Tesseract's first; the command line says the same in its message. In the Flatpak the OCR
is built in, so the box is on; if it is off there the installation is damaged, and the box says
`The OCR that comes with this Flatpak is missing, so the installation is broken: reinstall the
Flatpak` (it never suggests `brew`, `rpm-ostree` or `dnf`, which do not reach into the sandbox).

After scanning, the review grid lets you keep or remove pages, rotate clockwise, reorder, and split
into several PDFs with a name for each part. **Only pages to check** filters the warning flags;
**Preview** opens one larger page. **Save PDFs** writes the selected parts, while **Back** keeps the
review edits for later. **Open a past scan…** reopens an original-page folder, including saved edits.
Edits are autosaved and flushed on Save, Back and close; a failed save keeps the review open.
After a successful Save, **Review again** and **Delete the original pages** are offered. Deletion
requires confirmation; declining keeps the originals. Nothing is deleted automatically.

In the grid, arrows focus pages, Space/Delete keep or remove, R/Shift+R rotate clockwise/back,
Ctrl+Left/Right move, S starts a new PDF, and Enter previews. Ctrl+S saves; Esc goes back. Page-edit
keys do not apply while typing a part name.

Install it for your user (no root; nothing to do with `uv` or pip):

```sh
sudo dnf install python3-pyside6 kf6-kirigami     # Fedora; the app needs the distribution's Qt
tools/install-desktop.sh --dry-run                # list what it would do
tools/install-desktop.sh                          # install; run it again to update
tools/install-desktop.sh --uninstall              # remove it again
```

The installer creates a virtual environment that can see the system PySide6 and installs the
dependencies into it from `packaging/requirements-desktop.txt`, which pins every package by hash
(it is generated from `uv.lock`), and `ocrmypdf` with its own dependencies from
`packaging/requirements-ocr.txt` (the `ocr` extra, pinned the same way), after the build backend
from `packaging/requirements-build.txt` (also pinned by hash); only wheels are installed, and the
checkout is built with that backend. It builds the USB gap shim (`make` and `gcc` are needed) into
`~/.local/lib/fastfoto-linux/` (a folder only you can use), adds an application menu entry and
icon, and links `fastfoto` and `ffscan` into `~/.local/bin`. What it installed is listed in
`~/.local/share/fastfoto-linux/installed.txt`; `--uninstall` removes only that. PySide6 is not a pip
dependency on purpose: the PyPI wheel bundles its own Qt and cannot load the system Kirigami
plugin. Without PySide6 and Kirigami, `fastfoto` says what to install and exits with status 3.

Tesseract, which searchable text needs, is a program and not a Python package. When it is not
found the installer prints the command to run (`brew install tesseract` wherever Homebrew is
installed, `rpm-ostree install tesseract tesseract-osd` on an immutable system without it,
`sudo dnf install tesseract tesseract-osd` on classic Fedora).
`tools/install-desktop.sh --with-tesseract` runs the Homebrew command for you (on a terminal it
asks first); it looks for `brew` and `tesseract` in Homebrew's folder only when that folder is owned
by root or by you and nobody else can write to it (otherwise it says why it ignores the folder, and
never runs `brew` from it); it never uses `sudo`, and `--uninstall` leaves Homebrew packages alone
(`--with-tesseract` is ignored with `--uninstall`, and the installer says so).

Not done yet: further photo edits (rotate, fix the date, re-run the enhancement), the
scanner's Start button, and processing while still scanning. A scan through the app on real
hardware is still to be tried.

Started from a terminal, `fastfoto` hides two lines that KDE's own code prints and that do no harm:
`QML Shortcut: ... Only binding to one of multiple key bindings` from KDE's menu items (the context
menu of every text field; its Copy and Paste shortcuts each have several key bindings), and
`kf.kio.widgets.kdirmodel: No node found for item that was just removed` for the hidden
`.ffscan-raw-...` folder of a scan, which is renamed to `.raw/<time>` on purpose. Every other
message is still printed. When the app runs under systemd (its output goes to the journal), those
other lines go to stderr, as Qt's default handler does when it is not logging to the journal.

### Flatpak

Preparing a Flathub submission: see [docs/flathub-submission.md](docs/flathub-submission.md).

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

The Flatpak also brings **searchable text**, so the Documents box needs nothing installed:
Tesseract and its Leptonica library are built from source, with the English (`eng`) and
page-orientation (`osd`, which page rotation needs) data from tessdata_fast; OCRmyPDF is installed
from the same hashed wheels as the native install (`packaging/requirements-ocr.txt`). English
remains bundled. To use additional languages, select them in the desktop app's searchable
checkbox picker and explicitly download the selected missing models once; recognition then works
offline. The CLI uses those installed models too: `--lang eng+deu` works after German has been
downloaded in the Flatpak desktop app. The app does not download models during installation or
OCR. The bundle carries these components under their own licences, all compatible with this
project's GPL-3.0:
Tesseract (Apache-2.0), Leptonica (BSD-2-Clause) and the tessdata_fast data (Apache-2.0); OCRmyPDF
(MPL-2.0) and its wheels keep theirs; the texts of the three built components' licences are in
the bundle under `/app/share/licenses`. The app finds Tesseract in `/app/bin` and bundled models
in `/app/share/tessdata`, and never looks for Homebrew in the sandbox. When selected models come
from both bundled and downloaded data, OCR runs with a temporary combined data directory passed
only to its child processes; the bundled data and the parent process environment stay unchanged.

The CI job `flatpak` builds the same bundle, uploads it as an artifact, installs it, and runs
`tools/ci/flatpak-ocr-smoke.sh` inside the sandbox (Tesseract lists `eng` and `osd`, OCRmyPDF 17
runs, and a generated page of text becomes a PDF whose text layer holds the words). What the
sandbox may do:

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

The reviewed [photo and document enhancement roadmap](docs/roadmaps/enhancements.md)
and [research survey](docs/research/enhancement-survey-2026-10-18.md) preserve the
proposed features, evidence, and release order.

1. KDE desktop app (native and Flatpak previews above)
2. Local web page (127.0.0.1)
3. CLI + watched folder

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
