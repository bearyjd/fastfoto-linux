# Changelog

All notable changes to fastfoto-linux are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/) (see `docs/release-process.md`; before 1.0 any minor
version may change behaviour).

No release has been tagged yet. `pyproject.toml` says `0.0.1`, but there is no `v0.0.1` tag, so
everything below is **Unreleased**. The back-fill covers merged pull requests #41 to #88, plus
#94 and #95 which merged afterwards; work before #41 (the scanner transport, photo pipeline,
first Documents mode, desktop app and Flatpak) is in the git history. Entries repeat the pull
request titles; a pull request number is not a claim about quality. Constants such as Auto colour
and deskew thresholds, and the white balance and tint gain scale and preset values, are not yet
calibrated on real scans, and no entry here is an image-quality or OCR-quality claim.

## [Unreleased]

### Added

**Photos**
- Recoverable red-eye review and manual correction (#41).
- Recoverable photo tone adjustments (#43).
- Geometry: quarter-turns and crop, recipe v3 (#45); crop and rotate in the photo editor (#46).
- Straighten: angle in recipe v4 (#53); straighten slider in the photo editor (#54).
- Crop shape presets with swap and ratio-locked drag in the photo editor (#66).
- White balance and tint, recipe schema 5 (#82); sliders with presets in the photo editor (#84).
- Denoise and sharpen, recipe schema 6 (#85); sliders in the photo editor (#86).
- Export presets (lossless, high-quality, small) for photos and documents, backend and CLI (#87);
  a "File size" choice in the scan and document forms (#88).
- The photo editor opens lossless PNG masters (#95).

**Documents**
- Per-page Auto colour output and review overrides (#42).
- Optional paper whitening (cleanup), backend (#56); a paper cleanup choice, preview toggle and
  actual-pixel crop in the desktop app (#57); a `--cleanup` flag for `ffscan doc scan` and
  `ffscan doc process` (#65).
- Per-page manual crop, backend and sidecar v4 (#62); crop a page by hand in the review preview (#63).
- Opt-in despeckle for black-and-white pages, backend and CLI (#68); controls in the document form
  and review screen (#69).
- Opt-in document deskew, backend, CLI and sidecar v6 (#79); deskew in the desktop app with a form
  box, per-page Straighten and Undo (#80).

**Evaluation tooling** (no data is shipped and nothing has been measured)
- `ffscan eval redeye`, a red-eye evaluation harness (#70). Red-eye stays experimental and off by
  default.
- A corpus manifest schema, a rights-checking loader and metrics-only reports (#94).
- A binarisation benchmark of Otsu and Sauvola against adaptive mean on synthetic pages, as a
  diagnostic script and design-note section (#81); the current method was kept.

### Changed

- Dependency updates: pypdf 6.20.1 to 6.21.0 (#48), pluggy 1.6.0 to 1.7.0 (#50), ruff 0.17.0 to
  0.17.1 (#51), Pillow 12.3.0 to 13.0.0 (#59).

### Fixed

- Review follow-ups for #41, #42, #43 (#44); remaining findings for geometry and review preview
  (#47); review preview behaviour pinned and the crop hint tightened (#52); straighten follow-ups
  (#55); crop aspect follow-ups from #66 (#76); crop shape preset edge cases found by adversarial
  review (#67).
- Paper cleanup: size limit, draft validation and small follow-ups (#58); actual paper cleanup
  preview results are reported (#60).
- Desktop app: collapsible language list and narrow-window text wrapping (#61); the language list
  toggle is visible without an icon theme (#64); preview hook forwarding, strict-bool destructive
  slots and the applied/skipped cleanup label (#77).

### Internal

- Bounded the brute-force area-minimal growth test so it fits the CI timeout (#78).
