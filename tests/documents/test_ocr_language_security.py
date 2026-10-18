"""Adversarial transport, cache, and model-use regression checks."""

import hashlib
import io
import os
import stat
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastfoto_linux.documents import ocr_downloads, ocr_languages
from fastfoto_linux.documents.errors import OcrCancelledError
from tests.documents import test_ocr_languages as shared
from tests.documents.test_ocr_languages import (
    MODELS,
    REVISION,
    fake_download,
    fake_tesseract,
    install_managed,
)

models = shared.models


def test_private_opener_rejects_redirect_before_following_official_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = urllib.request.build_opener
    opened = []

    def build(*handlers: object) -> urllib.request.OpenerDirector:
        assert any(isinstance(handler, ocr_downloads._NoRedirect) for handler in handlers)
        opener = original(*handlers)
        redirect = next(
            handler for handler in opener.handlers if isinstance(handler, ocr_downloads._NoRedirect)
        )

        def open_request(request: object, *, timeout: float) -> None:
            opened.append(request)
            redirect.http_error_302(
                urllib.request.Request(str(request)),
                io.BytesIO(),
                302,
                "Found",
                {"location": "https://untrusted.example/model"},
            )

        monkeypatch.setattr(opener, "open", open_request)
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", build)
    with pytest.raises(OSError, match="redirect"):
        ocr_downloads._open_url(
            f"{ocr_downloads.MODEL_BASE_URL}/{REVISION}/spa.traineddata", timeout=1
        )
    assert len(opened) == 1
    assert "untrusted.example" not in str(opened[0])


def test_disabled_git_hash_reports_unavailable_verification_without_using_cache(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")

    def disabled(*args: object, **kwargs: object) -> None:
        raise ValueError("algorithm disabled")

    monkeypatch.setattr(hashlib, "sha1", disabled)
    inventory = ocr_languages.discover_languages()
    assert not inventory.installed
    assert "verification unavailable" in inventory.error


def test_nonsticky_shared_data_parent_cannot_redirect_cache_writes(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "shared"
    base.mkdir(mode=0o777)
    base.chmod(0o777)
    monkeypatch.setenv("XDG_DATA_HOME", str(base / "data"))
    fake_download(monkeypatch, MODELS["spa"])
    with pytest.raises(OSError, match=r"(safe|trusted)"):
        ocr_downloads.download_languages(["spa"])
    assert not (base / "data").exists()


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_download_preserves_a_verified_model_published_concurrently(
    models: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    cancel = threading.Event()
    responses = []

    def opened(url: str, *, timeout: float) -> io.BytesIO:
        install_managed(models, "spa")
        response = io.BytesIO(MODELS["spa"] if cancelled else b"wrong!!")
        response.geturl = lambda: url
        responses.append(response)
        return response

    def progress(*args: object) -> None:
        if cancelled:
            cancel.set()

    monkeypatch.setattr(ocr_downloads, "_open_url", opened)
    expected = OcrCancelledError if cancelled else OSError
    with pytest.raises(expected):
        ocr_downloads.download_languages(["spa"], cancel=cancel, progress=progress)
    assert (models / "spa.traineddata").read_bytes() == MODELS["spa"]
    assert sorted(path.name for path in models.iterdir()) == ["spa.traineddata"]
    assert responses[0].closed


def test_overlay_copies_verified_bytes_even_if_managed_cache_changes_after_validation(
    models: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    fake_tesseract(tmp_path / "system", monkeypatch, "eng", "osd")
    original = ocr_languages._system_models

    def replace_after_validation(*args: object, **kwargs: object) -> tuple:
        (models / "spa.traineddata").write_bytes(b"changed after validation")
        return original(*args, **kwargs)

    monkeypatch.setattr(ocr_languages, "_system_models", replace_after_validation)
    environment = ocr_languages.prepare_tessdata("eng+spa", tmp_path, {})
    overlay = Path(environment["TESSDATA_PREFIX"])
    assert (overlay / "spa.traineddata").read_bytes() == MODELS["spa"]
    assert (models / "spa.traineddata").read_bytes() != MODELS["spa"]


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("sticky", [False, True])
def test_foreign_ancestor_is_trusted_only_on_a_readonly_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, readonly: bool, sticky: bool
) -> None:
    original_stat, original_statvfs = Path.stat, os.statvfs

    def directory_info(path: Path, **kwargs: object) -> os.stat_result:
        info = original_stat(path, **kwargs)
        if path != tmp_path:
            return info
        fields = list(info)
        fields[4] = 65534
        fields[0] = stat.S_IFDIR | (0o1777 if sticky else 0o755)
        return os.stat_result(fields)

    def mount_info(path: Path) -> os.statvfs_result | SimpleNamespace:
        if path == tmp_path:
            return SimpleNamespace(f_flag=os.ST_RDONLY if readonly else 0)
        return original_statvfs(path)

    monkeypatch.setattr(Path, "stat", directory_info)
    monkeypatch.setattr(os, "statvfs", mount_info)
    if readonly:
        assert ocr_languages._trusted_base(tmp_path / "data") == tmp_path / "data"
    else:
        with pytest.raises(OSError, match=r"(safe|trusted)"):
            ocr_languages._trusted_base(tmp_path / "data")


def test_readonly_mount_does_not_relax_managed_cache_owner_requirement(
    models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_managed(models, "spa")
    original = Path.lstat

    def foreign_cache(path: Path) -> os.stat_result:
        info = original(path)
        if path != models:
            return info
        fields = list(info)
        fields[4] = 65534
        return os.stat_result(fields)

    monkeypatch.setattr(Path, "lstat", foreign_cache)
    monkeypatch.setattr(os, "statvfs", lambda path: SimpleNamespace(f_flag=os.ST_RDONLY))
    with pytest.raises(OSError, match=r"(safe|owned)"):
        ocr_languages._cache_root(ocr_languages._catalog())
