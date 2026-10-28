# Red-eye evaluation harness

`ffscan eval redeye MANIFEST.json` measures the automatic red-eye path against a labelled
manifest. It is a measuring instrument: **the harness ships with no data;
no accuracy has been measured.** Red-eye stays experimental and no default changes. Its
self-tests use synthetic images painted in code with a stub face detector, so they check that
the counting is right, not that red-eye works.

## Privacy

The manifest is a required argument. Nothing is read except the manifest and the images it
names, under the manifest's own directory. Each path is opened component by component
without following symlinks, so a symlinked directory or file is refused and a late swap cannot
redirect the read; FIFOs and other non-regular files are refused too. There are no default
corpus paths and no automatic ingestion of anyone's photos. Results go to `--out DIR` (default
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
Missing files, path escapes and hash mismatches share the one reason `unreadable`. Errored
negative images are shown as "unevaluated" beside the damage figure and per category; the exact
upper bound uses evaluated images only. G5 counts the labelled red eyes of errored items (G4
fails anyway). A damaged negative image attributes damage to the categories whose box holds a
changed pixel; a change outside every box is attributed to all of the image's categories.

## Limits

Only PNG, JPEG and single-frame TIFF are decoded. Eye radius is at most 10000 and coordinates
within 1e7; eyes and boxes must lie inside the decoded image. One run has an image budget
(20,000 images), a pixel budget (2 billion decoded pixels, tuning images included, charged
from each header before its pixels are decoded; undecodable headers are limited by the image
budget only) and a byte budget (4 GiB of file bytes, tuning images included, charged from each
file's size before it is read); going over any is a usage error. The budgets are charged
conservatively: images that later error still consume them, so a few hostile files can exhaust
one and abort the run with exit 2.
The manifest's own directory is opened while the manifest is read (its resolved path is walked
from `/` without following a symlink) and that descriptor is the corpus root for the whole run,
so no path is resolved again and replacing a path mid-run cannot redirect a read. A read that
fails at the device (EIO, ESTALE) is the per-item error `unreadable` for a held-out item and a
usage error for a tuning item. A multi-frame TIFF is detected by looking at the second IFD only,
never by walking the chain; there is no per-image wall-clock limit, so a hostile file can still
cost decode time within the byte and pixel caps.

A memory failure on a held-out item is the per-item error `resource`; on a tuning item it
refuses the run. A failing profiling pass leaves the scores alone and is recorded in `perf.json`
only. Every run writes a new directory `run-<UTC time>-<8 hex>` under the results directory
(`mkdirat`, so it is never an existing one; a taken name is retried up to three times with a new
token) and creates `summary.md` and `perf.json` in it exclusively, mode 0600. The report is
written whole to `.report.tmp`, synced, and published by an atomic rename (no hard-link support
is needed; the run directory is ours alone and `report.json` is checked to be absent first), so a
`report.json` that exists is complete (barring storage that lies) and a run directory without
it is incomplete (a crash; a refused run removes what it made). A SIGKILL can leave a harmless
partial `.report.tmp`, with no `report.json`, so that run reads as incomplete. Disk-full or EIO
on a write exits 2 (usage), like other output-location failures. Nothing existing is replaced,
removed or locked. Run directories accumulate: nothing prunes them, the user deletes old ones.

## Threat model

Untrusted: manifest content, image bytes and file names inside the corpus. Trusted: the user and
the directories they pass (corpus roots, results directory). Out of scope: a concurrent local
attacker with write access to those directories who races renames and unlinks. What remains is
defence in depth, not immunity. The results directory is walked from `/` without following
symlinks (directories made on the way are removed again if refused). Before the run directory is
made and again after the last file, the walk goes up from its descriptor with `openat("..")` and
refuses if it or any ancestor has the (device, inode) of a corpus root (taken from descriptors
held since the manifests were read) or is a checkout; a refusal after the last file removes what
this call made. A checkout is recognised by name: a `.git` entry and a `pyproject.toml` whose
`project.name` is `fastfoto-linux`, so a renamed fork is not recognised. An unparseable
`pyproject.toml` is someone else's; one that cannot be read (EIO, EACCES), in the location or
an ancestor, makes the check refuse (fail closed) with "cannot verify the output location".
Residual windows: a rename that lands after that last check cannot be closed by user-space code,
and a file written into a forbidden tree before the check is removed afterwards, not prevented.

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
