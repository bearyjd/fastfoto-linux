"""Hypothesis must not write into the checkout (an older `.hypothesis` there is not ours)."""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.configuration import storage_directory

from tests.fuzz import conftest


@given(text=st.text(max_size=5))
def test_an_example_run_adds_and_changes_nothing_in_the_checkout_cache(text: str) -> None:
    assert isinstance(text, str)
    assert conftest.snapshot_checkout_cache() == conftest.CHECKOUT_CACHE_AT_START
    assert str(storage_directory("x").path).startswith(conftest.HOME_DIR)
    assert not Path(conftest.HOME_DIR).is_relative_to(conftest.REPO)
