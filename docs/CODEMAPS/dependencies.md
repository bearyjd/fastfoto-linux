<!-- Generated: 2026-10-17 | Files scanned: 12 | Token estimate: ~700 -->
<!-- AUTO-GENERATED -->
# Dependencies and packaging

## Python (pyproject.toml, uv.lock; Python >=3.13)
- Runtime: `img2pdf`, `numpy`, `opencv-python-headless`, `pikepdf`, `pillow`
- Extra `ocr`: `ocrmypdf`
- Dev group: `pypdf`, `pytest`, `pytest-cov`, `pytest-timeout`, `pytest-xdist`, `pyyaml`, `ruff`
- Not dependencies: PySide6 and Kirigami (use the distribution's; PyPI wheel cannot load system Kirigami)
- Scripts: `ffscan` = `fastfoto_linux.cli:main`; `fastfoto` = `fastfoto_linux.gui.qt.app:main`
- Build backend: hatchling; wheel ships `models/` (YuNet ONNX + licence) and the QML

## System tools
- `scanimage` / SANE `epsonds` backend (USB), or SANE net backend (LAN) via private config dir
- USB gap shim: `tools/usb-gap-shim/ff680w_usb_gap.c` (+ Makefile), preloaded into `scanimage`; chosen by `scanner/shim_trust.py:select_shim`
- libusb-1.0 (ctypes, `scanner/libusb.py`) for the pre-scan check
- OCR: `ocrmypdf` (module of the app's interpreter or on PATH) and `tesseract`; located by `documents/ocr_tools.py`

## Packaging
- `tools/install-desktop.sh`: user-level install (venv seeing system PySide6, shim build, menu entry, `fastfoto`/`ffscan` in `~/.local/bin`); hashed pins `packaging/requirements-{desktop,ocr,build}.txt` (desktop/ocr are `uv export` of uv.lock)
- Flatpak: `packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml` (org.kde.Platform, command `fastfoto`; modules sane-backends, usb-gap-shim, leptonica, tesseract, tessdata, Python wheels from `python-deps.json`); `tools/flatpak/gen_wheel_sources.py`
- Desktop files: `packaging/io.github.bearyjd.FastFotoLinux.{desktop,metainfo.xml,svg}`

## CI (.github/workflows/ci.yml): 5 required checks (lint, test on 3.13 and 3.14, gui (fedora), flatpak)
- `lint`: no committed scans/captures, `ruff check`, `ruff format --check`, requirements files match `uv export`
- `test` (py3.13, py3.14): `pytest -n auto --cov` (80%), gui plain modules 85%, wheel contents checks
- `gui (fedora)`: Qt/QML tests with system PySide6 + Kirigami (`tools/ci/coveragerc-gui-qt`)
- `flatpak`: build bundle, install, `tools/ci/flatpak-ocr-smoke.sh`
<!-- /AUTO-GENERATED -->
