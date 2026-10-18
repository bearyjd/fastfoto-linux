"""OCR model discovery is local; explicit downloads are verified and staged privately."""

import hashlib
import io
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_downloads, ocr_languages, ocr_tools
from fastfoto_linux.documents.errors import OcrCancelledError, OcrMissingError

REVISION = "a" * 40
MODELS = {"eng": b"english", "spa": b"spanish", "deu": b"german", "osd": b"orientation"}


def blob_id(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


@pytest.fixture
def models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    catalog = tmp_path / "catalog.json"
    entries = [
        {"code": code, "name": code.title(), "size": len(data), "git_blob_sha1": blob_id(data)}
        for code, data in MODELS.items()
    ]
    catalog.write_text(
        json.dumps(
            {
                "revision": REVISION,
                "languages": [entry for entry in entries if entry["code"] != "osd"],
                "auxiliaries": [entry for entry in entries if entry["code"] == "osd"],
            }
        )
    )
    monkeypatch.setattr(ocr_languages, "CATALOG_PATH", catalog)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(ocr_tools, "find_tesseract", lambda: None)
    return tmp_path / "data" / "fastfoto-linux" / "tessdata" / REVISION


def install_managed(root: Path, *codes: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for code in codes:
        (root / f"{code}.traineddata").write_bytes(MODELS[code])


def fake_tesseract(root: Path, monkeypatch: pytest.MonkeyPatch, *codes: str) -> list[dict]:
    root.mkdir()
    for code in codes:
        (root / f"{code}.traineddata").write_bytes(MODELS.get(code, b"local"))
    calls = []
    monkeypatch.setattr(ocr_tools, "find_tesseract", lambda: "/trusted/bin/tesseract")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        output = f'List of available languages in "{root}/" ({len(codes)}):\n'
        return subprocess.CompletedProcess(command, 0, output + "\n".join(codes), "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def fake_download(monkeypatch: pytest.MonkeyPatch, data: bytes) -> list[str]:
    urls = []

    def open_url(request: str | urllib.request.Request, *, timeout: float) -> io.BytesIO:
        assert 0 < timeout <= 30
        urls.append(request if isinstance(request, str) else request.full_url)
        response = io.BytesIO(data)
        response.geturl = lambda: urls[-1]
        return response

    monkeypatch.setattr(ocr_downloads, "_open_url", open_url)
    return urls


def test_discovery_combines_system_and_verified_managed_models_without_network(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    calls = fake_tesseract(tmp_path / "system", monkeypatch, "eng", "osd", "custom")
    monkeypatch.setattr(
        ocr_downloads, "_open_url", lambda *a, **k: pytest.fail("network discovery")
    )
    inventory = ocr_languages.discover_languages()
    assert {item.code for item in inventory.installed} == {"eng", "spa", "custom"}
    assert {item.code for item in inventory.available} == {"deu"}
    assert next(item for item in inventory.languages if item.code == "spa").downloaded
    assert calls[0]["command"] == ["/trusted/bin/tesseract", "--list-langs"]
    assert 0 < calls[0]["timeout"] <= 10
    assert calls[0]["env"]["PATH"] == ocr_tools.ocr_environment()["PATH"]


def test_corrupt_cached_model_is_not_available_offline(models: Path) -> None:
    install_managed(models, "spa")
    (models / "spa.traineddata").write_bytes(b"invalid")
    assert not any(item.installed for item in ocr_languages.discover_languages().languages)


def test_unavailable_tesseract_still_lists_downloadable_languages(models: Path) -> None:
    inventory = ocr_languages.discover_languages()
    assert {item.code for item in inventory.available} == {"eng", "spa", "deu"}
    assert "Tesseract" in inventory.error


def test_discovery_timeout_is_reported_without_hiding_downloaded_models(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    monkeypatch.setattr(ocr_tools, "find_tesseract", lambda: "/trusted/bin/tesseract")

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("tesseract", 5)

    monkeypatch.setattr(subprocess, "run", timeout)
    inventory = ocr_languages.discover_languages()
    assert {item.code for item in inventory.installed} == {"spa"}
    assert inventory.error


def test_explicit_download_uses_pinned_official_object_and_reports_progress(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = fake_download(monkeypatch, MODELS["spa"])
    progress = []
    ocr_downloads.download_languages(["spa"], progress=lambda *args: progress.append(args))
    assert (models / "spa.traineddata").read_bytes() == MODELS["spa"]
    assert urls == [
        f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{REVISION}/spa.traineddata"
    ]
    assert progress[-1] == ("spa", len(MODELS["spa"]), len(MODELS["spa"]))
    assert [path.name for path in models.iterdir()] == ["spa.traineddata"]


@pytest.mark.parametrize(
    "code", ["../spa", "/spa", "spa/eng", "https://example.test/model", "bogus"]
)
def test_invalid_or_unknown_codes_never_open_the_network(
    models: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    monkeypatch.setattr(ocr_downloads, "_open_url", lambda *a, **k: pytest.fail("unsafe request"))
    with pytest.raises(ValueError):
        ocr_downloads.download_languages([code])
    assert not models.exists()


@pytest.mark.parametrize("bad", [b"wrong!!", b"short", b"spanish-and-extra"])
def test_wrong_object_or_size_never_publishes_a_model(
    models: Path, monkeypatch: pytest.MonkeyPatch, bad: bytes
) -> None:
    fake_download(monkeypatch, bad)
    with pytest.raises(OSError, match=r"(integrity|size|verify|verification)"):
        ocr_downloads.download_languages(["spa"])
    assert not (models / "spa.traineddata").exists()
    assert not models.exists() or not list(models.iterdir())


def test_already_verified_model_is_reused_offline(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    monkeypatch.setattr(ocr_downloads, "_open_url", lambda *a, **k: pytest.fail("redownload"))
    ocr_downloads.download_languages(["spa"])
    assert (models / "spa.traineddata").read_bytes() == MODELS["spa"]


def test_cancellation_removes_partial_download(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    fake_download(monkeypatch, MODELS["spa"])

    def stop(*args: object) -> None:
        cancel.set()

    with pytest.raises(OcrCancelledError):
        ocr_downloads.download_languages(["spa"], cancel=cancel, progress=stop)
    assert not models.exists() or not list(models.iterdir())


def test_pre_cancelled_download_never_requests_network(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(
        ocr_downloads, "_open_url", lambda *a, **k: pytest.fail("cancelled request")
    )
    with pytest.raises(OcrCancelledError):
        ocr_downloads.download_languages(["spa"], cancel=cancel)
    assert not models.exists()


def test_no_managed_selection_preserves_environment(models: Path, tmp_path: Path) -> None:
    env = {"PATH": "/trusted/bin", "TESSDATA_PREFIX": "/existing/models"}
    original = dict(env)
    assert ocr_languages.prepare_tessdata("eng", tmp_path, env) == original
    assert env == original
    assert not (tmp_path / "tessdata").exists()


def test_mixed_models_overlay_includes_orientation_and_tesseract_configs(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    system = tmp_path / "system"
    fake_tesseract(system, monkeypatch, "eng", "osd")
    for folder in ("configs", "tessconfigs"):
        (system / folder).mkdir()
        (system / folder / "pdf").write_text("configuration")
    staging = tmp_path / "private"
    staging.mkdir(mode=0o700)
    env = {"PATH": "/trusted/bin"}
    result = ocr_languages.prepare_tessdata("eng+spa", staging, env)
    overlay = Path(result["TESSDATA_PREFIX"])
    assert overlay.is_relative_to(staging)
    assert overlay.stat().st_mode & 0o777 == 0o700
    assert (overlay / "eng.traineddata").read_bytes() == MODELS["eng"]
    assert (overlay / "spa.traineddata").read_bytes() == MODELS["spa"]
    assert (overlay / "osd.traineddata").read_bytes() == MODELS["osd"]
    assert (overlay / "configs" / "pdf").is_file()
    assert (overlay / "tessconfigs" / "pdf").is_file()
    assert "TESSDATA_PREFIX" not in env
    assert os.environ.get("TESSDATA_PREFIX") != str(overlay)


def test_preflight_reports_missing_pack_without_network(models: Path) -> None:
    install_managed(models, "eng", "osd")
    ocr_languages.require_languages("eng")
    with pytest.raises(OcrMissingError, match="spa"):
        ocr_languages.require_languages("eng+spa")


def test_overlay_rejects_corrupted_managed_model(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    (models / "spa.traineddata").write_bytes(b"corrupt")
    fake_tesseract(tmp_path / "system", monkeypatch, "eng", "osd")
    with pytest.raises(OcrMissingError, match="spa"):
        ocr_languages.prepare_tessdata("eng+spa", tmp_path, {"PATH": "/trusted/bin"})


def test_preflight_requires_orientation_for_rotation(models: Path) -> None:
    install_managed(models, "eng")
    with pytest.raises(OcrMissingError, match="osd"):
        ocr_languages.require_languages("eng")


def test_orientation_metadata_is_visible_but_not_a_checkbox_language(models: Path) -> None:
    inventory = ocr_languages.discover_languages()
    assert inventory.orientation is not None
    assert inventory.orientation.code == "osd"
    assert inventory.orientation.size == len(MODELS["osd"])
    assert not inventory.orientation.installed
    assert all(item.code != "osd" for item in inventory.languages)


def test_explicit_orientation_download_is_verified(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_download(monkeypatch, MODELS["osd"])
    ocr_downloads.download_languages(["osd"])
    assert (models / "osd.traineddata").read_bytes() == MODELS["osd"]


def test_all_requested_codes_are_validated_before_first_download(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_downloads, "_open_url", lambda *a, **k: pytest.fail("unsafe batch"))
    with pytest.raises(ValueError):
        ocr_downloads.download_languages(["spa", "../eng"])
    assert not models.exists()


def test_redirect_to_another_host_is_rejected(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def redirected(*args: object, **kwargs: object) -> io.BytesIO:
        response = io.BytesIO(MODELS["spa"])
        response.geturl = lambda: "https://untrusted.example/spa.traineddata"
        return response

    monkeypatch.setattr(ocr_downloads, "_open_url", redirected)
    with pytest.raises(OSError, match=r"(redirect|host|URL)"):
        ocr_downloads.download_languages(["spa"])
    assert not (models / "spa.traineddata").exists()


def test_managed_symlink_is_not_treated_as_verified_cache(models: Path, tmp_path: Path) -> None:
    models.mkdir(parents=True)
    outside = tmp_path / "outside.traineddata"
    outside.write_bytes(MODELS["spa"])
    (models / "spa.traineddata").symlink_to(outside)
    assert not any(item.installed for item in ocr_languages.discover_languages().languages)


def test_symlink_cache_root_cannot_redirect_download_writes(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "other"
    target.mkdir()
    models.parent.mkdir(parents=True)
    models.symlink_to(target, target_is_directory=True)
    fake_download(monkeypatch, MODELS["spa"])
    with pytest.raises(OSError, match=r"(safe|symlink|cache|trusted)"):
        ocr_downloads.download_languages(["spa"])
    assert not list(target.iterdir())


def test_download_has_a_whole_transfer_deadline(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_download(monkeypatch, MODELS["spa"])
    ticks = iter(range(0, 1_000_000, 1000))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    with pytest.raises(OSError, match=r"(time|deadline)"):
        ocr_downloads.download_languages(["spa"])
    assert not (models / "spa.traineddata").exists()
