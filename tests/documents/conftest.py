"""Documents tests never run a real ``ocrmypdf``, even on a machine that has one."""

import pytest

from tests import _fake_ocrmypdf as fake


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)
