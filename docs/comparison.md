# Comparison with other ways to scan on Linux

!!! note "Not affiliated with Seiko Epson"
    Not affiliated with Seiko Epson. "Epson" and "FastFoto" name the vendor and its scanner and are
    used only to say which scanner this software is for.

This page states what we could check and says so plainly when we could not. We have not tested the
other programs against the FF-680W ourselves. They are good tools with their own aims, and the right
choice depends on what you scan. If a statement here is out of date or wrong, please open an issue.

How to read the status column: **checked** means we confirmed it from a primary source on the date
shown. **vendor claim** means the vendor says so and we have not confirmed it. **unverified** means
we have not confirmed it and you should check yourself before relying on it.

## What fastfoto-linux is for

It targets one scanner, the Epson FastFoto FF-680W, and one workflow: scan a shoebox of prints
with the backs paired to the fronts, turn pictures upright, keep every edit reversible, and also turn
paper into searchable PDFs. It runs fully offline. Its automatic features are tuned on synthetic data
only (see [Known limits](known-limits.md)), so it makes no claim to produce better pictures or more
accurate OCR than anything else.

## The FF-680W on Linux

| Option | What we know | Status |
|---|---|---|
| fastfoto-linux (this project) | Open source (GPL-3.0-or-later). Includes a workaround for the FF-680W's USB stall; a patch for SANE is being prepared and is not upstream. Tested on one unit. | checked (our own repository) |
| SANE `epsonds` backend | A 2026 blog says SANE lists the FF-680W as "Complete". Whether it works without a workaround on your USB host is a separate question. | unverified: single blog, not checked against the SANE device list |
| Epson Scan 2 for Linux | Epson publishes it for Linux. Whether it supports the FF-680W, and whether it hits the same USB stall, is not confirmed. | unverified |
| VueScan | Paid, closed-source. Its vendor page claims FF-680W support on Linux. | vendor claim |
| Epson FastFoto (Windows and macOS) | The vendor's own application for this scanner; not available for Linux. | checked: Windows and macOS only is our understanding; verify on Epson's site |

Sources, all from a bounded scan on 2026-11-07:

- SANE listing claim (blog): <https://computingforgeeks.com/best-photo-scanner-immich/>
- Epson Scan 2 for Linux downloads: <https://support.epson.net/linux/en/epsonscan2.php>
- Epson Scan 2 for Linux manual: <https://download.ebz.epson.net/man/linux/epsonscan2_e.html>
- VueScan FF-680W page: <https://www.hamrick.com/vuescan/epson_ff_680w.html>

## General scanning programs

These are made for many scanners and are widely used for documents. We have not re-checked their
current feature lists for this page, so we make no feature-by-feature claims about them.

| Program | What we say about it | Status |
|---|---|---|
| NAPS2 | A general document-scanning application. Feature list not compared. | unverified |
| gscan2pdf | A general document-scanning application. Feature list not compared. | unverified |
| Skanpage | The KDE scanning application. Feature list not compared. | unverified |
| Simple Scan | The GNOME scanning application. Feature list not compared. | unverified |
| ScanMole | Not researched for this page. | unverified |

If you mostly scan paper documents and do not need photo backs paired with fronts, one of these may
already do what you need. If you scan photos, check whether the program you are considering handles
the two-sided feeder, back pairing, and keeping edits reversible the way you want.

## Verify before you decide

Nothing on this page is a measurement. Quality of output (colour, sharpness, OCR accuracy) has not
been compared on real scans by us, so we state no ranking.
