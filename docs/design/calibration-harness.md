# Calibration harness: `ffscan eval deskew | autocolour | wb | detail`

Four offline evaluators that measure document deskew, automatic colour mode, white balance and
photo detail against a rights-cleared corpus (the manifest of [corpus.md](corpus.md)) and judge
the numbers against the roadmap section 4.9 acceptance table. They are measuring instruments:
**synthetic self-tests only. No quality has been measured**, the harness ships no data, and the
constants of the features it evaluates were tuned on synthetic data only. Nothing here claims
that any feature meets its threshold.

## Contract

```
ffscan eval <feature> [--corpus DIR] [--out DIR] [--split tuning|heldout]
                      [--expect-manifest-sha256 HEX] [--gate]
ffscan eval detail    ... [--denoise-luma N] [--denoise-chroma N] [--sharpen N]   # 0-100, default 50
```

- The corpus is `--corpus DIR` or `$FASTFOTO_CORPUS_DIR` (never a default); `DIR/MANIFEST.json` is
  loaded by the corpus loader, which re-hashes every file through a pinned directory descriptor.
- Default split is `tuning`. `--split heldout` is refused (exit 2) without
  `--expect-manifest-sha256`. A pin that does not match the manifest's sha256 is refused (exit 2)
  for either split. `--gate` needs `--split heldout` and the pin.
- A held-out run fingerprints (file sha256, decoded-pixel sha256, group) every item of the
  feature's kind in both splits, annotated or not, and refuses (exit 2) on any overlap. Pixels
  are compared as RGB (grey stacked, 1-bit as 0/255), so a grey page and its RGB copy collide.
  An item of either split that cannot be read or decoded refuses the run, because leakage could
  not be ruled out.
- Only items of the feature's kind (documents or photos) that carry the feature's annotation are
  measured; the others of that kind are counted as `skipped`.
- An item that cannot be decoded, whose boxes lie outside its image, or whose algorithm fails is
  counted as `errored` and does not stop the run. A malformed annotation (unknown key, wrong
  type, out of bounds) refuses the run, naming the item id.
- `report.json` is written into a new `run-...` directory under `--out` (default
  `$XDG_CACHE_HOME|~/.cache/fastfoto-linux/calibration-eval/<feature>/<manifest sha256[:12]>/`),
  refused inside the corpus directory or a checkout. It is metrics only (`corpus_report`
  allowlist), floats are rounded to 4 places, it holds no timing, and a rerun on the same corpus
  is byte-identical. Errors name item ids, never paths or hashes.
- Exit codes: 0 ok (or automated criteria passed), 1 a read or write failure (a fixed message,
  no path), 2 refusal or usage, 5 gate failed. With `--gate`, every automated criterion must be
  `pass`; `fail`, `insufficient_data` (a number is missing or the group is under `MIN_N`), any
  errored item and any skipped item (no annotation) fail it. Only automated criteria are
  judged: the run says so, never prints a bare "GATE PASS", and lists the pending criteria that
  people judge (`not_applicable`, e.g. the wb A/B preference).
- A file whose sha256 no longer matches refuses the run (exit 2). Other per-item failures are
  counted as `errored` and the class name of the exception (never its message) goes to stderr.
  A `MemoryError` is not swallowed. Items over 25 million pixels (`calib_pages.MAX_PIXELS`) are
  errored, or, in a held-out run, refuse it because they cannot be fingerprinted.

## Annotations (`annotations.<feature>` of an item)

Unknown keys are refused, a bool is not an integer, lists are capped, boxes are `[x, y, width,
height]` in pixels inside the image.

