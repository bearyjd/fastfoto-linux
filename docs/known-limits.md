# Known limits

This page says what is unfinished, uncalibrated or unsupported. It is meant to be read before you
trust the software with irreplaceable originals. Keep your prints.

## Evidence: synthetic only

- The numbers behind the automatic features were tuned on **synthetic** images: Auto colour, deskew
  thresholds, the white balance gain scale and presets, and the noise reduction and sharpening
  amounts. They are starting points, not calibrated corrections.
- Tests check arithmetic, exactness and compatibility. They do not show that a photo or a scanned
  page looks better, and no photo-quality or OCR-quality claim is made from them.
- Calibration against real, rights-cleared scans has not been done yet.

## Hardware

- **One scanner model**, the Epson FastFoto FF-680W, tested on one unit. Other models are not
  supported; reports are welcome.
- The USB workaround is a local shim, not a fix in SANE. A patch for SANE's `epsonds` backend is
  being prepared; nothing has been submitted upstream or accepted.
- Observations about the scanner (auto power-off after about an hour, for example) come from testing
  one unit, not from the manufacturer. See the [Runbook](RUNBOOK.md).

## Platforms

- **x86_64 only.** The Flatpak is built for x86_64.
- The Flatpak is not on Flathub yet.
- The native desktop app needs the distribution's PySide6 and Kirigami.

## Features

- **Red-eye** is experimental and off by default, and its suggestions start unaccepted in the editor.
- **Deskew** may abstain on difficult pages (sideways pages, very noisy scans) and is calibrated on
  synthetic pages only.
- **Straighten** in the photo editor resamples pixels and needs equal horizontal and vertical
  resolution.
- **Detail** (noise reduction, sharpening) is computed at full resolution and can take seconds on a
  600 dpi scan. Strong settings remove real texture or add halos.
- **PDF/A is not offered.** No PDF/A code or flag exists.
- **Export presets:** the `lossless` preset writes very large files. The `small` preset does not
  sharpen again after it shrinks the picture.
- **Edit recipes** newer than your app version are rejected by older versions; the JPEG itself stays
  a normal image.
- Not planned: cloud upload, album management, face identity, other scanner models, Windows or macOS
  ports, and generative restoration.

## Privacy

The app works offline. OCR language models are downloaded only when you select them and confirm.
There is no telemetry.

Design notes with the full detail for each feature are in the repository under `docs/design/`.
