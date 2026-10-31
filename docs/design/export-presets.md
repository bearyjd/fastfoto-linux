# Export presets

`--preset lossless|high-quality|small` on `ffscan scan`, `ffscan process`, `ffscan doc scan` and
`ffscan doc process`. No preset (the default, called "Standard" in the UI) is today's output,
byte for byte; the tests compare it with the legacy encoder calls. A preset name is matched
exactly: no trimming, no case folding. The value reaches no path, log line or subprocess; only
the enum member does, and the file extension comes from the table.

## Photos (scan and process writer)

| preset | format | quality | chroma | max long edge | DPI tag |
|---|---|---|---|---|---|
| none | JPEG `.jpg` | `--quality` (95) | 4:4:4 | none | scan DPI |
| high-quality | JPEG `.jpg` | 95 | 4:4:4 | none | scan DPI |
| small | JPEG `.jpg` | 80 | 4:2:0 | 2048 px, down only | `max(1, round(dpi*scale))` |
| lossless | PNG `.png` (level 6) | n/a | n/a | none | scan DPI |

A preset applies to every file of a sheet: original, `_a`, `_b` and the `_unprocessed` whole
pages. **small also downscales the whole pages**; re-cropping needs a rescan or `high-quality`.
`--preset` and `--quality` are exclusive (usage error, exit 2). `--quality` has no argparse
default so that `--preset small --quality 95` is caught. `ProcessSettings.quality` is likewise
`None` when unset (`effective_quality` gives 95), and any explicit quality next to a preset is
refused at the API level too.

## Document pages (colour and grey)

| preset | encoding | quality | chroma | max DPI |
|---|---|---|---|---|
| none | JPEG | 85 | Pillow default (4:2:0), not passed | none |
| high-quality | JPEG | 92 | 4:4:4 | none |
| small | JPEG | 60 | 4:2:0 | 200 (physical size holds) |
| lossless | PNG, embedded by img2pdf as Flate | n/a | n/a | none |

Black and white pages stay CCITT G4 at native DPI under every preset and are never resampled.
200 DPI keeps OCR usable. Presets are write-time only: `review.json` (format version 6) is
byte-identical with and without one. Analysis encodes with no preset, so a preset makes the
write re-read the raw pages (`on_page` fires); slower, but correct (`EncodedPage.preset`).

## Decisions

- Resampling is `cv2.INTER_AREA` (`output/resample.py`); never up, one scale for both sides.
- No sharpening after the small downscale (follow-up; reuse `photo_edits/detail.apply_sharpen`
  and apply only when a resize happened).
- Metadata is never stripped: EXIF and XMP stay (app-generated, no GPS). No ICC is embedded,
  no Orientation tag is written, pixels stay upright. PNG carries EXIF in `eXIf` and XMP in one
  iTXt chunk (`XML:com.adobe.xmp`) built from our own `build_xmp` bytes.
- TIFF was rejected: libtiff cannot carry our EXIF sub-IFD or XMP.
- Tolerances: a PNG DPI reads back as 599.9988 for 600 (pHYs is per metre), so compare
  `round(dpi)`; PDF page size is compared to 0.5 pt.

## Known limits and open items

- The photo editor and `ffscan library` do not open PNG masters (`photo_edits/source.py` refuses
  non-JPEG; `library/walk.py` lists JPEG suffixes only). Out of scope.
- Numbers: a photo's number is shared across `.jpg` and `.png` (a number is taken if any name
  of the family exists in either format).
- A lossless PNG of a 1200 DPI photo can be about 100 MB. The writer has no output size cap.
- Lossless document pages are large: a full A4 colour page at 600 dpi is about 35 million
  pixels, tens of MB as Flate, and the PDF is assembled in memory, so a long document needs
  that much RAM per kept page. No size warning is shown.
- Bomb limits are unchanged: document pages still come through `documents/loader.py`.
- "Lossless" PDFs: the plain PDF is verified lossless; OCR output relies on ocrmypdf `-O1`
  (lossless), which CI does not test. The OCR command is unchanged.
- **PDF/A is open.** CI has no veraPDF or Ghostscript and no Tesseract. Closing it needs a
  validator in CI and confirming ocrmypdf `--output-type pdfa` options for the pinned version.
  No PDF/A code or flag exists. Do not add `-O2`/`-O3` (lossy).
- Open: real-scan check of small sizes, 200 DPI OCR quality and lossless sizes; editor-save
  presets (needs recipe schema 7).

## GUI (PR B)

Both forms have a `preset` field (`""` is Standard, else an exact preset name) and a **File
size** drop-down (`presetBox`, `docPresetBox`) with a one-line hint. The value is checked by
`gui/form.py:preset_of` (Standard, or `parse_preset`): `update_field` and
`update_document_field` refuse anything else with one fixed message that does not repeat the
input, and `validate` flags it the same way. The Qt slot receives a QVariant and the same check
runs before the value is stored. The prefs file takes only the four exact strings; any other
value (wrong case, spaces, a non-string, a bool) is ignored with the existing log line and the
field stays Standard. Old prefs without the key load as Standard.

- The Photos name preview shows `.png` for Lossless.
- The results grid lists and shows `.png` photos (Qt reads PNG; names use the stem).
- **Edit photo** is disabled for a `.png` original (`photoeditside.eligibility`) with the fixed
  reason shown in the cell. Opening a saved edit whose source is a PNG still hits the editor's
  existing JPEG-only refusal.
- The Documents form passes the preset to `DocumentSettings`; it is write-time only, as in the CLI.
