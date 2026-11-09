# Your first scan

## Before you start

1. Switch the scanner on and connect it by USB, or have it on your network for Wi-Fi.
2. Over USB, run `ffscan devices`. It only reads sysfs and never talks to the scanner. It should
   list the scanner and say the USB gap shim was found. If not, see the [Runbook](RUNBOOK.md).
   Over Wi-Fi, `ffscan devices` lists USB scanners only and exits with status 3 if there is none.
   `ffscan devices --net HOST` only prints the network scanner name it would use; it does not
   contact the scanner, so it does not show that the scanner is reachable. Pass `--net HOST` to
   every scan command, as below.
3. Load photos face up, top edge first, as the loading label on the scanner says. The back is
   scanned first.

## In the desktop app

The desktop app needs the USB connection; to scan over Wi-Fi without USB, use the command line
with --net HOST. The commands are below.

1. Open **Feedshot**.
2. Pick an output folder, an album name and a date.
3. Press **Scan**. Photos appear in the window as they are saved, each back beside its front.
4. **Cancel** stops the scan. Pages scanned so far are kept, and **Process them now** turns them
   into photos later.
5. Select a photo and press **Edit photo** to adjust it. Edits are saved as a recipe beside the
   picture; **Reset** restores the recipe as it was opened.

## On the command line

With the native install, `ffscan` is in `~/.local/bin`. With the Flatpak there is no host `ffscan`:
run it through Flatpak, for example
`flatpak run --command=ffscan io.github.bearyjd.Feedshot devices`, and use that in place of
`ffscan` in the commands below. Inside the Flatpak, choose an output folder under your Pictures
folder.

```sh
ffscan scan --out ~/Scans --mkdir --album "Family Trips" --date 1975-06
```

For a Wi-Fi scanner, add `--net HOST` (the scanner's name or address), for example
`ffscan scan --out ~/Scans --mkdir --net scanner.local`.

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

`ffscan doc scan` processes the pages and writes the PDF directly, including automatic steps such as
dropping blank pages; there is no review before it writes. The review-first flow, where you check
each page before the PDF is written, is in the desktop app. OCR is optional and needs Tesseract (the
Flatpak has it built in). See the README section "Documents to PDF" for every option.

## Exit codes

0 ok, 1 processing error, 2 usage, 3 scanner not found or not answering, 4 no documents in the
feeder, 130 stopped with Ctrl-C.
