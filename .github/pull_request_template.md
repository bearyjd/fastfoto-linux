## Summary

<!-- What changes and why, in a few lines. -->

## Design

<!-- Approach, alternatives rejected, limits. Link `docs/design/` notes where relevant. -->

## Test plan

- [ ] Red commit (tests only) precedes the green commit, or this is docs/CI only
- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run pytest -n auto --cov`
- [ ] Qt layer tested where it changed (`gui (fedora)` job)
- [ ] User-visible change: `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] README and `docs/` updated, with no quality claim made from synthetic data

## Privacy note

- [ ] No scans, captures, pcaps, corpus images or manifests, OCR text, scanner serial numbers, network addresses, personal paths or e-mail addresses in the diff or in this text
- [ ] Files were staged by name
