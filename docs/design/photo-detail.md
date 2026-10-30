# Photo denoise and sharpen

API and recipe only; editor controls follow, and there is no CLI flag (no CLI command uses `photo_edits`). Three integer controls, `denoise_luma`,
`denoise_chroma` and `sharpen`, each 0 to 100 with neutral 0. Every value is a plain integer:
booleans, floats, `NaN`, infinities and strings are rejected.

## Order of operations

Rendering replays from the retained source: eyes, denoise, straighten, crop, quarter turns, white
balance, tone, sharpen. Denoise runs in source space right after the eye corrections, because the
noise is still native there: not yet interpolated by the warp, and not yet amplified per channel by
white balance or tone. One pass serves every preview image. The cost is that areas later cropped away
are denoised too. Sharpen runs last, after every resample and after tone, because it reads
neighbours and so does not commute with a crop; the preview therefore crops before it sharpens, and
its "after" image equals the export. This differs from the roadmap hypothesis of denoising after
geometry; it does keep "sharpen only after geometry and denoise". Render has no resize; a follow-up "small" export must sharpen after its own downscale or say it does not.

## Math

```text
Denoise, per band of uint8 RGB (template window 7, search window 15, halo of 10 rows):
  ycc = RGB2YCrCb(rgb);  NLM(x, h) = fastNlMeansDenoising(x, h, 7, 15)
  dY       = NLM(Y, H_LUMA_MAX * denoise_luma / 100) - Y             (0 if denoise_luma is 0)
  dCr, dCb = NLM(Cr and Cb, H_CHROMA_MAX * denoise_chroma / 100) - the same planes   (0 if chroma 0)
  R' = R + dY + 1.403 dCr ; G' = G + dY - 0.714 dCr - 0.344 dCb ; B' = B + dY + 1.773 dCb
  out = floor(clip(x', 0, 255) + 0.5)
Sharpen, per band (halo of ksize // 2 rows):
  sigma = clamp(effective_dpi / 300, 0.5, 3.0) ; ksize = 2 * ceil(3 * sigma) + 1
  Y = 0.2126 R + 0.7152 G + 0.0722 B (float32) ; amount = 1.5 * sharpen / 100
  D = amount * (Y - GaussianBlur(Y, ksize, sigma, BORDER_REFLECT_101))
  out_c = floor(clip(c + D, 0, 255) + 0.5)
```

`H_LUMA_MAX` = 10 and `H_CHROMA_MAX` = 15. Denoise is applied as deltas so there is no lossy colour
round trip; a strength of 0 changes nothing. Sharpen adds the same delta to R, G and B, so it
makes no colour fringes. Sigma follows `effective_dpi` (same physical sigma at any resolution).
A flat image is unchanged by both stages.

## Recipe: schema 6 (`photo-detail-v1`)

Schema 6 adds a top-level `detail` object with exactly the three keys above; it is present if and
only if the schema is 6 or later, and schema 6 keeps `straighten_tenths` and `white_balance`. Only a
non-neutral detail upgrades a draft to schema 6; a draft never downgrades, so a schema 6 draft
returned to neutral stays schema 6. New drafts stay on schema 2. Older app versions reject schema 6
recipes; the saved JPEG stays a normal image. Saved files are never rewritten in place. Presets
never set detail, and adjustment strength does not blend it.

## Bypass

`PhotoDetail()` is a hard bypass: no colour conversion, no filter call and no float pass runs,
and the output is byte-identical to a schema 5 render. Each stage also skips on its own when its
strength is 0 (luma only never runs the chroma filter, and the reverse).

## Banding, memory and cancel

The image is processed in full-width row bands of `max(4 * halo, DETAIL_BAND_PIXELS // width)` rows
with `DETAIL_BAND_PIXELS` = 1048576. Each band reads the original rows of its halo from both
neighbours, so banded output equals whole-image output byte for byte; a halo of 9 rows for denoise
does not. Bands are never split into columns. Work is in place with a rolling carry of the halo
rows, so extra memory is about one band plus two halos and never a second copy of the image.
Cancellation is checked before each band and after each stage; one filter call cannot be
interrupted, so the band size bounds the latency. Nothing in a recipe sizes a loop or an allocation:
window, halo, the sigma clamp and the strength maxima are constants, and total work is bounded by the
source pixel limit. A band is capped at 8388608 pixels with its halo: an image wider than about
139000 pixels is refused ("image too wide for detail adjustments"); no scan up to 8x10 in at 600 dpi
is near it. Denoise of an 89 MP image takes minutes on one thread; cancel latency is one band.
OpenCV's thread count is never changed. A non-contiguous buffer is refused.

## CPU cost

Measured with `tools/diagnostics/bench_photo_detail.py` on 2026-10-29: OpenCV 5.0.0, Intel Core
Ultra 9 185H, 22 default threads, median of 3 runs, strength 50 per stage, one seeded synthetic
print. Seconds per run (denoise and sharpen only, no decode or encode):

| Scan | Threads | Luma | Chroma | Both | Sharpen | All |
|---|---|---|---|---|---|---|
| 4x6 in at 300 dpi (2.16 MP) | 1 | 0.73 | 1.09 | 1.80 | 0.03 | 1.81 |
| 4x6 in at 300 dpi (2.16 MP) | 22 | 0.20 | 0.28 | 0.45 | 0.03 | 0.52 |
| 4x6 in at 600 dpi (8.64 MP) | 1 | 2.94 | 4.42 | 7.16 | 0.11 | 7.28 |
| 4x6 in at 600 dpi (8.64 MP) | 22 | 0.78 | 1.08 | 1.72 | 0.11 | 1.81 |
| 8x10 in at 600 dpi (28.8 MP) | 1 | 10.3 | 15.1 | 24.7 | 0.35 | 25.0 |
| 8x10 in at 600 dpi (28.8 MP) | 22 | 2.38 | 3.16 | 5.15 | 0.34 | 5.48 |

All stages together cost about 0.84 s per megapixel on one thread and 0.19 to 0.24 s per megapixel
on 22 threads. Peak RSS of the whole run, including the generated print, was 541 MiB. Sanity
numbers on the synthetic print only: the flat-patch luma noise std fell from 6.3 to 1.2-1.4 at
denoise 50 for both, and a hard synthetic step stays sub-pixel wide (0.8 to 0.5 px), which says
nothing about the sharpness of a real scan. Rerun the script on the target machine.

## Limits

- The evidence is synthetic: tests check arithmetic, exactness and ordering, and the benchmark uses
  a seeded generated print. Nothing here says how real scans look.
- `H_LUMA_MAX`, `H_CHROMA_MAX`, the sharpen amount and the sigma rule are uncalibrated starting points.
- Strong denoise removes real texture and film grain along with the noise. Sharpen 100 produces
  halos at edges.
- The fitted 1600 px preview barely shows detail; only the eye close-up is shown 1:1.
- Every white balance or tone change re-runs denoise at full resolution, because there is no stage
  cache; large scans take seconds to preview.
- Not in scope: automatic strength, GPU, dust repair, masked detail, a 1:1 loupe, export resizing, CLI flags.
