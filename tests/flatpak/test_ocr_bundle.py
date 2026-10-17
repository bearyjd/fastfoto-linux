"""The Flatpak brings OCR: Leptonica and Tesseract built from pinned sources, the English and
orientation data (not the whole data repository), and OCRmyPDF with its wheels."""

import re
from typing import Any

from tests.flatpak.helpers import (
    FLATPAK_DIR,
    PACKAGING,
    RUNTIME_MODULE,
    commands,
    load_json,
    load_manifest,
    module,
)

TESSDATA = "/app/share/tessdata"
# tessdata_fast 4.1.0, the same files Homebrew's tesseract formula installs.
TESSDATA_SHA256 = {
    "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "osd.traineddata": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}


def names() -> list[str]:
    return [e if isinstance(e, str) else e["name"] for e in load_manifest()["modules"]]


def archive(name: str) -> dict[str, Any]:
    [source] = [s for s in module(name)["sources"] if s.get("type") == "archive"]
    return source


def test_leptonica_and_tesseract_are_built_after_the_shim_and_before_the_python_wheels() -> None:
    order = names()
    assert order.index("usb-gap-shim") < order.index("leptonica") < order.index("tesseract")
    assert order.index("tesseract") < order.index("tessdata")
    assert order.index("tessdata") < order.index(RUNTIME_MODULE.name)  # so Python edits reuse it


def test_both_are_cmake_builds_of_a_hashed_release_archive_that_a_checker_can_bump() -> None:
    for name in ("leptonica", "tesseract"):
        assert module(name)["buildsystem"] == "cmake-ninja", name
        source = archive(name)
        assert source["url"].startswith("https://github.com/"), name
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), name
        assert source["x-checker-data"]["type"] == "anitya", name
        assert "$version" in source["x-checker-data"]["url-template"], name


def test_tesseract_is_built_lean_without_the_training_tools_or_a_network_library() -> None:
    options = module("tesseract")["config-opts"]
    assert "-DBUILD_TRAINING_TOOLS=OFF" in options
    assert "-DDISABLE_CURL=ON" in options
    assert "-DCMAKE_BUILD_TYPE=Release" in options
    assert "-DCMAKE_BUILD_TYPE=Release" in module("leptonica")["config-opts"]


def test_the_data_is_english_and_orientation_from_tessdata_fast_as_single_files() -> None:
    sources = module("tessdata")["sources"]
    assert not [s for s in sources if s["type"] == "git"]  # the repository is about 340 MB
    data = {s["url"].rsplit("/", 1)[-1]: s for s in sources if s["url"].endswith(".traineddata")}
    assert {name: s["sha256"] for name, s in data.items()} == TESSDATA_SHA256
    for source in data.values():
        assert source["type"] == "file"
        assert "/tessdata_fast/" in source["url"]
        assert "/4.1.0/" in source["url"]


def test_the_data_is_installed_into_the_tessdata_folder_tesseract_reads() -> None:
    steps = commands(module("tessdata")).replace("${FLATPAK_DEST}", "/app")
    for name in TESSDATA_SHA256:
        assert re.search(rf"install\b.*{name}.*{TESSDATA}", steps), name
    assert "-DTESSDATA_PREFIX" not in " ".join(module("tesseract")["config-opts"])


def test_tessdata_prefix_names_the_folder_itself_as_tesseract_4_and_later_read_it() -> None:
    assert f"--env=TESSDATA_PREFIX={TESSDATA}" in load_manifest()["finish-args"]


def test_the_cleanup_keeps_the_tesseract_configs_and_the_data_and_drops_cmake_files() -> None:
    cleanup = load_manifest()["cleanup"]
    assert "/lib/cmake" in cleanup
    for kept in ("/share/tessdata", "/share/tessdata/configs", "/bin/tesseract"):
        assert kept not in cleanup
    assert "/share/tessdata/*" not in cleanup


def test_ocrmypdf_and_its_native_wheels_are_installed_from_the_hashed_ocr_requirements() -> None:
    runtime = load_json(RUNTIME_MODULE)
    [command] = runtime["build-commands"]
    assert "-r requirements-ocr.txt" in command
    assert "requirements-desktop.txt" not in command
    [requirements] = [s for s in runtime["sources"] if "path" in s]
    assert (FLATPAK_DIR / requirements["path"]).resolve() == PACKAGING / "requirements-ocr.txt"
    files = [s["url"].rsplit("/", 1)[-1] for s in runtime["sources"] if "url" in s]
    wheels = {name.split("-")[0].lower().replace("_", "-") for name in files}
    assert {"ocrmypdf", "pypdfium2", "pdfminer-six", "cryptography"} <= wheels


def test_no_ghostscript_is_needed_because_ocrmypdf_rasterizes_with_pdfium() -> None:
    manifest_text = (FLATPAK_DIR / "io.github.bearyjd.FastFotoLinux.yml").read_text()
    assert "ghostscript" not in manifest_text.lower()
