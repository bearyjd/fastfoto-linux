# fastfoto-linux

An open-source Linux app for the Epson FastFoto FF-680W photo scanner. It scans through SANE (the desktop
app over USB; the command line also over Wi-Fi), pairs photo backs with their fronts, turns pictures upright, and lets you review
and reverse each edit. It also turns paper into searchable PDFs.

!!! note "Not affiliated with Seiko Epson"
    Not affiliated with Seiko Epson. "Epson" and "FastFoto" are names of their owners and appear
    here only to say which scanner this software is for: the Epson FastFoto FF-680W. This is
    independent software and is not the vendor's FastFoto application.

!!! warning "Early development"
    This is a preview. It was developed and tested on one scanner. The tuned constants behind the
    automatic features were set on synthetic images, not on real scans; see
    [Known limits](known-limits.md) before you rely on any of them.

## Where to start

- [Install](install.md): the native installer, or the Flatpak.
- [Your first scan](first-scan.md): from the feeder to files in a folder.
- [Runbook](RUNBOOK.md): what to do when the scanner is not found, stuck, or silent.
- [Known limits](known-limits.md): what is unfinished, uncalibrated or unsupported.
- [Comparison](comparison.md): how this differs from other ways to scan on Linux.

## What it does

- **Photos:** each sheet gives `Album_0001.jpg` (the photo, turned upright by its faces), an
  enhanced copy `Album_0001_a.jpg`, and `Album_0001_b.jpg` when the back has handwriting.
- **Editing:** edits are saved as small versioned recipes next to the picture and replayed from the
  retained source; nothing is applied destructively.
- **Documents:** a review-first flow from feeder to PDF, with optional OCR that runs on your machine.
- **Offline by default:** nothing is uploaded. OCR language models are downloaded only when you ask.

The USB part rests on a workaround for a firmware quirk: the FF-680W ignores a command that follows
the end of its previous reply too closely, and a gap of at least 0.5 ms avoids the stall. The
workaround is a small `LD_PRELOAD` shim shipped with the app. It is a workaround, and a patch for
SANE is being prepared; it is not part of SANE today.

## License

GPL-3.0-or-later.