| feature | kind | fields |
|---|---|---|
| `deskew` | document | `correction_tenths`: 1-4 integers in -450..450, the clockwise correction that levels the page in tenths of a degree, one per annotator (same sign as the estimate); optional `dpi` 50-2400, used only if the PNG states none |
| `autocolour` | document | `label`: `colour`, `grey` or `bw`, the least rich mode that keeps every meaningful mark; optional `dpi` |
| `wb` | photo | `neutral_boxes`: 1-16 boxes on a neutral patch; `cast`: true if the photo has a colour cast |
| `detail` | photo | `dpi` 50-2400; `flat_boxes`: 1-16 boxes of flat tone; `edge_boxes`: 1-16 of `{box, axis}` with `axis` `h` (edge crossed along x) or `v` (along y) |

Document pages are PNG only (RGB, 8-bit grey or 1-bit), at least 10 mm each way, with the
resolution read from the PNG. Photos are decoded as RGB.

## Metrics (fixed report keys under `metrics`)

Every report has `split`, `counts` (`n` annotated items in the split, `skipped`, `errored`), one
object named after the feature, and `criteria` (the verdicts below).

- `deskew`: `n`, `applied` (pages the estimator answered; an abstain, including a tilt under 0.3
  degrees, is not applied), `abstain` (proportion), `mae_deg` and `p90_abs_err_deg` of applied
  pages, `wrong_direction` (proportion of applied pages turned the opposite way to the mean
  annotation).
- `autocolour`: `n`, `colour_loss` (proportion; the chosen mode is poorer than the label, with
  the 95% zero-event upper bound `zero_upper_bound` when none), `over_retention` (richer than
  the label). Richness order is bw, grey, colour.
- `wb`: `settings` -> `none`, `restore`, `warm`, `cool`, `faded`, `mono` -> `all_items` and
  `cast_items` -> `n`, `median_de00`, `p90_de00`: CIEDE2000 between the mean colour of the neutral
  boxes and the neutral of the same lightness. `restore` is colour restoration (there is no
  automatic white balance); the others are the white balance part of the editor presets (`mono`
  has none). `improvement_vs_none_restore` is `(none - restore) / none` of the cast median.
- `detail`: `strengths` evaluated; `sigma_reduction_pct_median` (luma standard deviation of the
  flat boxes), `edge_width_growth_pct_median` (10-90 edge width), `halo_pct_p90` (overshoot of the sharpened edge past its plateaus, percent of the
  edge height; worst edge of an item), all read from one output against the original. The
  image is rendered as the product does: denoise, then sharpen, on the same buffer. A flat box
  whose original standard deviation is below `MIN_SIGMA` (0.5 grey levels) has no measurable
  noise and is not counted; an item with no such box is errored.
- Proportions carry `k`, `n`, `p`, a Wilson interval (`lo`, `hi`) and `zero_upper_bound`.

## Thresholds (roadmap section 4.9, as data in `evaluation/calib_thresholds.py`)

The wb human A/B preference (at least 60%, n >= 20) is not automated. The `small` preset,
red-eye and cleanup rows are inert, non-automated proposals (label `proposal`): the numbers are
not measured, and none of the four commands here judges them (red-eye has its own
`ffscan eval redeye` gate).

`MIN_N = 5` (a proposal, in `calib_thresholds.py`): a group with fewer items reports `status`
`insufficient_data`, keeps its counts (`k`, `n`) and has null rates, intervals, medians, p90s,
means and improvements (so a tiny group cannot reveal one item). Every automated criterion
whose group is smaller is `insufficient_data` and fails the gate. The wb `cast_items` group is
judged on its own count. Zero-event criteria (`wrong_direction`, `colour_loss`) are judged on
the count `k == 0`, not on the rounded rate. Every criterion is judged on the unrounded
metrics, with a relative slack of 1e-9 at inclusive limits for float error; only the copy
written to `report.json` is rounded.

