"""Every OCR run prepares a private model environment before spawning its child."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from fastfoto_linux.documents import ocr, ocr_languages


def test_run_ocr_prepares_selected_model_overlay_inside_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    child_environments = []

    def prepare(langs: str, folder: Path, env: dict[str, str]) -> dict[str, str]:
        calls.append((langs, folder, env))
        assert folder.is_relative_to(tmp_path)
        assert folder.stat().st_mode & 0o777 == 0o700
        return {**env, "TESSDATA_PREFIX": str(folder / "models")}

    def spawn(*args: object, **kwargs: object) -> SimpleNamespace:
        child_environments.append(kwargs["env"])
        return SimpleNamespace(wait=lambda **kw: 0)

    monkeypatch.setattr(ocr_languages, "prepare_tessdata", prepare)
    monkeypatch.setattr(ocr.subprocess, "Popen", spawn)
    monkeypatch.setattr(ocr, "ocrmypdf_version", lambda executable: "17.13.0")
    monkeypatch.setattr(ocr, "_checked", lambda target, pages: b"%PDF-searchable")
    outcome = ocr.run_ocr(
        b"%PDF-input",
        executable="/trusted/ocrmypdf",
        langs="eng+spa",
        page_count=1,
        staging_parent=tmp_path,
        timeout_s=1,
    )
    assert outcome.status is ocr.OcrStatus.DONE
    assert len(calls) == 1
    assert calls[0][0] == "eng+spa"
    assert child_environments[0]["TESSDATA_PREFIX"] == str(calls[0][1] / "models")
    assert not calls[0][1].exists()
