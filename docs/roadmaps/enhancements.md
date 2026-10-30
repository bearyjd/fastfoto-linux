# Photo and document enhancement roadmap

Research date: 2026-10-18. Historical baseline: `39910afd9d6094935c8db246ed5f438e17f8d98d`.
Progress updated: 2026-10-25, against shipped commit `88f7cf7`. Several bounded portions of E00–E06 have shipped; the broader benchmark, preservation and enhancement work remains open. The original research and proposed package scopes below remain historical planning context, not a claim that every package or acceptance gate is complete. This artifact does not authorize a feature rollout, model download, new dependency, or use of private scans.

## Goal and decision

Improve everyday scanned photographs and documents with predictable local tools, strong review controls and measurable quality. Build on the existing Python/OpenCV/Pillow pipeline and Kirigami review UI. Start with safer red-eye correction and per-page Auto color/grayscale/B&W, then add basic adjustments, cleanup and quality feedback. Prefer CPU/offline operation for the normal workflow.

The original ordering balanced photos and documents. Implementation has since delivered both photo editing and document Auto/cleanup; remaining work can be prioritized without repeating the research.

## Shipped progress and remaining scope (2026-10-25)

“Shipped” here means merged in the repository. It does not establish real-scan quality, attended scanner behavior or completion of the original package scope. Evidence includes merged changes #41–#58, the [tone design](../design/photo-tone.md), [geometry design](../design/photo-geometry.md), [document design](../design/documents.md#paper-cleanup) and [synthetic photo-fixture provenance](../../tests/photo_edits/PROVENANCE.md).

