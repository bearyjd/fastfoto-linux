# Document enhancement research for FastFoto Linux

Accessed: 2026-10-18. Roadmap research only; no product changes or hardware measurements.
Baseline supplied for this research: `main` at `39910afd`; bounded source checks below, not a complete feature audit.
No private scans, `docs/.raw`, `docs/Document_0001.pdf`, `test-scans`, or home scan folders were accessed.

## Recommendation

Improve the existing document path in this order: measurable preservation guarantees and review controls; content-based automatic color/gray/BW selection; conservative selectable binarization and background correction; OCR and export choices; optional separation and advanced geometry.
Reuse OpenCV, NumPy, Pillow and the existing OCRmyPDF subprocess before adding another processing engine.
Treat cleanup as a reversible derivative of a retained source, with independent display and OCR processing recipes.
Prioritize ADF defects and mixed office documents over camera perspective correction or book dewarping.
Do not promise that a whiter page, smaller PDF, or higher OCR confidence means that more original information survived.

## Existing behavior versus actual gaps

The repository declares `GPL-3.0-or-later` in `pyproject.toml:10`; the earlier MIT assumption is stale.
`pyproject.toml` already requires NumPy and `opencv-python-headless`; OCR extras require OCRmyPDF, with pinned packaging at 17.13.0.
Pillow is already used by the document loader/encoder. These findings support reuse, not another independent document stack.
`documents/loader.py:23,90` maps image storage modes `RGB`, `L`, and `1` to color, gray, and BW.
This is not content classification: a monochrome-looking page stored in RGB remains a color page by this check.
`documents/modes.py:17` chooses the lower richness of source kind and requested mode; it does not infer the cheapest safe mode from content.
`documents/bilevel.py:55` already combines adaptive mean thresholding with a morphological paper estimate and a dark-pixel rule.
It explicitly documents loss of dark text on a sufficiently dark fill, making shaded forms a mandatory evaluation slice.
Selectable Otsu/Sauvola/Wolf/Niblack controls and validated automatic method selection remain distinct proposals.
`documents/encode.py` already writes color/gray JPEG and lossless CCITT G4 BW; calling BW export or document PDF creation entirely new would be incorrect.
`documents/settings.py` already includes OCR mode/languages, blank retention, DPI fallback, timeout and duplex settings.
`documents/assess.py`, `bleed.py`, `holes.py`, and `inkmap.py` already support blank-page assessment with paired-side/context evidence.
Those modules establish detection/assessment foundations, not proof of exposed pixel-restoration controls for bleed-through or punch holes.
Draft/review modules exist; the baseline audit should establish precisely which per-page overrides and comparison views are already exposed before adding UI.
Flatpak manifests already build Tesseract 5.5.3 and include English/OSD traineddata; OCRmyPDF appears in bundled Python dependency manifests.
New external tools still require an explicit sandbox packaging check; presence on the host does not establish availability inside the app.

## Candidate matrix

Priority: P0 = preservation/evaluation prerequisite; P1 = near-term improvement; P2 = opt-in after validation; P3 = later specialist scope.
CPU estimates are relative engineering expectations, not measured performance on this app or scanner.

