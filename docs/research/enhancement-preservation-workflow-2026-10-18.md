# Preservation, workflow and export research

Research date: 2026-10-18. Baseline: `39910afd9d6094935c8db246ed5f438e17f8d98d`.
Status: research findings and proposed requirements; no implementation or performance claims.

## Verified constraints

- The current project declares `GPL-3.0-or-later` in `pyproject.toml:10`; bundled model notices are separately listed at line 11. Evaluate each proposed dependency and model at its exact revision; permissive code does not establish rights to every downloaded weight or dataset.
- Current lock versions include NumPy 2.5.4 (`uv.lock:661`), OpenCV headless 5.0.0.93 (`uv.lock:745`) and Pillow 12.3.0 (`uv.lock:834`). Current online documentation may describe newer releases; verify APIs against the lock before implementation.
- Epson specifies 600 dpi optical resolution, 24-bit external RGB and 8-bit external grayscale for the FF-680W. A 1200 dpi output option must not be described as additional optical detail. A 16-bit scanner-output feature is not established by these specifications. [Epson specifications](https://epson.com/For-Home/Scanners/Photo-Scanners/FastFoto-FF-680W-Wireless-High-speed-Photo-Scanning-System/p/B11B237201)

## Findings and recommendations

### Preserve a master and render derivatives

The Library of Congress prefers preservation of available original resolution, a known color space/profile, and descriptive/technical metadata. It accepts several image formats and favors lossless characteristics. This is guidance for preservation design, not a claim that this app meets an institutional digitization standard. [LoC still-image recommendations](https://loc.gov/preservation/resources/rfs/stillimg.html)

**Recommendation:** Keep acquisition data unchanged, retain existing raw-file protections, and record versioned edit recipes. Render each edited export from the original rather than repeatedly recompressing the last JPEG. Distinguish acquisition/raw bytes, a cropped master, and an enhanced derivative in both UI and documentation. Record a hash and processing provenance; do not claim that an existing output called “original” necessarily retains uncropped acquisition pixels without checking its pipeline.

For family photographs, user-supplied approximate dates, captions and back-side associations are valuable. Keep scan timestamp distinct from a known or estimated photo date. Suggested OCR dates must require confirmation. ExifTool supports metadata reading/writing across formats, but adding that executable should depend on whether existing Pillow support covers the first release. [ExifTool application documentation](https://exiftool.org/exiftool_pod2.html)

### Treat color management as a basic feature

Pillow's `ImageCms` uses LittleCMS2 and supports profile transformations and reusable transforms. This is a plausible starting point using an existing dependency; runtime availability of LittleCMS in native and Flatpak builds needs verification. [Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html)

Pillow's format documentation describes explicit ICC and EXIF save options. JPEG profiles are not automatically preserved when the profile argument is omitted. Therefore, metadata/profile round-trip tests belong beside visual enhancement tests. [Pillow format documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)

**Recommendation:** Audit decoding, OpenCV/Pillow conversion, thumbnails, Qt display, image export and PDF export as one path. Preserve known source profiles, transform pixels when converting, and do not assign an sRGB tag to arbitrary unknown scanner colors as though calibration had occurred. Provide a documented assumption for untagged images. Normalize EXIF orientation after applying geometric transforms so viewers do not rotate twice. Keep capture DPI distinct from arbitrary resizing.

libvips supports ICC operations through LittleCMS and offers another possible image backend. Its existence alone does not justify replacing the current array pipeline. Benchmark it only if current long-page or batch memory/throughput remains a measured problem. [libvips color operations](https://www.libvips.org/API/current/libvips-colour.html)

### Give users useful, repeatable controls

NAPS2 exposes brightness, contrast, output color depth, document sizing, blank detection and Patch-T separation. Its documentation also explains the blank detector's threshold tradeoff. These are useful workflow precedents rather than proof that matching numeric settings would produce equivalent output here. [NAPS2 profile settings](https://www.naps2.com/doc/profile-settings)

**Recommendation:** Offer separate photo and document presets with adjustable strength, explicit per-item overrides, synchronized before/after zoom, reset, undo/redo and a batch change summary. Keep confidence-based suggested changes distinct from confirmed edits. Preserve the existing recommended-blank-removal and additional-candidate review behavior the user liked.

Preview a bounded working image for responsiveness, then render from the full-resolution original using the same recipe. Masks and coordinates must map correctly across DPI, crop and rotation. One full-resolution render should be active per bounded worker policy; cancellation must not leave a half-written export or change the next item's settings.

### Evaluate faithfully before adding heavier restoration

FADGI's technical guidelines explicitly pair capture recommendations with evaluation targets, software, testing and monitoring. A single enhancement checkbox or attractive result does not demonstrate conformance. [FADGI technical guidelines](https://www.digitizationguidelines.gov/guidelines/digitize-technical.html)

**Recommendation:** Build a small, versioned, rights-cleared evaluation corpus first. Include ordinary and difficult cases, store ground truth or expert annotations where applicable, and separate development from held-out acceptance samples. Never silently use the user's scan folders as a test corpus. Synthetic examples test invariants but cannot establish real-world restoration quality alone. The [LoC Free to Use and Reuse dataset](https://data.labs.loc.gov/free-to-use/) provides candidate photographs and item-level rights metadata; retain each selected item's provenance and rights statement. It is not a specialized red-eye ground-truth set, and its rights categories must not be treated as identical.

## Proposed acceptance checklist

1. Original acquisition bytes and their hash remain unchanged through preview, edits, cancel, re-export and restart.
2. Recipe replay from the same original produces matching deterministic output for classical operations; record algorithm/version/parameters and export settings.
3. ICC/EXIF/DPI survive supported round trips; profile conversion uses a test profile with known expected results. Unsupported metadata is explicitly documented.
4. Before/after zoom uses matching coordinates; a click-selected eye mask lands on the same full-resolution eye at each tested DPI and rotation.
5. Preview and export use the same transformation order and parameters, with differences limited to documented preview resampling.
6. Repeated exports do not read their own previous JPEG as the next processing source. Undo restores the previous recipe without rewriting the master.
7. Batch runs report elapsed time, peak memory, p50/p95 per image, cancellation latency and output size on named CPU/DPI/page-size fixtures; set budgets from the measured baseline rather than inventing speed claims.
8. Native and Flatpak distributions retain offline basic enhancements, consistent model notices and required codec support. No unrequested cloud calls or model downloads.

## Remaining uncertainty

- Availability/licensing of a redistributable scanner-specific ICC profile and a licensed physical calibration target have not been established.
- Current end-to-end profile retention, Qt color behavior and metadata round trips require a targeted implementation audit/experiment; this research has not certified them.
- No new scanner acquisition, real-photo benchmark or document accuracy experiment was performed.
- Exact metadata scope, persistent session format and optional external-tool packaging belong in individual implementation specifications.