| Package | Shipped portion | Remaining work / evidence limit |
|---|---|---|
| E00 — quality baseline | Synthetic invariant, recipe, pixel-rendering and compatibility coverage for the shipped features; bounded geometry timing/memory measurements are recorded in the geometry design; a red-eye evaluation harness (`ffscan eval redeye`, synthetic self-tests only). | No completed rights-cleared, held-out real-image benchmark or broad CPU/memory report. Synthetic tests do not measure red-eye accuracy, photographic preference or OCR improvement. |
| E01 — edit/source contract | Hash-checked retained photo source, versioned JSON recipes, undo/reset, bounded previews, saved derivative copies and reopening without redetection (#41 and later extensions). Metadata handling includes EXIF/XMP dimensions, DPI and available ICC. | The source is the existing cropped, upright JPEG, not an untouched acquisition master. Default acquisition-master retention/storage policy and the full native/Flatpak metadata and preservation matrix remain open. |
| E02 — red-eye review | Per-eye accept/reject and strength, manual click/ellipse correction, close-up comparison, undo/reset and saved replay (#41, #44). | Held-out positive/negative evaluation **data** and evidence for changing experimental defaults remain outstanding; the harness exists, but no corpus has been run. UI controls are not an accuracy benchmark. |
| E03 — Auto document engine | Conservative per-page Auto classification, selected mode/reason, richer-mode fallback and retained source-kind semantics (#42, #44). | Real-scan calibration remains needed: the current classifier can retain colour too conservatively. Meaningful-mark preservation and OCR/content quality need corpus evaluation. |
| E04 — Auto review controls | GUI and CLI Auto requests, per-page mode overrides, persisted review decisions, output previews and export/OCR integration (#42, #44). | Broad real-scan and attended workflow validation remains open; these controls do not complete the E00 quality gate. |
| E05 — basic photo editor | Brightness, contrast, saturation and adjustment strength (#43); free crop and quarter turns (#45–#47); straighten slider up to ±15° with version-4 recipes (#53–#55); crop aspect presets (`Free`, `Original`, `1:1`, `4:3`, `3:2`, `16:9`, `5:7`) with a portrait/landscape swap, editor-only and not stored in the recipe. | White balance/tint has editor sliders, four editor-only presets (`Warm`, `Cool`, `Faded print`, `Black and white`; uncalibrated) and version-5 recipes; restoration-strength controls are not implemented. Adjustment strength controls tone only. Straighten has no line tool; its inscribed frame has a documented tiny-image area limitation, and each keyboard angle step is a separate undo entry. |
| E06 — document cleanup | Optional Off/Light/Strong paper whitening, off by default, with document/page choices, persisted recipes, original/output preview toggle and actual-pixel preview crop (#56–#58). Large work grids are skipped above 12 million pixels. A `--cleanup` CLI flag and despeckle (black and white only, opt-in) have shipped for the CLI, the API and the desktop form and review screen; document deskew (opt-in, per page, up to 10 degrees) has shipped for the CLI, the API and the desktop form and review screen. | Otsu/Sauvola/Wolf alternatives and an OCR-only working image remain unimplemented. Cleanup quality evidence is synthetic; it does not prove better OCR. |

The shipped photo render order is accepted red-eye corrections → straighten → crop → quarter turns → white balance → tone, always replayed from the retained source. This implements a bounded editor; it does not replace the original research hypothesis about future denoise, restoration and sharpening stages.

**Follow-up implemented, not released:** document-review rows now label the requested cleanup level explicitly. The built-in output preview reports whether cleanup was applied or skipped, with a reason for dark paper, coloured paper, no paper estimate or the size limit. These changes are outside the shipped baseline `88f7cf7` and have passed independent code and roadmap review; they are not released.

For the next feature, choose a bounded scope: real-scan Auto calibration and benchmark coverage; the acquisition-master retention decision; missing tone/geometry controls; or one of the unimplemented document cleanup tools. Per-page manual crop/rotate in document review also remains open. E07–E11 remain backlog proposals, and E09's broader export presets/PDF/A validation remain open despite the metadata handling already delivered. No delivery dates are assigned.

## Historical evidence and baseline (2026-10-18)

See the [source inventory](../research/enhancement-current-capabilities-2026-10-18.md), [photo research](../research/photo-enhancements-2026-10-18.md), [document research](../research/document-enhancements-2026-10-18.md), and [preservation/workflow research](../research/enhancement-preservation-workflow-2026-10-18.md). The table describes the historical baseline, not current limitations. File references below refer to the baseline checkout. Abbreviated module paths in tables are relative to `src/fastfoto_linux/`; paths beginning with `tests/` or `pyproject.toml` are repository-relative.

| Already available | Actual limitation to address |
|---|---|
| Face-aware red-eye masks with feathering/highlight protection | Experimental, off by default; no per-eye acceptance or manual correction. The existing warning is not an independently measured benchmark. `enhance/redeye.py:22`, `:243`; `gui/qml/FormPanel.qml:223`. |
| Faded-color/cast/contrast/saturation restoration | Mostly a single toggle; internal strength parameters and CLAHE are not exposed. `enhance/restore.py:108`, `:146`; `gui/form.py:253`. |
| Face orientation and scanner-specific automatic crop | No-face abstention exists; no arbitrary-angle manual straighten/crop editor. `enhance/orient.py:49`; `pipeline/crop.py:240`. |
| Document trim, blank review, duplex hole/crease/streak assessments | These assessments improve decisions; they do not repair visible holes, creases or streaks in exported pixels. `documents/blank.py:29`; `documents/holes.py:1`; `documents/streak.py:26`. |
| Global color/gray/B&W, adaptive-mean binarization | No content-based per-page Auto or per-page output override. `documents/modes.py:6`; `loader.py:92`; `bilevel.py:55`; `draft_edit.py:26`. |
| Document review, multilingual OCR and PDF splitting | No general enhancement-mask review; current OCR output is ordinary PDF, not an archival-PDF preset. `gui/qml/ReviewPage.qml:139`; `documents/ocr.py:203`. |
| Original/enhanced photo comparison and retained document raw files | Photo “original” is already cropped/upright JPEG. It is not an untouched acquisition master or persistent edit recipe. `output/writer.py:50`; `pipeline/process.py:343`. |

Current project license is GPL-3.0-or-later (`pyproject.toml:10`). YuNet has its own bundled notice. The exact selected library, model and dataset revisions require separate license checks.

## Original recommended feature priorities (2026-10-18)

| Priority | Addition | Why / chosen starting approach | Difficulty |
|---|---|---|---|
| P0 | Rights-cleared quality corpus and reproducible benchmark | Existing invariant tests cannot establish perceptual red-eye or restoration quality. Separate held-out examples from tuning data. | M |
| P0 | Recoverable edits, original retention and metadata contract | Render from a retained source; make reset/re-export predictable; preserve current document-review behavior. Extend existing structures rather than build a general plugin platform. | M–L |
| P1 | Per-eye red-eye preview, accept/reject, undo and manual eye region | Reuse YuNet plus the existing `EyeFix` detection/application seam. A user-selected ellipse gives a reliable location when face detection abstains. Algorithm quality must still be measured. | M |
| P1 | Per-page Auto color → grayscale → B&W with override | Acquire color and classify after trim; retain color when small annotations, photographs, shading or uncertainty make reduction unsafe. | M–L |
| P1 | Photo exposure, contrast, white balance/tint, saturation and restoration strength | Expose a small, useful set of deterministic adjustments with before/after preview; reuse current restoration where appropriate. | M |
| P1 | Manual crop, straighten and rotate | Correct ambiguous automatic geometry while preserving borders, timestamps and back associations. | M |
| P2 | Document paper/background normalization and stronger B&W options | Benchmark current adaptive mean against Otsu and Sauvola/Wolf; allow faded-paper/receipt presets without erasing pencil or stamps. | M–L |
| P2 | Photo mild denoise and sharpening | Start with bounded OpenCV non-local-means and luminance unsharp masking; keep separate strengths and preview halos/detail loss. | M |
| P2 | Quality warnings | Report possible blur, clipping/cut-off content, skew, recurring scan streaks and dubious conversions. Warnings aid review; they never discard or repair content automatically. | M |
| P2 | Export presets, profile/metadata preservation and optional PDF/A | Offer small searchable PDF, high-quality document PDF and lossless image-master derivatives with explicit size/quality tradeoffs. Validate actual PDF/A output. | M |
| P3 | Descreen, manual dust/spot brush and narrowly masked repair | Useful for printed halftones and isolated damage; opt-in, local, reversible. Broad scratch inference needs a separate benchmark. | M–L |
| P3 | Barcode/Patch-T separation, back-text/date suggestions and captions | Workflow conveniences after quality foundations; keep duplex associations and confirm suggested dates/separators. | M–L |
| Research | Book/camera dewarp, aggressive debleed, deep restoration and super-resolution | Outside the core ADF-photo/document use case or may synthesize/change content. Separate experiments with explicit go/no-go gates. | Unknown |

Difficulty is relative engineering scope, not a delivery-time estimate. No accuracy, speed or disk-size improvement has been measured in this research.

## Original algorithm and dependency decisions (2026-10-18)

1. **Red-eye:** keep face/eye localization plus local redness/shape/contrast masks, feathering and highlight protection as the baseline. Compare established reference implementations before replacing it. Add candidate reasons, a full-resolution ROI overlay and a manual seed/ellipse fallback. Do not apply a whole-image “remove red” rule. Pet eyes/white or green flash reflections are a separate mode requiring their own corpus.
2. **Document Auto:** add `auto` as a requested policy without changing the meaning of `LoadedPage.kind`. Analyze chroma, meaningful colored components, continuous tones and threshold damage; choose a richer representation when uncertain. Persist selected mode, reason and user override. A page that looks neutral in a downscaled thumbnail may still contain a small colored mark.
3. **Binarization:** compare actual OCR/content preservation using current adaptive mean, Otsu and Sauvola/Wolf. OpenCV's latter methods are in `ximgproc`, which is not the current core wheel. Benchmark a small NumPy/OpenCV formulation before adding scikit-image or replacing the core wheel with contrib. Never install multiple packages providing `cv2` into one environment. [OpenCV binarization API](https://docs.opencv.org/5.0/extra_modules/ximgproc.html)
4. **Denoise/sharpen:** retain OpenCV as the first CPU candidate. Measure luminance/chroma denoise separately, use DPI-aware bounds, and sharpen only after geometry/denoise. Higher denoise strength can remove genuine detail. [OpenCV denoising](https://docs.opencv.org/5.0/main_modules/photo_denoise.html)
5. **Color and output:** use existing Pillow/LittleCMS support when available; preserve/transform known profiles and normalize orientation metadata. Do not invent a scanner calibration profile. libvips is a measured-performance alternative, not an immediate rewrite. [Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html)
6. **Heavy models:** keep new PyTorch/CUDA stacks and downloaded restoration weights out of the default app until a benchmark, distributable artifacts, CPU behavior and packaging size justify them. A paper result or a code license alone does not establish suitable model licensing or identity preservation.

The FF-680W is specified as 600 dpi optical with 24-bit external RGB/8-bit external gray. Keep internal arithmetic sufficiently precise, but do not advertise 16-bit hardware capture or interpolated output as additional captured detail. [Epson specifications](https://epson.com/For-Home/Scanners/Photo-Scanners/FastFoto-FF-680W-Wireless-High-speed-Photo-Scanning-System/p/B11B237201)

## Original delivery sequence and implementation seams

The following table preserves the original intended scope, not current completion status; use the progress table above to see what shipped. Each further slice needs its own bounded specification, tests before behavior changes, independent review, applicable full/Qt gates and required CI. Package IDs are planning units, not issue or branch identifiers. Dependencies below were proposed logical prerequisites; the full E00 corpus has not been completed even though bounded E01–E06 work shipped.

| Package | Concrete result and likely areas | Depends on |
|---|---|---|
| E00 — quality baseline | Versioned synthetic fixtures plus rights manifest and a held-out real-image evaluation recipe; red-eye annotations, document ground truth and CPU/memory report. Extend relevant `tests/test_redeye*`, `test_restore*` and `tests/documents/` utilities without reading private folders. | None |
| E01 — edit/source contract | Define photo source retention and an opt-in versioned recipe alongside existing `ProcessSettings`, `output/writer.py` and GUI photo state. Preserve profiles/DPI/orientation intentionally. Bounded before/after preview and atomic export from source; no broad review-system rewrite. | E00 |
| E02 — red-eye review | Extend `find_red_eyes`/`EyeFix`/`apply_fixes`; candidate metadata plus per-eye accept/reject and manual region in photo review; explicit commit/reset. Benchmark before changing the default. | E00, E01 |
| E03 — Auto document engine | Classifier between trim/analysis and encode, new request setting, selected-mode/reason result and conservative fallback; preserve source PNG-kind semantics. Update analysis-version meaning deliberately. | E00 |
| E04 — Auto review controls | Wire GUI/CLI request plus per-page override through `documents/draft_edit.py`, persistence, review thumbnails and export/OCR; migrate saved sessions safely. | E03 |
| E05 — basic photo editor | Small tone/color/strength controls and useful presets, deterministic operation order, crop/straighten/rotate with coordinate transforms and lossless recipe reset. Prefer separate tone and geometry PRs. | E01 |
| E06 — document cleanup | Background normalization and measured threshold alternatives; show original/cleaned preview, parameter limits and richer-mode escape. Optional OCR-only working image distinct from visible-page output. | E03, E04 |
| E07 — denoise/sharpen | Opt-in mild filters with separate chroma/luma and sharpening strength; publish comparison results and CPU cost. | E00, E01, E05 |
| E08 — quality review | Add calibrated warning results/reasons to existing report/review flows. Test natural low-texture photographs and faint pages so warnings are not treated as certain defects. | E00, E02, E04 |
| E09 — export and metadata | Profile/DPI/metadata round trips, explicit lossless/high-quality/small presets, PDF/A validation, correct searchable text/rotation/page order and no repeated-JPEG source. | E01, E04; E06 when cleanup is used |
| E10 — optional practical tools | Independently specified descreen, masked spot repair, separators, captions/back OCR/date suggestions; add only the tools supported by evaluation and user demand. | Relevant earlier packages |
| E11 — research experiments | Compare dewarp/debleed/restoration/super-resolution candidates with archived-project, model-license, identity/text-change, CPU and bundle-size checks. Promote one only after an explicit acceptance decision. | E00 and an approved experiment spec |

**Historical suggested first release (2026-10-18):** E00 + the smallest usable E01 + E02 and E03/E04. Document Auto can proceed alongside photo source/review work after the corpus is defined. Follow with E05/E06, then E07–E09. E10/E11 are a separate backlog, not prerequisites for the first useful release.

Photo processing order is a hypothesis to benchmark: source/color normalization → geometry → local repair/denoise → tone/color → final sharpening → export. In particular, compare red-eye detection on source pixels with detection after restoration; do not silently move the current restore→red-eye order without evidence. Keep all masks in a well-defined coordinate space.

## Testable acceptance gates

These are the original proposed release criteria, not a completed checklist. Shipped slices have invariant and compatibility tests, but the retained acquisition-master, held-out quality, metadata matrix and broad performance gates are still open. Record baseline and held-out results before choosing numeric performance/recall targets.

### All edits

- Retained acquisition/master hashes remain unchanged across preview, edit, undo, cancel, restart and export. Existing explicit user deletion remains a distinct confirmed workflow.
- Recipe replay from a retained source is deterministic for classical algorithms; an older session opens with defaults/migration rather than silently gaining new enhancements.
- Preview/export operation order and masks agree at tested DPI and rotations; downsampled preview is labeled and is not the export source.
- Cancellation leaves no half-published export or stale next-page edits; batch processing remains bounded in memory and serialized through existing worker semantics where needed.
- Supported ICC/EXIF/DPI metadata round trips pass on native and Flatpak builds; invalid/unknown profiles produce a documented fallback rather than a crash or fabricated calibration.
- Runtime measurements record hardware, DPI, image/page dimensions, p50/p95 time, peak RSS, cancellation latency and output bytes. Set budgets after E00, with a recorded go/no-go review before enabling a costly filter by default.

### Red-eye

- Existing locality, immutability and protected-highlight tests pass. Applying zero accepted candidates changes no pixels; pixels outside the accepted correction-mask support remain unchanged.
- Curated negative cases include red clothing, lips, jewelry, signs, flowers, reflections, printed text, spectacles and non-red pupils. Gate automatic rollout on no damaging changes in the frozen negative acceptance set; report sample size and confidence intervals rather than claiming universal zero false positives.
- Positive cases include tiny/faded pupils, multiple faces, rotated images, varied skin tones, glasses and one-eye flash. Report per-eye precision/recall, skipped faces, edit-mask overlap and blinded human preference/identity judgments. Maintain a manual route when automatic detection abstains.
- A user can accept one eye, reject the other, adjust the region, undo and reopen/re-export without accumulating edits. No default-on change based solely on synthetic results or the current unverified “1 in 6” wording.

### Document Auto and cleanup

- A frozen corpus includes faint pencil, colored stamps/highlights, small red annotations, colored charts, grayscale photos, shaded/reversed text, receipts, sepia paper, scanner noise and mixed duplex sheets. Record source/output mode, reason and override.
- No designated meaningful colored marks disappear in acceptance examples. A color-loss/continuous-tone ambiguity selects color or gray, not a forced smaller mode. Manual color/gray/B&W choices remain available.
- Blank recommendations, additional candidates, keep/remove decisions, page order, sheet pairing, splitting and confirmed-original-deletion behavior retain their existing contracts.
- Compare character/word error rate on available transcription truth, foreground/stroke preservation and binarization scores on appropriate ground truth; no regression in designated protected text/annotations. PDF page count, searchable text and manual rotation intent survive OCR.
- Score OCR working-image changes separately from visible output. A smaller file or higher OCR confidence alone does not prove faithful document cleanup.

### Optional advanced work

- Masked dust/scratch/hole/line removal has a pre-apply mask view and leaves all other pixels unchanged. Test real letters, ruled tables, faces and similar-looking genuine marks.
- Lossless originals stay available for any generative restoration. Disclose that the tool may invent details; separate research output labels and explicit opt-in are required.
- PDF/A preset output passes an independent validator; no lossy symbol-substitution compression is introduced. Confirm exact OCRmyPDF version/options instead of reviving obsolete flags.

## Corpus, source and licensing policy

Use synthetic fixtures for invariants, item-level rights-cleared public samples for redistribution, and separately consented local evaluation for real family-photo edge cases. No automatic ingestion of the user's documents or photographs. Record URLs, rights/license, consent scope where applicable, checksums, annotations and train/tune/hold-out split. A public download is not proof of redistribution rights. [LoC candidate dataset and rights fields](https://data.labs.loc.gov/free-to-use/)

Do not adopt a library solely because it implements the named algorithm. Confirm exact-version APIs, Python 3.13/3.14 support, CPU latency, native/Flatpak packaging, dependency size and notices. Preserve the single-OpenCV-package rule. Keep optional model downloads explicit and verified; require a functioning offline baseline.

## Deferred or rejected assumptions

- No new face-identity search, cloud upload, album-management service or scanner firmware feature is required for this enhancement roadmap.
- Software-only RGB scratch repair is not an infrared dust-removal channel. Do not promise recovery of detail that was never captured.
- Red-eye, auto-color and quality warnings are not perfect detectors. Abstention, review and a reversible source are product behavior, not exceptional error paths.
- Preservation guidance informs design; no FADGI, archival or color-calibration conformance claim is made by this roadmap. [FADGI evaluation context](https://www.digitizationguidelines.gov/guidelines/digitize-technical.html)

## Remaining decisions for further implementation

1. Choose the next bounded feature slice; photo and document features have both shipped, and the local cleanup-label follow-up has passed independent review but remains uncommitted and unreleased.
2. Choose the default photo acquisition-master retention policy and explain its storage cost; preserve current explicit document deletion controls.
3. Approve the rights-cleared benchmark corpus and minimum evaluation coverage before changing experimental red-eye defaults.
4. Decide which export presets and metadata fields belong in the first UI; advanced target-based scanner calibration remains separate.
5. Select external libraries/models only after the benchmark spikes and exact packaging/license checks.

## Historical independent review

[Critic review](../research/enhancement-roadmap-review-2026-10-18.md) approved this research/roadmap artifact with two minor corrections, now applied: clarify module-path roots and correct the source inventory's dark-on-dark B&W limitation. That review found no remaining blockers in the original plan. It does not cover this dated progress update or authorize implementation of every package.
