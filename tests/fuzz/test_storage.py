"""Hypothesis must not write into the checkout."""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.configuration import storage_directory

from tests.fuzz import conftest

REPO = Path(__file__).resolve().parents[2]


@given(text=st.text(max_size=5))
def test_an_example_run_leaves_no_hypothesis_folder_in_the_checkout(text: str) -> None:
    assert isinstance(text, str)
    assert not (REPO / ".hypothesis").exists()
    assert str(storage_directory("x").path).startswith(conftest.HOME_DIR)
