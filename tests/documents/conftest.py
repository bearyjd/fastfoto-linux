"""Documents tests never run a real ``ocrmypdf``, even on a machine that has one."""

from pathlib import Path

import pytest

from tests import _fake_ocrmypdf as fake


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path / "no-ocr", monkeypatch)