| Candidate | Current foundation and proposed delta | Expected value / risks | Dependency and priority |
|---|---|---|---|
| Automatic color/gray/BW | Storage-mode classification exists; add content-based recommendation and uncertainty | Smaller output without losing meaningful color or tonal content; a tiny stamp can defeat area-only rules | Existing OpenCV/NumPy, low–medium CPU; P1 |
| Protected color and tonal regions | Add optional masks/overrides around annotations, stamps, photos, highlights and pencil | Prevent irreversible semantic loss; automatic masks need conservative fallback | Existing stack; P0/P1 |
| Otsu | Add as selectable baseline beside current custom adaptive method | Simple clean high-contrast pages; global threshold can fail on uneven background | Core OpenCV; P1 |
| Sauvola | Compare against current method; expose strength/window in physical units | Local statistics candidate for uneven/degraded paper; thin/faint content can disappear | NumPy/core OpenCV prototype or contrib; P1 |
| Wolf / Niblack | Benchmark alternatives; advanced controls rather than presumed defaults | Potential additional recovery cases; parameter sensitivity and noisy backgrounds | Contrib or separately reviewed implementation; P2 |
| Background/shadow correction | Estimate slow paper tone, exclude protected regions, cap correction | Fold shading/yellowed paper; photos, colored stock and highlights can be erased | Existing morphology/filters; P1 opt-in |
| Despeckle | Connected component filtering with DPI-scaled size and protected regions | Removes dust; punctuation, decimal points, diacritics and pencil dots are also small | Existing OpenCV; P2 |
| Bleed-through restoration | Build on paired-side assessment; require registration and reject unreliable pairs | Thin duplex stock; mirrored genuine content and front/back misregistration cause false removal | Existing stack, medium CPU; P2 |
| Deskew and orientation | Verify existing geometry; add bounded correction/confidence/manual rotation where absent | ADF misfeed angle and upside-down pages; sparse text and photos undermine orientation evidence | Existing OpenCV/Tesseract; P1 |
| Edge crop and border cleanup | Distinguish actual paper boundary from content bounding box; preserve safety margin | Removes scanner strips while retaining edge notes; no algorithm recovers clipped originals | Existing OpenCV; P1 |
| Line/streak removal | Separate scanner streak detection from intentional form rules; OCR-only first | Dirty sensor streaks may be removable; tables, signatures and character strokes can be damaged | Core morphology/inpainting; P2 |
| Punch-hole fill | Existing blank-assessment logic is not a general image editor; add previewed region filling | Cosmetic page margins; circular logos/bullets can look like holes | Existing stack; P2 |
| Dewarp / perspective | Optional imported-photo/book workflow, explicitly disabled for ordinary flat ADF pages | Curved books or oblique images; unconstrained transforms can distort accurate pages | ScanTailor/Leptonica study; P3 |
| OCR preprocessing | Preserve visible page; vary OCR-only threshold/cleanup and selected languages | Search accuracy without replacing original image; coordinate alignment must survive all transforms | Existing OCRmyPDF/Tesseract; P1 |
| Searchable PDF / PDF-A / TIFF | PDF/OCR already exist; add explicit archival/compression choices and validation | Interoperable derivatives; format label alone does not prove conformance or image preservation | Existing stack plus verified optional validators; P1/P2 |
| Blank-page review | Existing conservative contextual analysis; expose evidence, restore and bulk review as needed | Less empty output without deleting sparse or faint marks | Existing assessment/drafts; P0 |
| Patch/QR separation | Detect on original pages before cleanup; preserve physical side identity | Batch organization; ordinary document barcodes must not trigger splitting | Core QR/own patch detector; P2 |
| Quality warnings | Add calibrated blur, edge-touch, clipping/saturation and skew indicators | Directs review/rescan; image content and noise confound universal thresholds | Existing filters; P1 |
| Batch recipes | Version presets, preview samples and retain per-page exceptions | Repeatability; automatic bulk application amplifies a bad threshold | Existing settings/drafts; P0/P1 |

