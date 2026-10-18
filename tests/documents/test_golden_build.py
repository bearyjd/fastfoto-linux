"""``build_document`` against a golden: the pages dropped and the bytes of each page and of the
PDF (clock pinned, OCR off, or a fake ``ocrmypdf``), for the kinds of page sets that matter.

The golden was taken before the build was split into analyse and write (see ``golden_cases``).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.documents.golden_cases import BuildCase, build_cases, run_build_case

GOLDEN: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).parent / "golden_build.json").read_text(encoding="utf-8")
)
CASES = build_cases()


def test_the_golden_covers_every_case() -> None:
    assert sorted(GOLDEN) == sorted(CASES)


def test_the_golden_has_pages_dropped_and_pages_kept() -> None:
    dropped = [name for name, record in GOLDEN.items() if record["dropped"]]
    assert len(dropped) >= 5
    assert any(not record["dropped"] for record in GOLDEN.values())
    assert GOLDEN["keep blank"]["dropped"] == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_document_is_what_it_was(name: str, tmp_path: Path, monkeypatch) -> None:
    case: BuildCase = CASES[name]
    assert run_build_case(case, tmp_path, monkeypatch) == GOLDEN[name]
