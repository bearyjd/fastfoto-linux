# Evaluation corpus tooling

A manifest format, a loader, a split rule and a metrics-only report for a labelled corpus that
later calibration harnesses (for example `ffscan eval deskew`) will build on. **This repository
ships no corpus data, no images and no CLI for it, and no quality has been measured.** The
calibration constants elsewhere in the project are tuned on synthetic images only; nothing here
changes that. Library code lives in `src/fastfoto_linux/evaluation/corpus_*.py`; the schema and an
example are in `corpus/` (`.json` and `.md` only: a test fails if an image lands there).

## Where the corpus lives

Never in the repository. `corpus_root(explicit, env)` takes an explicit directory or
`FASTFOTO_CORPUS_DIR`; there is no default path. The path must be absolute with no `.` or `..`
component, is opened from `/` without following any symlink, and is refused when it is or sits
inside a fastfoto-linux checkout. The manifest is `<root>/MANIFEST.json`.

## Manifest (JSON, version 1)

`format` `fastfoto-corpus`, `version` 1, `split_seed` (16-64 hex) and `items`. Unknown keys,
duplicate keys and NaN or infinity are errors; the file is at most 8 MB and at most 10 000 items.
Each item has `id`, relative POSIX `path`, `sha256`, `kind` (`photo` or `document`), `split`,
the flat rights fields `source`, `licence` (non-empty text, at most 512 characters) and
`consent_scope`, `annotations`, and an optional `group`. A missing rights field is refused by
name. `id`, `sha256` and `path` are unique. `annotations` maps lowercase names to objects whose
contents later work packages validate; here they are only bounded (depth 8, 10 000 values per
item) and frozen. `MANIFEST.schema.json` documents this (JSON Schema 2020-12); the loader is
hand-written and a test keeps the two in step.

Ids must be opaque: never the name of a person or place. `source` is free text for the curator and
is never copied into a report.

## consent_scope

- `private-eval`: the item may be used for local metrics only. It is never shown in docs,
  screenshots, issues or pull requests.
- `redistributable`: the item may appear in docs and demos (roadmap section 4) under its
  `licence`.

## Splits

`split` is `tuning` or `heldout`. The rule is red-eye's (`redeye_split.derived_split`, same
algorithm as red-eye's `split_salt`): 20 % held out, chosen from a hash of the seed and the group
(or the sha256 when there is no group), so a print and its rescans stay together. The loader
refuses any declared split that differs from the derived one; `assign_splits(items, seed)` returns
new item dicts with the split filled in, for authoring. The example manifest's splits come from it.

## Loading and verification

`load_corpus_manifest(path, verify=True)` takes an absolute path with no `.` or `..` component.
The directory is walked from `/` without following any symlink, the manifest is opened
`O_NOFOLLOW` (a symlinked manifest or directory is refused), and the directory is refused if it is
or sits inside a fastfoto-linux checkout (an unreadable `pyproject.toml` is reported as "cannot
verify", not as a checkout). It returns a `CorpusManifest` that holds the directory's file
descriptor (`root_fd`; use `with` or `close()`). `verify_hashes` streams each file through that
descriptor, one component at a time without following symlinks, so replacing the directory path
afterwards cannot redirect a read. A symlink, FIFO or other non-regular file, a missing file, a
file over 4 GiB, more than 256 GiB in all (charged from `fstat` before reading) or a wrong hash is
a `CorpusError` naming the item id only (never the path or the hash). `verify=False` reads no
item file. Descriptors are closed on every path.

Consumers must read item bytes with `read_verified(manifest, item)`: it reads through the same
pinned directory (at most 1 GiB) and checks the sha256 of the very bytes it returns, so what a
harness measures is what the manifest vouches for. Opening `item.path` yourself after a
verification does not give that guarantee.

## Untrusted input

The manifest is untrusted. Its size (8 MB, checked before JSON parsing), item count, text length
(512; paths 1024), annotation depth (8) and annotation size (10 000 values per item, 200 000 in
all, counted iteratively before anything is built) are capped, control characters are refused in
free text and paths, ids may not be `.` or `..`, and hostile JSON nesting is a `CorpusError`, not
a crash. As for red-eye, a concurrent local attacker who races renames is out of scope.

## Reports

`build_report` copies only the format, version, the manifest's sha256, item counts by split and by
kind (zero counts included) and the caller's metrics. It carries no item ids, paths, rights text
or annotations. It also refuses metrics that repeat, ignoring case, any id, group, path component
(with or without suffix), `source`, `licence` or annotation string of the manifest (the top-level
annotation names are schema words and are exempt).

`serialise_report` runs `check_metrics_only` first. It is an allowlist: leaves are booleans, null,
integers below 2^53, finite floats, or one of a closed set of status words (the splits, the kinds,
`pass`, `fail`, `abstain`, `insufficient_data`, `not_applicable`); keys match
`[a-z][a-z0-9_]{0,47}` and are not in a forbidden set (`pixels`, `image`, `crop`, `thumbnail`,
`text`, `ocr_text`, `path`, `source`, `licence`, `id`, `annotations`, ... compared without
underscores); objects have at most 64 keys, lists at most 32 items, nesting at most 8 levels.
Output is `json.dumps(sort_keys=True, indent=2, ensure_ascii=True)` plus a newline, so it is
byte-deterministic.

This guard enforces shape plus the manifest cross-check. It is defence in depth, not a proof: a
number can still encode something. Harness authors use fixed metric keys and never build keys or
strings from item data.

## Limits

`O_NOCTTY` is not set when opening corpus files (that code is red-eye's `redeye_images`); a
follow-up. Nothing here has been run on a real corpus.

## Not done here

Collecting or approving a corpus, per-feature annotation schemas, a CLI and the calibration
harnesses are separate, later work packages.
