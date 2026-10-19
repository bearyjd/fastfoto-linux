# Enhancement survey: findings and recommendations

Research date: 2026-10-18. App baseline: `39910afd9d6094935c8db246ed5f438e17f8d98d`.
Research and roadmap completed; [independent review](enhancement-roadmap-review-2026-10-18.md) approved the artifact, and its two minor corrections were applied. Implementation remains pending user decision. No new algorithms were benchmarked, no private scans were accessed, and no application code or installed behavior changed.

## Answer

Good classical red-eye approaches exist, and the app already has a sensible architecture: YuNet eye locations, conservative local red-component masks, highlight protection and feathered correction. The next useful addition is candidate review and manual click/ellipse correction, backed by better real-image evaluation. Replacing the detector or adding a large model is an experiment to justify with evidence.

GIMP/GEGL provides a mature correction primitive; GIMP recommends selecting the iris first. That makes it a useful reference for local user-guided correction, not proof of a reliable whole-image detector. digiKam, darktable and RawTherapee also provide useful workflow references. [GIMP manual](https://testing.docs.gimp.org/3.0/en/gimp-filter-red-eye-removal.html), [GEGL implementation](https://raw.githubusercontent.com/GNOME/gegl/master/operations/common-gpl3+/red-eye-removal.c), [digiKam tools](https://docs.digikam.org/en/image_editor/enhancement_tools.html#red-eye)

## Research map

| Report | What it establishes |
|---|---|
| [Current capability inventory](enhancement-current-capabilities-2026-10-18.md) | Implemented algorithms, exposed controls, gaps, exact source/test references and integration seams. |
| [Photo algorithms and libraries](photo-enhancements-2026-10-18.md) | Red-eye alternatives, face/eye localization, color/tone, denoise, scratch repair, sharpening, model/runtime/license considerations and evaluation data. |
| [Document algorithms and libraries](document-enhancements-2026-10-18.md) | Automatic color modes, thresholding, paper/shadow correction, geometry, duplex artifacts, OCR/export, separation and quality flags. |
| [Preservation, workflow and export](enhancement-preservation-workflow-2026-10-18.md) | Acquisition masters, recipes, ICC/metadata, reversible review, performance measurements and actual hardware-output limits. |
| [Implementation roadmap](../roadmaps/enhancements.md) | Priorities, work packages, dependencies, source locations, release gates and open implementation decisions. |

The external research used official documentation, upstream source/license files and original research papers. Search passes covered mature tools, underlying algorithms, package/runtime fit, model terms and suitable test data. Evidence of an API or an attractive paper result is kept separate from evidence of good output on our scans.

## Candidate choices

| Area | First candidate | Comparisons / later choices | Decision |
|---|---|---|---|
| Red-eye | Existing YuNet + local masks, manual eye region, per-eye accept/undo | GEGL correction; investigate digiKam implementation only if needed | Improve review and measure quality first. |
| Face/eye locations | Existing bundled YuNet | Haar baseline; MediaPipe eye contours | Additional landmark density is not a pupil-artifact mask. Avoid new runtime until measured benefit. |
| Fade/cast/tone | Existing guarded restoration plus exposure, neutral picker, tint, contrast and saturation strength | Low-strength luminance CLAHE; other white-balance methods | Expose useful controls and preserve intentional sepia/warm scenes. |
| Photo denoise | OpenCV non-local means | Cleared BM3D implementation; scikit-image methods | Reuse the installed runtime first and measure detail loss/CPU cost. |
| Sharpen | Thresholded luminance unsharp mask | Carefully evaluated deconvolution | Off/low default; inspect halos and grain. |
| Dust/spot repair | User mask + small-radius OpenCV inpainting | Clone/heal handoff or later scratch proposal | Keep scope local and reversible; no broad automatic defect erasure. |
| Document Auto | Existing-stack content classifier with conservative richer-mode fallback | Learned classifier only after simpler rules are evaluated | Preserve colored annotations and grayscale continuous tones; add per-page override. |
| B&W conversion | Current adaptive method as control; Otsu and Sauvola comparisons | Wolf/Niblack; Leptonica references | Select from measured text/annotation preservation, not paper whiteness. |
| Paper/background | Bounded low-frequency normalization and protected regions | Leptonica/unpaper/ScanTailor comparisons | Previewable option; retain original and separate OCR working image where appropriate. |
| Geometry | Manual crop/straighten plus existing orientation/scanner deskew | Camera perspective/book dewarp | Prioritize ordinary flat ADF output; book/camera workflows are later. |
| Export | Existing PDF/OCR/G4 plus explicit presets, profile/metadata round trips | Validated PDF/A, lossless image derivatives, optional lossless JBIG2 | Keep visible content and searchable text alignment verifiable. |
| Workflow/QA | Reversible recipes, before/after zoom, overrides, blur/clipping/streak warnings | Separators, back OCR, date suggestions, captions | Extend current review; do not change liked blank-removal decisions silently. |

OpenCV exposes CPU denoise and masked inpainting, while its extended module provides several document-threshold algorithms. Actual wheel capabilities and full-resolution cost still need testing. [Denoising](https://docs.opencv.org/5.0/main_modules/photo_denoise.html), [inpainting](https://docs.opencv.org/5.0/main_modules/photo_inpaint.html), [local thresholding](https://docs.opencv.org/5.0/extra_modules/ximgproc.html)

## Findings that change implementation choices

- **Much is already implemented.** Red-eye, fade/cast restoration, face rotation, cropping, document blank/trim assessment and multilingual OCR are current features. Hole/crease/streak assessment is not exported-pixel restoration. Source evidence is in the baseline inventory.
- **Automatic document color selection is a real gap.** Current color “kind” is the source PNG storage mode. Add a separate content-based policy and retain color acquisition so an uncertain page can remain rich.
- **The current license is GPL-3.0-or-later.** Evaluate selected implementation, component, dataset and model terms separately. Do not discard every GPL candidate or assume permissive library code covers its weights.
- **BM3D is not one universally licensed package.** The authors' distribution has research restrictions; a separate IPOL implementation is GPL3+; other implementations have different scope. This is a candidate-selection issue, not an algorithm-wide licensing conclusion. [Authors' distribution](https://webpages.tuni.fi/foi/GCF-BM3D/index.html), [IPOL implementation](https://www.ipol.im/pub/art/2012/l-bm3d/)
- **Contrib is not an additive OpenCV wheel.** All Python wheel variants provide `cv2`; replacing the existing headless package needs a deliberate packaging change, not installation of both. [Official wheel repository](https://github.com/opencv/opencv-python)
- **Check OCR flags against the pinned version.** OCRmyPDF 17.13.0 source disables its background-removal path for non-monochrome images despite cookbook references. Current OCRmyPDF also documents removal of lossy JBIG2. Do not make the roadmap depend on those obsolete/unavailable behaviors. [Pinned pipeline](https://raw.githubusercontent.com/ocrmypdf/OCRmyPDF/v17.13.0/src/ocrmypdf/_pipeline.py), [JBIG2 documentation](https://ocrmypdf.readthedocs.io/en/latest/jbig2.html)
- **Deep restoration needs a separate decision.** Model permissions and third-party terms vary; Microsoft's old-photo project is archived. Learned face reconstruction/upscaling can produce plausible invented detail, so it belongs in an optional research derivative workflow. [Archived Microsoft project](https://github.com/microsoft/Bringing-Old-Photos-Back-to-Life), [perception/distortion paper](https://openaccess.thecvf.com/content_cvpr_2018/html/Blau_The_Perception-Distortion_Tradeoff_CVPR_2018_paper.html)
- **Capture limits matter.** The scanner's specified external output is 24-bit color/8-bit gray and optical resolution is 600 dpi. Higher-precision processing is useful but does not create additional captured data. [Epson specifications](https://epson.com/For-Home/Scanners/Photo-Scanners/FastFoto-FF-680W-Wireless-High-speed-Photo-Scanning-System/p/B11B237201)

## Suggested release order

1. Establish the evaluation corpus and source/edit/metadata contract; deliver red-eye review/manual correction and document Auto with overrides.
2. Add basic photo sliders/crop/straighten, conservative document background and threshold options, then mild denoise/sharpen.
3. Add quality warnings, robust export presets/profile handling and selected workflow conveniences.
4. Evaluate descreen, masked spot repair, separators and advanced restoration independently. Keep experimental model-heavy tools optional.

This is a balanced proposal; a photo-first or document-first preference can reorder work packages. Existing document review and photo pipeline pieces should be extended rather than replaced wholesale.

## Limits of the research

No suitable public scanned-print red-eye corpus with verified redistribution rights and pupil masks was established. A consented, representative evaluation set is still needed. SIDD and selected scikit-image samples can help with denoise/geometry tests but cannot establish red-eye accuracy on old scanned prints. DIBCO redistribution terms also remain unresolved in this pass. Dataset permissions are recorded in the detailed reports.

No proposed algorithm has yet been benchmarked in this application. The roadmap's precision/content-preservation/performance gates are proposals to measure, not achieved product claims. No choice here certifies archival or color-calibration conformance.
