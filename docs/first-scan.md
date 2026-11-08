# Your first scan

## Before you start

1. Switch the scanner on and connect it by USB (or have it on your network for Wi-Fi).
2. Run `ffscan devices`. It only reads sysfs and never talks to the scanner. It should list the
   scanner and say the USB gap shim was found. If not, see the [Runbook](RUNBOOK.md).
3. Load photos face up, top edge first, as the loading label on the scanner says. The back is
   scanned first.

## In the desktop app

1. Open **fastfoto**.
2. Pick an output folder, an album name and a date.
3. Press **Scan**. Photos appear in the window as they are saved, each back beside its front.
4. **Cancel** stops the scan. Pages scanned so far are kept, and **Process them now** turns them
   into photos later.
5. Select a photo and press **Edit photo** to adjust it. Edits are saved as a recipe beside the
   picture; **Reset** restores the recipe as it was opened.

## On the command line

```sh
ffscan scan --out ~/Scans --mkdir --album "Family Trips" --date 1975-06
```

This scans the feeder (both sides, 600 dpi) and processes the pages. For each photo it writes (`Album` is the album name you gave):

| File | What it is |
|---|---|
| `Album_0001.jpg` | the photo, cropped and turned upright by its faces |
| `Album_0001_a.jpg` | an enhanced copy (colour restoration) |
| `Album_0001_b.jpg` | the back, when it has handwriting (`--backs auto\|always\|never`) |

A sheet whose photo cannot be found (two items fed together, say) is saved as whole pages named
`..._unprocessed.jpg`; nothing is lost. If anything goes wrong, the raw pages are kept in
`DIR/.raw/<UTC time>/` so nothing needs rescanning, and `ffscan process` can rerun them.

Use `--preset small` for smaller files, or `--preset lossless` for PNG photos (very large files).

## Documents to PDF

```sh
ffscan doc scan --help
```

The document flow is review-first: you check each page before the PDF is written. OCR is optional
and needs Tesseract (the Flatpak has it built in). See the README section "Documents to PDF" for
every option.

## Exit codes

0 ok, 1 processing error, 2 usage, 3 scanner not found or not answering, 4 no documents in the
feeder, 130 stopped with Ctrl-C.