OpenCV's `ximgproc.niBlackThreshold` exposes Niblack, Sauvola, Wolf and NICK; scikit-image offers Otsu, Niblack and Sauvola reference APIs. Neither documentation establishes one best method for this application. [OpenCV API](https://docs.opencv.org/5.0/extra_modules/ximgproc.html), [scikit-image filters](https://scikit-image.org/docs/0.25.x/api/skimage.filters.html).
ScanTailor Advanced documents selectable Sauvola/Wolf, mixed foreground/background layers, picture zones and despeckle controls; use it as comparative design evidence, not a drop-in Python dependency. [Upstream README](https://github.com/4lex4/scantailor-advanced).

## Automatic page classification: explicit user priority

Proposed result: recommended encoding mode, rationale, uncertain flag, and user override for each page.
Keep acquisition in color when preservation matters; an image captured in BW cannot recover lost color later.
Separate chromaticity detection from suitability for binarization: a gray photo has no meaningful chroma but is not safe BW text.
Start with a small CPU pipeline using perceptual color differences, local luminance range, connected regions and foreground/background masks.
Correct only a conservative estimated paper cast for analysis; keep original pixels as the reference.
Use both page-level summaries and tile/region evidence so a small colored date stamp survives a mostly black text page.
Exclude scanner margins/noise from voting only when the paper boundary is reliable; otherwise retain them and raise uncertainty.
BW eligibility should reject meaningful continuous-tone regions, faint pencil, dark shaded text boxes and uncertain low-contrast content.
Gray eligibility should require no meaningful chromatic content; yellow highlighter can carry meaning even where underlying text remains black.
Color fallback should win ties and uncertain classifications; provide a deliberate compact-text preset for users who choose more aggressive conversion.
Display proposed mode plus an approximate size preview only after producing representative encodings; never invent a predicted saving.
Require page-level overrides and bulk overrides by selected pages, with an obvious return to the automatic recommendation.
Store classification inputs/algorithm version separately from user choice, so rerunning analysis cannot erase an intentional override.
These are proposed engineering rules, not a claim that a published classifier already meets the preservation requirements.
Evaluate simple rules before learned classification; any later model needs independently checked code, weights and training-data permissions.

## Binarization and cleanup decisions

Retain the current method as the control arm; preserve its observed strengths before replacing it.
Compare global Otsu, existing adaptive mean/closing, Sauvola and Wolf on the same held-out fixtures.
Niblack is useful as a comparison and advanced option; adoption depends on measured foreground preservation and OCR outcomes.
Parameter labels should describe strength and minimum detail in physical units, with an advanced method selector if justified.
Do not apply one unscaled pixel window to 200/300/600 dpi pages.
Avoid a universal automatic winner chosen solely by whiteness, black-pixel coverage or compressed size.
For clean text pages, choose the least transformative method meeting the quality gate.
For uncertain pages, preserve gray/color and offer BW as a previewable export choice.
Prefer OCR-only cleanup before altering the visible document; OCRmyPDF distinguishes `--clean` from `--clean-final`. [Advanced options](https://ocrmypdf.readthedocs.io/en/latest/advanced.html).
OCRmyPDF's cookbook warns that cleanup/background processing can remove desirable content, particularly photos, and recommends inspection. [Cookbook](https://ocrmypdf.readthedocs.io/en/stable/cookbook.html).
Important version caveat: despite cookbook mentions, pinned OCRmyPDF 17.13.0 source raises `NotImplementedError` for background removal on non-monochrome pages. Do not expose `--remove-background` as a working integration without capability verification. [Pinned pipeline](https://raw.githubusercontent.com/ocrmypdf/OCRmyPDF/v17.13.0/src/ocrmypdf/_pipeline.py).
Prototype background normalization within the existing stack rather than depending on that flag.
Use a low-frequency paper estimate, protected foreground/color/photo masks and a bounded adjustment; show before/after at true pixel scale.
Preserve a colored-paper mode and original-background mode; neutralizing the paper is an aesthetic choice that can alter evidence.
Despeckle must account for physical size, proximity to text and regional context; isolated punctuation is not reliably distinguishable from dust by area alone.
Do not apply erosion/dilation globally as a generic text improvement; it changes stroke geometry and can merge or delete glyph parts.
Leptonica offers adaptive background normalization, binarization, segmentation and content-based dewarping; evaluate its algorithms before introducing a separate binding. [Official repository](https://github.com/DanBloomberg/leptonica).

## Geometry, lines and duplex context

Deskew is a small-angle correction; orientation is a 90/180/270-degree decision; perspective and curved-page dewarp are separate operations.
Run only necessary transforms, compose them where practical and resample once to limit avoidable interpolation.
Keep an explicit transform chain for OCR overlays, crop previews and exported page geometry.
Text-line skew evidence should reject sparse diagrams/photos and flag uncertain angles rather than force every page level.
Tesseract notes that skew impairs text segmentation; preprocessing must nevertheless be validated for the target documents. [Quality guide](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).
Crop the physical paper, not the outermost dark content; content-based cropping can delete pale margins and handwritten edge notes.
Edge-touch warnings should say content may be cut off; an image alone cannot establish what was outside the scanner capture.
ADF pages are usually planar enough that deskew/crop provide a more relevant first investment than dewarping; this is a workflow inference, not a measured device finding.
For imported camera pages, perspective correction is useful only when page corners are reliable; a rectangular document is an assumption that must be previewable.
For curved book imports, dewarp may help text-line curvature, but should be a distinct workflow with manual correction and original comparison.
ScanTailor's marginal dewarp explicitly relies on curved top/bottom boundaries against a dark background and has documented failure conditions. [Upstream description](https://raw.githubusercontent.com/4lex4/scantailor-advanced/master/README.md).
OpenCV morphology can extract long horizontal/vertical structures, but the operation does not decide whether a structure is unwanted. [Official tutorial](https://docs.opencv.org/5.0/tutorials/imgproc/morph_lines_detection/morph_lines_detection.html).
Keep form borders, musical staves, underlines and signature strokes intact by default; allow OCR-only line suppression for a chosen form profile.
Treat repeatable ADF streaks as cross-page evidence, with exclusions for recurring printed rules and page templates.
Punch holes should require margin position, shape/tone and preferably paired-side/context agreement; a fill mask must be visible and reversible.
Bleed-through suppression should use original sheet-side IDs and reliable mirrored registration; never pair pages after blank removal has changed numbering.
When a back is missing, skipped or unreliable, fall back to single-page conservative processing and warn that paired correction was unavailable.

## OCR and export

Use Tesseract's internal threshold controls as the first OCR-only experiment: its version 5 line includes adaptive Otsu and Sauvola. [Quality guide](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).
Avoid binarizing twice without a measured benefit; a good visible image can be a better OCR source than an aggressively cleaned BW image.
Evaluate language-specific text, numbers, diacritics, punctuation and mixed-script pages separately.
Expose installed language selection, order and missing-model diagnostics; do not assume OSD identifies every language or that selecting all languages improves results.
Tesseract permits combined languages and documents that order can change output and time; it also creates PDF image/text layers. [Command-line documentation](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
For receipts/forms/code lists, make page segmentation and user-word options profile-specific, with a preview and reset.
Mark OCR confidence as a heuristic, not verification of exact account numbers, names or decimal points.
Searchable PDF should preserve the selected visible raster while adding aligned text, with checks after rotation/cropping.
Add an explicit output contract: ordinary PDF, searchable PDF, or a particular PDF/A flavor; report successful validation rather than merely setting metadata.
Offer TIFF/PNG as image derivatives when useful, preserving DPI, page order and exact BW pixels with lossless compression.
Use lossless storage for source masters and selectable quality for compact derivatives; JPEG is already lossy before OCR or PDF/A steps.
Keep CCITT G4 as a dependable BW baseline; evaluate lossless JBIG2 only when the encoder is included and verified in the sandbox.
Current OCRmyPDF documents lossless JBIG2 and removal of its former lossy mode because character substitution can change the visible document. [Current JBIG2 documentation](https://ocrmypdf.readthedocs.io/en/latest/jbig2.html).
Do not add lossy JBIG2 through another tool or inherit old tutorials recommending its flag; this hazard is independent of OCR mistakes.
Compression acceptance must compare decoded image content and legibility; bytes saved alone are insufficient.
Version-detect external OCR capabilities and preserve a working non-OCR path; missing optional tools should not prevent image-only document output.

## Blank pages, separation and review

Maintain raw physical sheet/side IDs independently of display order, kept-page index and exported PDF page number.
Pair duplex sides before classifying blanks or separator pages, then apply logical document boundaries.
Retain uncertain sparse pages; blank detection must preserve a page containing only pencil, a signature, page number, seal or tiny colored mark.
Show candidate blanks in a recoverable review group with reasons and bulk restore; use existing draft mechanisms where possible.
Separate a confident blank decision from permission to delete a source file: exporting without a page must not erase its recoverable original.
NAPS2 documents tunable brightness/coverage thresholds and acknowledges both false positive and false negative blank decisions. [Profile settings](https://www.naps2.com/doc/profile-settings).
Patch-T is a useful explicit separator model; NAPS2 supports batch splitting and recommends at least 300 dpi for difficult patch recognition. [Batch scanning](https://www.naps2.com/doc/batch-scan).
For this app, prefer a generated application-specific QR separator with a fixed prefix/checksum, or a documented patch protocol, over arbitrary invoice barcodes.
Never execute decoded barcode payloads or use them unchecked as paths; preview document names and split boundaries.
Decoding should operate on the original page before whitening, cropping or despeckling damages a code.
OpenCV provides a QR detector; its linear barcode tutorial lists EAN-8/EAN-13/UPC-A/UPC-E, so broader barcode formats require a separately evaluated decoder. [QR API](https://docs.opencv.org/4.x/de/dc3/classcv_1_1QRCodeDetector.html), [Barcode tutorial](https://docs.opencv.org/4.x/d6/d25/tutorial_barcode_detect_and_decode.html).
Review must distinguish separator omission from blank omission, allow moving boundaries and retain the opposite side of a separator sheet unless explicitly resolved.
Profiles should include document kind, acquisition DPI/mode, cleanup, output quality, OCR languages and blank/separation policy.
Batch preview should include random pages plus worst-case candidates, not just the first clean page.

## Quality warnings and evidence

Proposed local warning signals: text-region edge energy/blur, low contrast, edge-touching foreground, saturated dark/light areas, unusual aspect/size, uncertain skew and repeated streaks.
OpenCV's Laplacian provides a derivative primitive, not an approved universal blur threshold. [Official operator tutorial](https://docs.opencv.org/3.3.0/d5/db5/tutorial_laplace_operator.html).
Calibrate any blur score by DPI and region/content type; a blank page, halftone photo, sharp noise and small print can defeat a single global score.
Use warnings to prioritize review/rescan; never silently discard, sharpen or invent content because a score is low.
Keep source, rendered preview, OCR derivative and final output distinct, with checksums and a versioned recipe.
Allow comparison at the same zoom/location, mask overlays, a toggle for the original and one-step reset per page or selection.
A processed preview should predict the saved rendering; thumbnail-only inspection is inadequate for punctuation, pencil and colored stamps.

## Dependencies, maintenance and distribution

| Candidate | Verified upstream state / license | Decision for this app |
|---|---|---|
| OpenCV core/contrib | Python packaging scripts MIT; OpenCV Apache-2.0; wheels contain further third-party components | Reuse core; review full notices for shipped wheel. [Packaging upstream](https://github.com/opencv/opencv-python) |
| ximgproc | Contrib module documented for local threshold variants | Requires replacing `opencv-python-headless` with `opencv-contrib-python-headless`, not installing both; validate size, CPU ABI and Flatpak build. [Package selection](https://github.com/opencv/opencv-python#installation-and-usage) |
| scikit-image | Latest release endpoint resolved to v0.26.0; general BSD-3-Clause with file-specific notices, including BSD-2-Clause thresholding | Prefer research/reference dependency first; avoid a permanent SciPy/scikit-image dependency solely for one threshold. [Release](https://github.com/scikit-image/scikit-image/releases/tag/v0.26.0), [License manifest](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt) |
| Leptonica | Latest endpoint resolved to 1.87.0, release text dated 2025-12-24; two-clause redistribution notice | Already used beneath Tesseract; direct binding has separate build/maintenance cost. [Release](https://github.com/DanBloomberg/leptonica/releases/tag/1.87.0), [License](https://raw.githubusercontent.com/DanBloomberg/leptonica/master/leptonica-license.txt) |
| Tesseract | Apache-2.0 engine; current repository packaging pins 5.5.3 | Reuse existing local engine and managed language downloads; audit traineddata independently. [Official installation](https://tesseract-ocr.github.io/tessdoc/Installation.html) |
| OCRmyPDF | MPL-2.0; latest docs currently identify 17.13.1, app pins 17.13.0 | Reuse subprocess; pin/capability-check exact version and each external dependency. [License](https://raw.githubusercontent.com/ocrmypdf/OCRmyPDF/main/LICENSE), [Docs](https://ocrmypdf.readthedocs.io/en/latest/jbig2.html) |
| unpaper | README GPL-2.0-only SPDX, some individual files MIT/Apache; releases page currently lists 7.0.0 latest | Optional external OCR-only cleaner; FFmpeg/build and temporary-space cost, no default vendoring. [README](https://raw.githubusercontent.com/unpaper/unpaper/main/README.md), [Releases](https://github.com/unpaper/unpaper/releases) |
| ScanTailor Advanced | Official repo GPL-3.0; release page still fronts 2019.8.16 Early Access/v1.0.16 prereleases | Comparative tool/optional handoff first; Qt/C++ integration and maintenance uncertainty outweigh near-term ADF benefit. [Repository](https://github.com/4lex4/scantailor-advanced), [Releases](https://github.com/4lex4/scantailor-advanced/releases) |

Maintenance signals above are observed endpoints, not a security audit or a promise of support.
The newly indexed Python package named `scantailor-advanced` was not assumed to be the official upstream or adopted; provenance and APIs need a separate review.
An optional executable, a bundled executable, a linked library and copied source are different integration/distribution cases; subprocess use is not a blanket exemption from obligations.
The current GPL app license does not itself settle compatibility of every incorporated dependency; retain exact notices and assess the chosen integration, including GPL-2.0-only/AGPL components.
No legal compatibility conclusion is made here. Code, models/weights, fonts, example scans and training/evaluation datasets require separate recorded permissions.
Run enhancement and OCR locally; no cloud upload is necessary for the recommended pipeline.
New dependencies need reproducible offline Flatpak sources, checksums, architecture support, notices, resource limits, cancellation and missing-tool behavior.
Do not assume host subprocess access; prefer bundled sandbox executables where justified and verify both app manifests.
Stream/bound page work and cache low-resolution analysis, while checking small faint marks at sufficient resolution; avoid keeping an entire 600 dpi batch in memory.
Measure peak RSS, temporary disk, seconds/page and cancellation latency for 200/300/600 dpi mixed batches on a declared CPU.
unpaper's temporary uncompressed page files can be large; OCRmyPDF explicitly notes this cost. [Advanced documentation](https://ocrmypdf.readthedocs.io/en/latest/advanced.html).

## Phases and acceptance gates

P0 — Establish preservation and review foundations before changing automatic output.
- Inventory exposed controls against existing implementation; retain raw pages, stable duplex IDs and versioned recipes.
- Build an original-versus-derivative review path and a corpus with declared rights and per-region preservation labels.
- Gate: reset reproduces original selection; overrides survive reopening; omitted pages restore in correct order; sources remain unchanged after failure/cancellation.

P1 — Deliver practical ADF improvements with current dependencies.
- Add content-based mode recommendations, uncertain fallback, quality warnings and selected-page overrides.
- Compare current binarization with Otsu/Sauvola; add conservative background correction only after mask review.
- Verify/correct deskew/crop behavior, add OCR-only preprocessing and explicit output-quality/archival choices where absent.
- Gate: zero lost protected regions or nonblank deletions in the acceptance corpus; report confusion matrices by document slice and uncertainty coverage.
- Gate: no statistically meaningful aggregate OCR regression on the held-out corpus, with separately reviewed exceptions; targets and method agreed before tuning.
- Gate: PDF opens in declared readers, OCR text aligns after transforms, page count/order/DPI are correct and any claimed PDF/A flavor passes a named validator.

P2 — Add opt-in specialist batch controls when evidence supports them.
- Wolf/Niblack, despeckle, streak/line suppression, paired bleed-through, hole fill, patch/QR separation, TIFF/lossless-JBIG2 options.
- Gate: preview masks explain every destructive operation; fixtures preserve punctuation, signatures, form rules, logos and opposing duplex content.
- Gate: separator tests include mixed simplex/duplex, missing backs, blank backs, damaged/rotated codes and ordinary document barcodes without accidental splits.
- Gate: Flatpak and native runs reproduce declared behavior with optional tools absent/present; memory/disk limits and cancellation are measured.

P3 — Explore camera/book imports and learned methods only for a demonstrated unmet corpus.
- Test perspective/dewarp separately, with manual control and original comparison; require a reliable failure/abstention path.
- Gate: improved curvature/OCR on book fixtures without measurable distortion on planar controls; provenance and weight/data rights resolved before shipping models.

## Evaluation corpus and metrics

Create redistributable synthetic office pages and acquire explicit consent/rights for any real examples; do not repurpose private scans for public fixtures.
Include color stamps/highlights, gray photos, pencil, thermal receipts, shaded forms, diacritics, tiny punctuation, page-edge notes, colored paper and nearly blank backs.
Cover paired duplex bleed-through, holes, scanner streaks, paper sizes and 200/300/600 dpi; split by source document so near-duplicates do not leak into tuning/test sets.
Keep separate manual labels for page mode, protected content/regions, blanks, crop bounds, orientation, split boundaries and exact text transcription.
Measure OCR character/word error, exact critical-field correctness, region preservation, mode confusion/cost-weighted errors, false blank removal and split accuracy.
For binarization ground truth, use foreground precision/recall/F1, pseudo-F measure and DRD where the benchmark evaluator is verified; pixel agreement alone can reward deleting faint strokes.
DIBCO 2019 is a relevant historical-document binarization benchmark, not an ADF-office or color-preservation benchmark. [Competition paper](https://ieeexplore.ieee.org/document/8978205).
The organizer URL `https://vc.ee.duth.gr/dibco2019/` timed out during this research; dataset redistribution terms and exact evaluator were not verified. Do not bundle its images until permissions are resolved.
Record corpus license/source/consent, transformations and ground-truth authorship in a machine-readable manifest.
Measure runtime and peak memory/disk alongside quality and output size, using fixed input/versions/CPU and warm/cold conditions.
Publish actual per-slice results, confidence intervals where sample size permits and all preservation failures; no benchmark results are claimed in this research.
The no-loss acceptance-corpus gate is a release check on known examples, not a guarantee that future unseen scans cannot be misclassified.

## Research coverage and open questions

More than 20 targeted queries across multiple passes covered threshold APIs, OCR preprocessing, background correction, compression hazards, blank/separation workflows, dewarp, maintenance, licensing and evaluation.
Primary upstream documentation/source was preferred; stale cookbook flags were checked against pinned source when behavior conflicted.
Open questions: which controls are already exposed in the current GUI/CLI; exact Flatpak PDF/A toolchain; measured resource costs; public corpus rights; expected non-Latin/mixed-language workload; acceptable review burden.
Resolve those through the baseline audit and an approved implementation plan; this report authorizes no dependency installation, code changes or scans.
