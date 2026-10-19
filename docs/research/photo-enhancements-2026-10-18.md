# Photo enhancement research for FastFoto Linux

Research date and source access date: 2026-10-18.
Scope: planning and source comparison; no application implementation or private-image evaluation.
Baseline: repository `main` at `39910afd`, as supplied by the coordinating agent.
Recommendations below are engineering proposals, not measured quality or performance claims.

## Recommendation

Keep the existing NumPy/OpenCV/Pillow pipeline as the default implementation base.
Prioritize red-eye review and manual correction, conservative color/tone controls, and reversible recipes.
Add mild denoise, selective dust repair, and sharpening only with full-resolution previews.
Treat face restoration, generated reconstruction, and learned super-resolution as separately installed experiments.
An attractive reconstructed face is not evidence that historical facial detail was recovered.
The perception/distortion distinction is established in restoration research; archival faithfulness needs its own review criteria. [Perception–distortion paper](https://openaccess.thecvf.com/content_cvpr_2018/html/Blau_The_Perception-Distortion_Tradeoff_CVPR_2018_paper.html)

The repository declares `GPL-3.0-or-later` in `pyproject.toml:10`; an initial MIT assumption was incorrect.
GPL candidates therefore need an ordinary component/license and distribution review, not automatic exclusion.
Keep copyright notices, corresponding-source/build information, and model license provenance with adopted components.
Do not infer weight permissions from a Python package's top-level code license.

## What already exists locally

- Required dependencies include NumPy, `opencv-python-headless>=5.0`, and Pillow.
- `enhance/redeye.py` already gates candidates using YuNet faces and the first two eye landmarks.
- It uses red dominance, connected components near the eye, area/roundness/edge/ring-contrast rejection.
- Correction neutralizes and darkens the pupil with a feathered mask and excludes bright highlights.
- These are substantive existing capabilities; do not plan a second independent global red-pixel filter.
- `enhance/fullres.py` supplies the shared full-resolution detection path.
- `enhance/faces.py` bundles and SHA-256 verifies `face_detection_yunet_2023mar.onnx`.
- `enhance/restore.py` already offers guarded percentile-based tone/color recovery and gentle LAB saturation.
- Optional CLAHE operates on lightness and is off by default.
- `restore_cast.py` contains single-tone/monochrome and cast-evidence logic.
- Existing red-eye tests include detection, gates, correction, and real-scan test modules.
- This research inspected narrow source excerpts; it did not execute those tests or inspect private scans.

## Red-eye: separate localization, segmentation, and correction

A face detector answers where a face and approximate eyes are; it does not identify red-eye pixels.
An eyelid/iris landmark model can constrain an eye region, but still needs an artifact mask.
A semantic face mask likewise does not distinguish healthy iris, flash reflection, and glasses glare.
Red-pixel thresholds alone are cheap but cannot reliably distinguish pupils from red clothes or flowers.
The recommended architecture combines face/eye localization with small, conservative pixel masks.

Suggested automatic sequence:

1. Reuse orientation/full-resolution face detection, preserving image-coordinate transforms.
2. Visit every face, with de-duplication for overlapping tiles/scales.
3. Place a modest eye search region relative to interocular distance, not a fixed DPI-only radius.
4. Find a red component close to the expected pupil; reject implausible shape, size, or boundary contact.
5. Score artifact color against a surrounding ring and protect highlights/sclera/skin.
6. Produce a candidate record and mask before committing a pixel edit.
7. Show uncertain candidates for review; safely abstain where pupil evidence is inadequate.
8. Blend the least invasive correction into a new derivative, with per-eye undo.

Do not require both eyes to be red: profile views and a single affected eye are legitimate cases.
Do not promise detection of a pupil only one or two scan pixels wide.
Increasing DPI metadata or upscaling cannot recreate missing pupil evidence.
Try multiple scales/rotations only within bounded work; report minimum reliable eye size from fixtures.

### Mature red-eye implementations

| Candidate | Evidence and algorithm role | Practical decision |
|---|---|---|
| Existing local YuNet + masks | Already integrated; separate localization, pixel gates, highlight protection | Preferred baseline; improve diagnostics/manual review before replacing |
| GIMP / GEGL red-eye operation | Thresholded per-pixel red-channel reduction; a selection is strongly encouraged | Useful deterministic reference and optional comparison baseline |
| digiKam Red Eye | Current manual describes a neural engine locating eyes/red pupils and a red-level control | Strong workflow reference; not verified as a small reusable Python red-eye library |
| darktable | Documented example uses pupil masks and channel mixing; retouch supports heal/clone | Good manual-editing precedent; a whole RAW editor is excessive as a dependency |
| RawTherapee | Local RT-spot selection and chrominance reduction targeted to the pupil | Good manual-selection precedent; no verified drop-in Python detector |
| ImageMagick | Broad color/tone/filter engine; searched official operator/API documentation | No dedicated maintained red-eye detector verified; do not equate `-enhance` with red-eye correction |

GIMP's current manual recommends selecting the iris boundary before applying its filter and offers a threshold control. [GIMP red-eye manual](https://testing.docs.gimp.org/3.0/en/gimp-filter-red-eye-removal.html)
The current GEGL implementation compares weighted channel values, adjusts red only, and preserves the other channels.
It is a point filter, so spatial pupil/face logic must be provided by the caller.
Its operation is specifically **GPL3+**, even though GEGL's core licensing differs. [GEGL operation source](https://raw.githubusercontent.com/GNOME/gegl/master/operations/common-gpl3+/red-eye-removal.c), [operation metadata](https://gegl.org/operations/gegl-red-eye-removal.html)
This makes it a credible mature correction primitive, not a proven whole-image automatic red-eye solution.

digiKam documents neural localization and adjustable red strength, but its documentation does not establish a separately licensed, stable Python API or model manifest for our use. [digiKam enhancement tools](https://docs.digikam.org/en/image_editor/enhancement_tools.html#red-eye)
If its implementation is investigated later, inspect the actual filter, face model, model license, and Qt/KDE dependencies before selecting it.
Do not infer its model weights' terms from the application's GPL status.

darktable's explicit masked channel-mixer example supports user-guided correction as a mature approach. [darktable red-eye example](https://darktable.gitlab.io/doc/en/red_eyes.html)
Its retouch workflow offers drawn shapes, clone/heal, and wavelet-selective edits. [darktable retouch](https://docs.darktable.org/usermanual/4.6/en/module-reference/processing-modules/retouch/)
RawTherapee's current local-adjustment example selects the pupil by RT-spot, previews the selection, and reduces chrominance. [RawPedia local adjustments](https://rawpedia.pixls.us/local_adjustments/)
These are UI/algorithm references, not evidence of reusable maintained Python packages.

### Face/eye localization alternatives

| Option | Code / model evidence | CPU, packaging, and quality implications |
|---|---|---|
| YuNet through OpenCV | Zoo directory explicitly licenses all files MIT; OpenCV library Apache-2.0 | Existing bundled runtime/model; lowest incremental complexity |
| OpenCV Haar eye/face cascades | Included in Python wheel distribution; audit individual data-file notices | No new neural runtime, but compare recall carefully for aged scans/pose |
| MediaPipe Face Landmarker | Official API provides 478 landmarks and configurable face count; page's sample-code license is not a weight grant | Possible eye-contour refinement; extra runtime/model packaging; default maximum is one face |
| dlib 68-point predictor | Official example warns iBUG training dataset excludes commercial use | Avoid default bundling without resolving predictor rights; extra compiled dependency |
| InsightFace models | MIT library code; supplied pretrained models restricted to noncommercial research | Poor default distribution fit without separately licensed weights |

YuNet's current model README says its training targets faces around 10–300 pixels and describes a new dynamic-shape May 2026 export for an OpenCV 5 ONNX Runtime engine.
The repository currently pins the 2023 model; keep its tested hash until an explicit model/runtime migration is validated.
Published WIDER Face results are face-detection results, not red-eye-correction accuracy. [YuNet model documentation](https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/README.md), [model directory license](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE)
The current 2023 model's approximate few-hundred-KB footprint is small; measure actual bundled bytes in packaging rather than promising an exact download size.

MediaPipe returns face landmarks/mesh, and `num_faces` defaults to one; still-image group photographs need explicit multi-face configuration. [MediaPipe task guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)
Its exact model-bundle redistribution terms and Python 3.13/3.14/Flatpak build fit remain unverified here.
dlib's data warning is explicit in its own example. [dlib landmark example](https://www.dlib.net/face_landmark_detection_ex.cpp.html)
InsightFace explicitly separates MIT code from its restricted pretrained models. [InsightFace model terms](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md)

### Manual fallback and red-eye acceptance

Provide click-to-seed plus adjustable ellipse/radius, with zoom and before/after blink comparison.
The same local color mask/correction can operate inside a user-selected region even when face detection fails.
Show a mask overlay and strength control; let users erase mask spill or reject a suggested eye.
For severely faded/non-red pupils, offer explicit manual neutralization rather than silently broadening all-image thresholds.
Preserve catchlights at their actual positions; do not paint synthetic circular highlights.
Keep healthy iris texture/color outside the affected pupil and avoid a uniformly black disk.
Review neutralizing all channels versus changing red only; current implementation chooses the former.
That choice is an experimental comparison, not a mandate to replace working code.

Pets may exhibit green/yellow/white eyeshine rather than red and are outside a human-face detector's validated scope.
Provide a separately labeled manual eyeshine correction mode only after pet fixtures support it.
Glasses reflections, red makeup, red iris contacts, red LEDs, and red objects near faces are negative fixtures.
Tiny faces, occlusion, dark skin, faded prints, rotated faces, and group photos require distinct recall reporting.
Higher sensitivity should move candidates to review before granting permission for automatic edits.

## Other enhancement priorities

| Priority | Feature | Concrete proposal | Main failure mode |
|---|---|---|---|
| P0 | Reversible recipes / review | Preserve original, stage on/off, per-image/per-eye undo, deterministic export | Accidental overwrites or cumulative edits |
| P0 | Color management | Honor embedded ICC profiles; normalize declared working space; retain output profile | Wrong colors from treating every RGB array as sRGB |
| P1 | Color cast / fading | Expose existing guarded restoration with strength and neutral-point picker | Removing intentional warm light, sepia, monochrome toning |
| P1 | Tone / exposure | Black/white points, gentle curve, shadow/highlight control, clipping preview | Crushing shadows or clipping pale faces |
| P1 | Local contrast | Existing low-strength lightness CLAHE, preview and off by default | Halos, noise amplification, exaggerated paper texture |
| P1 | Red-eye correction | Candidate review, click fallback, independent per-eye strength | False edits or erased catchlights |
| P1 | Geometry | Quarter-turn rotate; reversible crop/deskew with visible bounds | Trimming handwritten margins or subject detail |
| P2 | Denoise | Low-strength OpenCV nonlocal means; separate luma/chroma controls if justified | Waxy skin and loss of real film grain |
| P2 | Dust / scratches | Brush mask + small-radius inpaint; conservative proposed dust masks | Removing freckles, text, jewelry, hair, stars |
| P2 | Sharpen | Thresholded low-radius unsharp mask after denoise/resize | Edge halos and amplified grain |
| P3 | Descreen | Explicit optional mode for printed halftones, separate from ordinary photographs | Blurring authentic fine detail |
| P3 | Restoration / upscale | Separate experimental derivative and optional model installation | Invented identity/detail and large resource costs |

Pillow already provides ICC transforms through LittleCMS2; color management need not add a second general-purpose image engine. [Pillow ImageCms](https://pillow.readthedocs.io/en/stable/reference/ImageCms.html)
Automatic white balance assumes something about scene color; gray-world can fail on predominantly red sunsets or green landscapes.
Prefer capped correction, user-picked neutral samples, monochrome/sepia protection, and easy comparison.
OpenCV contrib exposes GrayworldWB, SimpleWB, and LearningBasedWB; the last adds a model path/behavior to validate. [OpenCV xphoto](https://docs.opencv.org/5.0/extra_modules/xphoto.html)
CLAHE limits local contrast amplification but does not make arbitrary settings safe; OpenCV's tutorial demonstrates global equalization damage and local-noise concerns. [CLAHE tutorial](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html)
OpenCV's color nonlocal-means denoiser is available without training new models. [OpenCV denoising](https://docs.opencv.org/4.12.0/d5/d69/tutorial_py_non_local_means.html)
Its useful strength and full-resolution CPU cost on scans remain measurements to obtain.

BM3D is a credible alternative to NLM for evaluation: it groups similar patches and collaboratively filters them in a transform domain.
Select a concrete implementation before making licensing or availability claims; BM3D is not subject to one universal software license.
The authors' current Python `bm3d`/`bm4d` distribution is limited to nonprofit education/scientific research, with profit-oriented use prohibited. [Authors' software page](https://webpages.tuni.fi/foi/GCF-BM3D/index.html)
The IPOL/Lebrun implementation is separately published as GPL-3.0-or-later, making it a concrete source-review candidate for this GPLv3 app; it is an older C++/FFTW-oriented integration, not a maintained drop-in Python wheel. [IPOL implementation](https://www.ipol.im/pub/art/2012/l-bm3d/), [author-attributed source distribution](https://github.com/gfacciol/bm3d)
ORNL also publishes an MIT Python/Rust implementation with a generic-noise mode, but its main domain is neutron-tomography sinogram artifacts; ordinary RGB photo quality/build fit are unvalidated. [BM3DORNL](https://github.com/ornlneutronimaging/bm3dornl)
Keep NLM first because it reuses the shipped runtime; benchmark a cleared BM3D implementation only if fixtures show a useful detail/noise improvement.
Gaussian-noise benchmarks do not establish superiority for film grain, paper texture, compression artifacts, or scanner streaks.

OpenCV offers Telea and Navier–Stokes inpainting using an explicit mask and neighboring pixels. [OpenCV inpainting](https://docs.opencv.org/5.0/main_modules/photo_inpaint.html)
For small dust marks, mask quality is usually more important than adding a more elaborate filler.
Proposed automatic masks can combine local residuals, morphology, scale, and edge protection; call these engineering hypotheses until fixtures validate them.
Do not remove all small bright/dark components: some are legitimate photograph content.
Long scratches crossing eyes, writing, or structured edges need user-guided clone/heal or explicit experimental reconstruction.
RGB-only processing cannot reproduce the information from an infrared dust channel.
No infrared capture channel was established for this app/device; do not promise Digital ICE.

Epson specifies 600-dpi optical resolution, 24-bit external color, and 8-bit external grayscale for the FF-680W. [Official scanner specifications](https://epson.com/For-Home/Scanners/Photo-Scanners/FastFoto-FF-680W-Wireless-High-speed-Photo-Scanning-System/p/B11B237201)
Do not advertise 16-bit/channel hardware capture as an available feature.
Float intermediate processing and possible future 16-bit imported-file handling are separate engineering choices.
Neither produces additional captured tonal information from an 8-bit/channel scan.

## Library choice and distribution

| Library | Verified license facts | Adoption decision |
|---|---|---|
| NumPy + OpenCV + Pillow | Already dependencies; OpenCV 4.5+ Apache-2.0; wheel build scripts MIT with third-party notices | First choice for masks, geometry, tone, denoise, inpaint, unsharp operations |
| scikit-image | Main license BSD-3-Clause with component exceptions in license file | Optional prototype/benchmark dependency for wavelet/NLM/TV/biharmonic methods; add only for measured benefit |
| libvips + pyvips | libvips LGPL-2.1-or-later; pyvips MIT | Evaluate if peak memory/thumbnail/export throughput is the bottleneck, not to replace pupil logic |
| GEGL + babl | Inspect operation-level license; red-eye is GPL3+ | Credible graph/color/high-bit-depth engine, but GLib/babl/GEGL packaging and Python bridge add work |
| ImageMagick | Own permissive license, official text says GPLv3 compatible; attribution required | Useful external comparison/interop; redundant default engine for current app |
| Complete editors | Application components/models require individual review | Workflow references or optional external-editor handoff; avoid embedding an entire editor for one filter |

OpenCV's license and wheel packaging licenses are distinct. [OpenCV license](https://opencv.org/license/), [official Python wheel repository](https://github.com/opencv/opencv-python)
Headless wheels avoid a competing GUI dependency chain, fitting the existing Qt/Kirigami application.
Install only one OpenCV Python distribution because all variants occupy `cv2`.
If xphoto is required, evaluate replacing the headless main wheel with a matching contrib-headless build; do not install both.
Check the actual Flatpak build's capabilities rather than assuming every documented contrib function is enabled.
In particular, do not promise BM3D solely because its API is documented: current OpenCV contrib 4.x source gates it behind `OPENCV_ENABLE_NONFREE` and supports one channel; separately verify the app's 5.x build. This build guard is evidence of configuration requirements, not a determination of present patent validity. [OpenCV BM3D source](https://raw.githubusercontent.com/opencv/opencv_contrib/4.x/modules/xphoto/src/bm3d_image_denoising.cpp)

scikit-image offers NLM, wavelet/TV denoising, Richardson–Lucy, and biharmonic inpainting; this is a usable maintained library family, not a scanner-specific restoration guarantee. [restoration API](https://scikit-image.org/docs/stable/api/skimage.restoration.html), [license file](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt)
Adding it brings additional scientific-library dependencies and duplicate image-processing paths; estimate Flatpak delta before adoption.
libvips is demand-driven and designed for low-memory pipelines; its homepage lists LGPL terms. [libvips](https://www.libvips.org/)
pyvips offers native/shared-library and self-contained binary installation; converting whole images back to NumPy can erase streaming advantages. [pyvips](https://github.com/libvips/pyvips)
ImageMagick supplies color/tone operators such as gray-world LAB white balance, but no verified dedicated red-eye detector emerged from the official API/operator search. [operators](https://imagemagick.org/command-line-options/), [license](https://imagemagick.org/license/)

## Learned restoration: optional research lane

| Candidate | Evidence | Distribution / maintenance decision |
|---|---|---|
| Real-ESRGAN | Official Python inference supports tiling and gray/16-bit inputs; BSD-3-Clause repository | Most plausible optional upscale experiment; exact checkpoint terms/provenance still need manifest review |
| GFPGAN | Official repository offers face restoration; top-level Apache-2.0 with substantial third-party license exceptions | Do not label the complete stack unconditionally Apache; audit clean inference path, selected weights, and dependencies |
| CodeFormer | Official code uses S-Lab noncommercial license; fidelity tradeoff is an explicit feature | Exclude default redistributable core pending suitable permission and distribution review |
| Microsoft old-photo restoration | CVPR research for scratches/noise/blur; MIT code | Official repository archived 2026-10-03; research reference, not maintained production dependency |
| General segmentation/inpainting models | Can help user-selected damage repair, not proven pupil-specific masks | Later experiment only; no need to add SAM-scale runtime for click red-eye correction |

Real-ESRGAN's smaller general model is an evaluation candidate, not evidence of new factual detail. [official repository](https://github.com/xinntao/Real-ESRGAN), [model zoo](https://github.com/xinntao/Real-ESRGAN/blob/master/docs/model_zoo.md)
Code and checkpoint licenses must be recorded separately even where a repository prominently displays a permissive license.
The GFPGAN license lists DFDNet noncommercial-sharealike and NVIDIA-related third-party terms in addition to Apache. [GFPGAN license](https://github.com/TencentARC/GFPGAN/blob/master/LICENSE)
CodeFormer's current license limits the grant to noncommercial purposes and directs commercial users to contributors. [CodeFormer license](https://raw.githubusercontent.com/sczhou/CodeFormer/master/LICENSE)
Microsoft's official repository is explicitly archived; the paper remains credible research but does not establish current package support. [archived repository](https://github.com/microsoft/Bringing-Old-Photos-Back-to-Life), [research paper](https://arxiv.org/abs/2004.09484)

Keep heavy runtimes such as PyTorch/ONNX Runtime optional and local; benchmark CPU first, then optional acceleration.
Do not give a GPU-free speed guarantee or bundle hundreds of MB of checkpoints without measuring the exact artifact.
Use versioned hashes, source URL, byte size, license text, model card, and offline import in a model manifest.
No model should silently download on opening a scan; make downloads explicit, cancellable, and removable.
Flatpak extension/extra-data mechanisms exist, but extra-data is installation-time and does not itself resolve license compatibility. [Flatpak module sources](https://docs.flatpak.org/en/latest/module-sources.html)
Evaluate optional model storage against sandbox permissions and Flathub policy before choosing the delivery mechanism.

## Proposed acceptance fixtures and release gates

Use redistributable or explicit-consent fixtures and synthetic corruptions; private scans remain local and excluded from Git.
Track fixture provenance/license and stratify by scanner DPI, image size, pupil size, pose, age of print, and degradation.
All thresholds below are proposed gates to agree before implementation, not achieved results.

### Available corpus candidates and licensing boundaries

| Corpus | Availability and terms verified | Appropriate role / limitation |
|---|---|---|
| Selected scikit-image sample images | Official data API identifies `camera`, `chelsea`, and `eagle` as CC0 | Small redistribution-friendly geometry/texture/injected-noise fixtures; not a real scanned red-eye benchmark |
| SIDD Small | Official site offers 160 noisy/clean image pairs and states dataset plus associated code are MIT | Secondary denoise benchmark using provided sRGB PNG pairs; smartphone sensor noise differs from scanned prints |
| Open Images | Downloadable; annotations CC BY 4.0; images listed CC BY 2.0 with explicit per-image verification caveat | Candidate hard negatives/group scenes after individual provenance review; not red-eye mask ground truth |
| Consented scanned-print corpus | Must be assembled with explicit permissions and local storage rules | Essential domain test set; annotate eye/pupil masks, protected highlights, defects, and acceptable edits |

Record individual sample-image terms rather than treating the scikit-image software license as blanket image permission. [scikit-image data API](https://scikit-image.org/docs/stable/api/skimage.data)
SIDD provides actual paired data and a clear license, but its official site reports its evaluation server down; prefer reproducible local metrics on the small set. [SIDD official page](https://abdokamel.github.io/sidd/)
Open Images' maintainers explicitly require verifying each image's license status; preserve attribution/source records for any selected images. [Open Images licenses](https://storage.googleapis.com/openimages/web/factsfigures.html#licenses)
No immediately reusable public **scanned-print red-eye** corpus with verified redistribution rights and pupil masks was established in this research.
Do not substitute iris-recognition, gaze-tracking, or medical retinal datasets for flash red-eye examples.
Synthetic red pupils and injected dust permit exact known-mask assertions but cannot establish real-world recall alone.
Microsoft's example-image availability does not imply its MIT code license grants rights to every photograph; do not vendor those images without per-file provenance.

- Red-eye negatives: red flowers/clothing/LEDs, lipstick, glasses glare, normal brown/red-toned irises, no-face scenes.
- Red-eye positives: one/two affected eyes, multiple faces, rotated prints, occlusion, uneven flash, faded red pupils.
- Include varied skin tones, ages, scan noise, print contrast, and very small faces; report subgroup failures.
- Pet eyeshine remains a separate manual-only fixture category until supported.
- Measure eye-level precision/recall, missed-face rate, candidate review burden, and false edits per photograph.
- Prefer a high-precision automatic gate; example target is ≥99% precision on the agreed held-out set, with confidence intervals.
- Require zero observed false modifications on the curated hard-negative suite; document that this is not a universal guarantee.
- Verify unchanged pixels outside approved masks/feather bounds and exact preservation of protected catchlight pixels.
- Assess mask overlap/boundary spill against hand annotations; tolerate abstention rather than iris/sclera spill.
- Review each corrected eye at 100% and fit-to-window for black-disk appearance, seams, and preserved identity.
- Color: neutral/skin patches, intentional warm scenes, sepia/B&W, scanner borders, faded prints, already-good images.
- Record clipping fraction, neutral color error where a reference exists, tone monotonicity, and human preference/faithfulness separately.
- Dust: injected spots/scratches with known clean originals plus true defects; inspect damage to hair, text, jewelry, freckles.
- Denoise/sharpen: quantify noise/detail tradeoff on controlled pairs and inspect halos, grain retention, and skin texture.
- Geometry: measure retained content and deskew error; ensure manual crop can retain borders/writing.
- Learned outputs: compare identity/detail manually; never accept lower blur or higher perceptual score alone as fidelity evidence.
- Benchmark preview and full export separately at 300/600 dpi; record CPU, runtime versions, thread count, p50/p95 time and peak RSS.
- Test many-image batches for bounded memory, cancellation, deterministic recipe replay, crash recovery, and unchanged originals.
- Verify missing optional models work offline, yield clear UI state, and do not disable classical enhancements.
- Record license notices, actual download/installed size, and checkpoint hashes in the release artifact review.

## Open questions for the implementation plan

1. Which existing restoration/red-eye controls are already exposed in the GUI versus CLI only?
2. What consented fixture set represents the user's real red-eye failures and acceptable manual review burden?
3. Does the shipped OpenCV 5 build use the legacy DNN engine or ONNX Runtime, and is the pinned YuNet fully compatible?
4. Is there measured benefit from eye contours beyond the existing YuNet landmarks on tiny scanned faces?
5. Are source profiles available, and what is the chosen working/output color-space contract?
6. Are there actual full-resolution CPU/memory bottlenecks that justify libvips or a scientific-library addition?
7. What are the exact license grants for each optional checkpoint and its training-derived restrictions?
8. Would explicit external-editor handoff deliver advanced clone/heal sooner than rebuilding an editor?

Research coverage: more than ten targeted queries across multiple passes; primary official docs, repositories, and papers only support claims above.
No hardware scans, model downloads, application tests, commits, pushes, or source-code changes were performed for this report.
