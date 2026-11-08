# Release process

This describes how a release is cut. **Nothing here is automated, and no release has been made yet:**
there are no tags, `pyproject.toml` says `0.0.1`, and the metainfo has a `0.0.1` entry dated
2026-10-15 that no tag backs. Tagging and publishing a release is a decision of the maintainer,
never of a contributor or an automated agent.

## Versioning

[Semantic Versioning](https://semver.org/), before 1.0:

- `0.MINOR.PATCH`. A minor version may change behaviour, options, file formats (recipe and review
  sidecar versions) or defaults; say so under **Changed** in the changelog.
- A patch version holds fixes only.
- `1.0.0` is not planned until the scanner path has been run on more than one unit and the
  known limits below are shorter. That is a judgement, not a rule.

## Tags

- Format: `vX.Y.Z`, or `vX.Y.Z-beta.N` for a pre-release (`v0.1.0-beta.1`). Pre-release tags are
  marked as pre-release on GitHub.
- The tag is on a commit of `main`, and `pyproject.toml` `version` on that commit equals the tag
  without the `v` (a beta `v0.1.0-beta.1` is `0.1.0b1` in `pyproject.toml`, the PEP 440 spelling).
- Tags are never moved. A bad release gets a new patch version.
- The Flathub manifest pins `tag:` and `commit:` to the tag (see `docs/flathub-submission.md`).

## Changelog gate

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

1. A pull request that changes what a user sees (features, options, defaults, fixes, file formats)
   adds a line under `## [Unreleased]`, in the right area and in Added, Changed or Fixed. Use the
   pull request title's wording and its number. Internal-only changes may go under Internal or be
   left out.
2. At release time, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` (the real date), start a new
   empty `[Unreleased]` above it, and add the compare link at the bottom of the file.
3. Check the entries against the merged pull requests since the previous tag:
   `gh pr list --state merged --search "merged:>YYYY-MM-DD" --json number,title`. Do not state
   anything the pull request does not.
4. Gate: the release is not tagged while a merged user-visible pull request has no entry. This is
   a manual check; CI does not enforce it.

## Checklist for each tag

Work through these on the exact commit that will be tagged.

1. The 5 required CI jobs (`lint`, `test (3.13)`, `test (3.14)`, `gui (fedora)`, `flatpak`) are
   green on that commit.
2. Hardware-in-the-loop run by the maintainer on that commit: a real scanner, over USB and over
   Wi-Fi. CI never touches the scanner.
3. For every feature changed since the last tag that makes a quality claim, a held-out evaluation
   report on rights-cleared real scans, kept locally (see `docs/design/corpus.md`). Reports hold
   metrics only. Without one, the feature is described as experimental or uncalibrated, not as
   good.
4. `CHANGELOG.md` entry dated with the real date, the metainfo `<release>` with the same date,
   and `pyproject.toml` `version` bumped.
5. PII scan of the diff since the last tag. The pattern list is in `.omc/STATE.md` (scanner
   serial numbers, private network addresses, e-mail addresses and personal paths). Zero hits.
6. The Flatpak bundle from CI installs on a clean Fedora and a clean Ubuntu VM and reaches the
   scanner list (time it; the goal is ten minutes).
7. The known limits section of the README, and the list below, are updated.
8. Tag and publish the release. **Needs the maintainer's explicit approval.** Then update the
   Flathub manifest `tag:` and `commit:`.

## Known limits (keep this honest)

- One scanner model, the Epson FastFoto FF-680W, tested on very few units. This is not Epson
  software and is not affiliated with Seiko Epson. Other scanners are unsupported.
- The USB path depends on a delay between commands that the scanner's firmware needs
  (`tools/usb-gap-shim`). It is a workaround, not a fix in SANE.
- Calibration constants (Auto colour, deskew, despeckle and similar thresholds, white balance and
  tint gain and preset values) were tuned or checked on synthetic images. No image-quality or
  OCR-quality claim is made from them, and they need checks on real scans.
- Automatic red-eye correction is experimental and off by default.
- The evaluation harness and corpus tooling ship no data; nothing has been measured with them
  in this repository.
- The desktop app needs the distribution's PySide6 and Kirigami (or the Flatpak). The Flathub
  submission is prepared but waits on a release tag (`docs/flathub-submission.md`).
- CI has no Tesseract, so OCR is tested with OCR switched off; in CI OCR runs only in the
  Flatpak smoke test.
