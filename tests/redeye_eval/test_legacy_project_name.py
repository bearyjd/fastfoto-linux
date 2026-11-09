"""The checkout guard knows a checkout from before the rename (pyproject name fastfoto-linux)."""

import pytest

from fastfoto_linux.evaluation import redeye_output


@pytest.mark.parametrize("name", ["feedshot", "fastfoto-linux"])
def test_a_pyproject_of_this_project_under_either_name_is_ours(name: str) -> None:
    assert redeye_output._is_our_pyproject(f'[project]\nname = "{name}"\n'.encode())


@pytest.mark.parametrize("name", ["feedshots", "fastfoto", "someone-else"])
def test_another_project_is_not_ours(name: str) -> None:
    assert not redeye_output._is_our_pyproject(f'[project]\nname = "{name}"\n'.encode())
