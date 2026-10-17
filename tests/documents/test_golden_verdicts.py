"""``is_blank_beside`` on every synthetic fixture family against a golden table taken before
the verdicts moved into the analysis step (see ``golden_cases``)."""

import json
from pathlib import Path

from tests.documents.golden_cases import verdict_table

GOLDEN: dict[str, bool] = json.loads(
    (Path(__file__).parent / "golden_verdicts.json").read_text(encoding="utf-8")
)


def test_the_golden_holds_blank_and_kept_pages() -> None:
    assert len(GOLDEN) >= 100
    assert True in GOLDEN.values()
    assert False in GOLDEN.values()


def test_every_fixture_is_judged_as_it_was() -> None:
    table = verdict_table()
    assert sorted(table) == sorted(GOLDEN)
    changed = sorted(label for label, verdict in table.items() if verdict != GOLDEN[label])
    assert changed == []