| feature | constants | design note | harness | criterion | metric | op | value | automated | label |
|---|---|---|---|---|---|---|---|---|---|
| deskew | documents/deskew_tables.py | documents.md | eval deskew | mae_deg | mae_deg | <= | 0.3 | yes | - |
| deskew | documents/deskew_tables.py | documents.md | eval deskew | wrong_direction | wrong_direction.k | <= | 0 | yes | - |
| deskew | documents/deskew_tables.py | documents.md | eval deskew | abstain_rate | abstain.p | <= | 0.25 | yes | - |
| autocolour | documents/auto_colour.py | documents.md | eval autocolour | colour_loss_zero | colour_loss.k | <= | 0 | yes | - |
| autocolour | documents/auto_colour.py | documents.md | eval autocolour | over_retention | over_retention.p | <= | 0.3 | yes | - |
| wb | enhance/restore.py | photo-white-balance.md | eval wb | restore_de00_improvement | improvement_vs_none_restore | >= | 0.3 | yes | - |
| wb | enhance/restore.py | photo-white-balance.md | eval wb | ab_preference | ab_preference | >= | 0.6 | no | - |
| detail | photo_edits/detail.py | photo-detail.md | eval detail | sigma_reduction | sigma_reduction_pct_median | >= | 25 | yes | - |
| detail | photo_edits/detail.py | photo-detail.md | eval detail | edge_width_growth | edge_width_growth_pct_median | <= | 10 | yes | - |
| detail | photo_edits/detail.py | photo-detail.md | eval detail | halo | halo_pct_p90 | <= | 5 | yes | - |
| small | export presets | export-presets.md | none | median_mb_per_6x4 | median_mb_per_6x4 | <= | 1.5 | no | proposal |
| small | export presets | export-presets.md | none | ssim | ssim | >= | 0.95 | no | proposal |
| redeye | enhance/redeye.py | redeye-evaluation.md | eval redeye | g1_g5 | g1_g5 | == | pass | no | proposal |
| redeye | enhance/redeye.py | redeye-evaluation.md | eval redeye | recall_lb | recall_lb | >= | 0.6 | no | proposal |
| cleanup | documents/cleanup.py | documents.md | none | cer_delta_pp | cer_delta_pp | <= | 0.5 | no | proposal |
| cleanup | documents/cleanup.py | documents.md | none | pencil_stamp_losses | pencil_stamp_losses | <= | 0 | no | proposal |

Readings: deskew mean absolute error at most 0.3 degrees on applied pages, no wrong-direction
page, at most 25% abstains; autocolour no colour loss (the report gives the 95% upper bound) and
at most 30% over-retention; wb the neutral CIEDE2000 median on cast photos improves by at least
30% against `none`, judged on `restore`; detail noise reduced by at least 25% at the evaluated
strength with edge-width growth at most 10% and halo at most 5%.

## How a human runs it on a real corpus

1. Build and approve a corpus as described in [corpus.md](corpus.md): outside the checkout, rights
   recorded, items annotated for the feature, splits derived from the seed.
2. `export FASTFOTO_CORPUS_DIR=/absolute/path/to/corpus` (or pass `--corpus`).
3. Tune on the tuning split only, as often as needed:
   `uv run ffscan eval deskew --split tuning --out ~/calibration-results`. Read `report.json`
   in the new `run-...` directory; change constants in the feature code, never the manifest.
4. Freeze: commit the parameters, then record the manifest hash:
   `sha256sum "$FASTFOTO_CORPUS_DIR/MANIFEST.json"`. Do not edit the corpus after this.
5. Run once on the held-out split with the pin and the gate:
   `uv run ffscan eval deskew --split heldout --expect-manifest-sha256 <hex> --gate`.
   Exit 0 means every automated criterion passed with no errored item; exit 5 lists the failing
   criteria; exit 2 is a refusal (pin mismatch, leak, bad annotation). Repeat for `autocolour`,
   `wb` and `detail`.
6. A held-out result that fails is not a reason to re-tune on it: collect a fresh held-out set
   before the next gate run. The wb human A/B preference is run separately by people.

## Limits

Self-tests use tiny generated pages and photos, so they check the counting, the guards and the
determinism, not feature quality. Mark-box colour loss, bootstrap intervals, summary and timing
files, and blinded A/B tooling are not built. The held-out leak check compares file hashes,
decoded pixels and groups, so near-duplicates (a crop, a re-scan) are not caught.
