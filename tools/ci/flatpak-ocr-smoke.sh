#!/bin/sh
# Smoke test of the OCR that the Flatpak brings, run inside its sandbox on an installed bundle.
# CI runs it after the flatpak job has installed the bundle for the user; by hand: install the
# bundle with `flatpak --user install fastfoto-linux.flatpak`, then run this script.
#
# It shows that the programs the manifest builds are the ones the app finds and uses: Tesseract
# lists English and the orientation data, OCRmyPDF runs as the app's module, and the app's own
# `ffscan doc process --ocr on` (which exits 3 when it cannot find its OCR programs) turns a
# generated page of text into a PDF whose text layer holds the words. The runtime has no
# pdftotext, so the text is read with pdfminer, which OCRmyPDF brings. Only one temporary folder
# is shared with the sandbox, and the page holds no data but the words below.
set -eu

APP="${1:-io.github.bearyjd.FastFotoLinux}"
work=$(mktemp -d)
trap 'rm -r "$work"' EXIT

inside() {
    flatpak run --filesystem="$work" "$@"
}

echo "== Tesseract and its data"
inside --command=tesseract "$APP" --version 2>&1 | head -n 1
langs=$(inside --command=tesseract "$APP" --list-langs)
printf '%s\n' "$langs"
printf '%s\n' "$langs" | grep -qx eng
printf '%s\n' "$langs" | grep -qx osd

echo "== OCRmyPDF"
version=$(inside --command=python3 "$APP" -I -m ocrmypdf --version)
echo "ocrmypdf $version"
printf '%s\n' "$version" | grep -q '^17\.'

echo "== Offline catalogue and writable model cache inside the sandbox"
inside --unshare=network --command=python3 "$APP" -I -c '
import os
import stat
import tempfile
from pathlib import Path
from fastfoto_linux.documents.ocr_languages import _cache_root, _catalog, discover_languages

catalog = _catalog()
root = _cache_root(catalog, create=True)
expected = Path(os.environ["XDG_DATA_HOME"]).resolve() / "fastfoto-linux" / "tessdata"
assert root == expected / catalog.revision
assert root.stat().st_uid == os.getuid()
assert stat.S_IMODE(root.stat().st_mode) == 0o700
with tempfile.TemporaryFile(dir=root) as probe:
    probe.write(b"offline cache write check")
    probe.flush()
inventory = discover_languages()
assert not inventory.error, inventory.error
assert "eng" in {language.code for language in inventory.installed}
assert inventory.orientation is not None and inventory.orientation.installed
'

echo "== A page of text through the app"
inside --command=python3 "$APP" -I -c '
import sys
from PIL import Image, ImageDraw, ImageFont

page = Image.new("L", (2550, 3300), 255)  # letter size at 300 dpi
draw = ImageDraw.Draw(page)
font = ImageFont.load_default(size=110)
for row, line in enumerate(("Searchable text", "inside the Flatpak", "bundle of Tesseract")):
    draw.text((250, 400 + row * 300), line, fill=0, font=font)
page.save(sys.argv[1], dpi=(300, 300))
' "$work/page.png"
inside --command=ffscan "$APP" doc process --ocr on --lang eng --mkdir --name smoke \
    --out "$work/out" "$work/page.png"
set -- "$work"/out/smoke_*.pdf
test -f "$1"

echo "== The text layer of the PDF"
text=$(inside --command=python3 "$APP" -I -c '
import sys
from pdfminer.high_level import extract_text

print(extract_text(sys.argv[1]))
' "$1")
printf '%s\n' "$text" | grep -qi searchable
printf '%s\n' "$text" | grep -qi tesseract
echo "OK: the Flatpak finds and runs its OCR"
