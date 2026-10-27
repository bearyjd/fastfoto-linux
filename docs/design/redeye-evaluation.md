# Red-eye evaluation harness

`ffscan eval redeye MANIFEST.json` measures the automatic red-eye path against a labelled
manifest. It is a measuring instrument: **the harness ships with no data; no accuracy has been measured.** Red-eye stays experimental and no default changes. Its self-tests use
synthetic images painted in code with a stub face detector, so they check that the counting is
right, not that red-eye works.

## Privacy

The manifest is a required argument. Nothing is read except the manifest and the images it
names, under the manifest's own directory (symlinks are followed, then contained; FIFOs and
other non-regular files are refused). There are no default corpus paths and no automatic
ingestion of anyone's photos. Results go to `--out DIR` (default
`$XDG_CACHE_HOME/fastfoto-linux/redeye-eval/<manifest sha256[:12]>/`), which is refused inside
the manifest directory or inside a fastfoto-linux checkout. Reports hold opaque ids, sha256
prefixes, numbers and categories: never paths, pixels or the rights `source` text. Use opaque
ids, not names of people.

## Manifest (JSON, version 1)

Top level: `format` (`fastfoto-redeye-eval`), `version` (1), `split_salt` (16-64 hex) and
`images`. Unknown keys, duplicate keys and NaN are errors; the file is at most 8 MB.
Each image has `id`, relative POSIX `path`, `sha256` (verified), `dpi` (50-2400), `upright: true`
(the detector finds upright faces only), optional `group` (a print, its rescans and crops),
`split`, `rights` (`licence`, `source`, `consent_scope`, `redistributable`), `faces` and
`negatives`. A face lists two eyes, right then left, each `{x, y, r, red}` in image pixels
with pixel centres at +0.5. `red: false` marks a non-red pupil, closed eye or glare. An image
with no red eye is a negative image. `negatives` are `{category, box}` regions where any
changed pixel is damage; categories are red_clothing, lips, jewelry, signs, flowers,
printed_text, spectacles, non_red_pupils, reflections and other.

## Split guard

An image is held out when `int(sha256(salt:group-or-sha256)[:8], 16) % 100 < 20`. A declared
split that disagrees is refused, so it cannot be picked after seeing results. A held-out report
is refused when a held-out item shares a file hash, a decoded-pixel hash, a group or an id with
a tuning item, in the manifest or in any `--tuning-manifest`. Rescans or crops with different
pixels are caught only if a human gave them the same `group`. The guard protects against
accidents, not an adversary: the salt is controlled by the manifest author, and a re-encoded or
cropped copy filed under another group is not detected. A tuning image that cannot be read
refuses the held-out run (exit 2), because its leakage evidence would otherwise vanish.

## Matching and metrics

Predictions are `detect_fixes` (the auto path). A prediction's position is its fix-mask
centroid, not the landmark. It matches a ground-truth eye within 0.15 of that face's
inter-ocular distance, greedily and one-to-one, nearest first. A match to a red eye is a true
positive; to a `red: false` eye, a false positive of its own kind; an unmatched prediction is a
false positive; an unmatched red eye is a miss. Reported per eye: precision, recall, mask IoU
(median, p10, p90), faces found, skipped for score or size, missed, and eyes abstained in found
faces (not errors). Proportions carry 95% Wilson intervals. A count of 0 of n also prints the
exact one-sided 95% upper bound, `1 - 0.05^(1/n)`; n = 0 is "no samples", never 0 or 1. The
intervals treat eyes, faces and photos as independent, so they are optimistic for correlated
data (rescans, one family, one scanner); image-level recall (at least one red eye corrected) is
reported beside the per-eye figure.

Changed pixels are counted outside the fix regions (must be 0), inside negative regions or
anywhere in a negative image (damage), and outside the dilated ground-truth discs
(collateral, informational). Gate G1 covers damage in labelled negative regions and negative
images only; non-red-eye matches (`fp_non_red`) are reported but ungated. Errored items
(unreadable, corrupt, too large, bad mode or format, multi-frame, bad geometry, resource) are
listed, keep their labelled red eyes (as misses) and faces in the denominators, and fail G4.
Missing files, path escapes and hash mismatches share the one reason `unreadable`.

## Limits

Only PNG, JPEG and single-frame TIFF are decoded. Eye radius is at most 10000 and coordinates
within 1e7; eyes and boxes must lie inside the decoded image. One run has an image budget
(20,000 images) and a pixel budget (2 billion decoded pixels, tuning images included); going
over is a usage error.

## Gate

`--gate` needs `--split heldout` and `--expect-manifest-sha256`. It passes only if there is no
damage (G1), no change outside the fix regions (G2), the held-out split (G3), no errored item
(G4) and at least one negative image and one red eye (G5, else "insufficient data").
`--min-precision` and `--min-recall` compare against the Wilson lower bound and are off by
default. Exit code 5 means a gate failed. A pass reports "No damaging change observed in N
frozen negatives (95% upper bound X%)" and makes no claim about false-positive freedom.

## Outputs

`report.json` and `summary.md` are byte-deterministic. `perf.json` (wall time, a traced Python
allocation peak that excludes OpenCV-internal memory, and the process high-water RSS) is not;
use `--no-perf` to skip it. Writing the corpus, approving it (roadmap decision 3) and
measuring a baseline are separate, later steps.
