# Contributing

fastfoto-linux is a Python 3.13+ project managed with [uv](https://docs.astral.sh/uv/). CI runs
on Python 3.13 and 3.14. See `README.md` for what the tool does and `docs/design/` for the design
notes.

## Set up

```sh
uv sync                         # runtime and dev dependencies, from uv.lock
uv sync --extra ocr             # also ocrmypdf (searchable PDFs); Tesseract is a program, install it separately
uv run ffscan --help
```

The desktop app (`fastfoto`) needs the distribution's PySide6 and Kirigami, which are not Python
dependencies on purpose (see the README). Its Qt tests run only where they are installed; the
`gui (fedora)` CI job runs them in a container.

## Checks to run before you push

<!-- AUTO-GENERATED: from pyproject.toml and .github/workflows/ci.yml -->
```sh
uv run ruff check .
uv run ruff format --check .      # `uv run ruff format .` to fix
uv run pytest -n auto --cov --cov-report=term-missing
uv run coverage report --include='*/fastfoto_linux/gui/*' --fail-under=85
```

| Gate | Where it is set |
| --- | --- |
| Ruff rules `E,F,W,I,B,UP,SIM,PL,RUF`, line length 100 | `[tool.ruff]` in `pyproject.toml` |
| Total coverage at least 80% (branch coverage; the Qt layer `gui/qt/*` is omitted) | `fail_under` in `pyproject.toml` |
| Coverage of the plain-Python `gui/` modules at least 85% | `test` job in `.github/workflows/ci.yml` |
| Qt layer coverage at least 80% | `gui (fedora)` job, `tools/ci/coveragerc-gui-qt` |
| Each test times out after 60 s | `timeout` in `pyproject.toml` |
| Markers `real_scans` and `hardware` are skipped by default | see "Tests" below |
<!-- END AUTO-GENERATED -->

`uv.lock` and the hashed requirement files must agree. If you change dependencies, commit
`pyproject.toml` and `uv.lock` together and regenerate the files CI compares them with:

```sh
uv export --locked --no-dev --no-emit-project --hashes --no-header --no-annotate --quiet > packaging/requirements-desktop.txt
uv export --locked --no-dev --no-emit-project --extra ocr --hashes --no-header --no-annotate --quiet > packaging/requirements-ocr.txt
```

## CI: five required checks

<!-- AUTO-GENERATED: from .github/workflows/ci.yml -->
| Check | What it does |
| --- | --- |
| `lint` | Refuses tracked `test-scans`, `captures`, `*.pcap`, `*.pcapng`; `ruff check`; `ruff format --check`; the two hashed requirement files match `uv.lock` |
| `test (3.13)` | `pytest -n auto --cov` (80%), `gui/` coverage (85%), wheel contents (face model and licence, QML files, `fastfoto` launcher, no PySide dependency) |
| `test (3.14)` | The same on Python 3.14 |
| `gui (fedora)` | Fedora container with the distribution's PySide6 and Kirigami; Qt and QML tests with `FASTFOTO_REQUIRE_QT=1`, Qt layer coverage at least 80% |
| `flatpak` | Builds `packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml`, installs the bundle, runs `tools/ci/flatpak-ocr-smoke.sh` in the sandbox |
<!-- END AUTO-GENERATED -->

All five must pass before a PR is merged. Docs-only changes still run all five.

## Workflow

One pull request per step, opened with `gh`:

1. Branch from an up-to-date `main`.
2. Red commit: tests only (plus the smallest stubs that make them import). Run them and see them
   fail on the assertions. Lint stays green. Commit as `test: ... (red)` and open the PR.
3. Green commit: the implementation. Do not change the red commit's tests unless a test is wrong,
   and say so in the PR body.
4. Review, fix findings, wait for all five checks to pass.
5. Squash merge.

Commit messages are `<type>: <description>` with type one of feat, fix, refactor, docs, test,
chore, perf, ci. PR bodies have a summary, the design, a test plan and a privacy note.

## Code rules

- Full type hints; frozen dataclasses; return new objects instead of changing inputs (copy a numpy
  array before changing it).
- Functions under about 50 lines, files under about 400; named constants rather than magic
  numbers; image-geometry thresholds in millimetres, converted with the dpi.
- Clear, explicit errors; `logging` in library code, no `print()`.
- Package code in `src/fastfoto_linux/`, tests in `tests/`.

## Privacy: this repository is public

- Never commit `test-scans/`, scans, captures or pcaps (the `lint` job fails on them), or `*.so`.
- Never put scanner serial numbers, personal paths, names, addresses or e-mail in code, tests, docs
  or PR text. Use placeholders.
- Stage files by name (`git add path/to/file`), not `git add -A` or `git add .`.
- Tests that use private scans are marked `real_scans`, assert structure only (counts, boxes within
  a tolerance, booleans) and never print image content or OCR text.

## Tests

- Tests must be deterministic and fast, need no network and never touch the scanner.
- `@pytest.mark.real_scans` tests are skipped when `CI` is set or no scans are found in
  `test-scans/` (or the folder in `FASTFOTO_REAL_SCANS`). `@pytest.mark.hardware` tests need
  `FASTFOTO_HARDWARE=1` and a connected scanner.
- CI runs the suite with pytest-xdist (`-n auto`), so tests must be safe to run in parallel: write
  only inside the `tmp_path` fixture, never to a shared or fixed path, and do not rely on test
  order or on state left in `os.environ` (use `monkeypatch`).
- Several tests in `tests/documents/test_docs_*_claims.py` check statements in `README.md` and
  `docs/design/documents.md`. If you edit those files, run the full suite.

```sh
uv run pytest -n auto -q                       # whole suite
uv run pytest tests/path/test_file.py -q       # one file
```
