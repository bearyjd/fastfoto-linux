"""Reading a plan: a pipe or a link where the plan should be is an error, never a hang."""

import os
from pathlib import Path

import pytest

from fastfoto_linux.library import plan as plan_module
from fastfoto_linux.library.plan import PlanError, read_plan, write_plan

PLAN_TIMEOUT_S = 10


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    root.mkdir()
    return root


@pytest.mark.timeout(PLAN_TIMEOUT_S)
def test_a_pipe_in_place_of_the_plan_is_refused_without_waiting_for_a_writer(
    tmp_path: Path, library: Path
) -> None:
    pipe = tmp_path / "plan.csv"
    os.mkfifo(pipe)
    with pytest.raises(PlanError, match="regular file"):
        read_plan(pipe, library)


def test_a_link_in_place_of_the_plan_is_not_followed(tmp_path: Path, library: Path) -> None:
    real = tmp_path / "real.csv"
    write_plan(real, ())
    link = tmp_path / "plan.csv"
    link.symlink_to(real)
    with pytest.raises(PlanError, match="link"):
        read_plan(link, library)


def test_a_plan_bigger_than_the_limit_is_refused_unread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path
) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, ())
    monkeypatch.setattr(plan_module, "MAX_PLAN_BYTES", plan.stat().st_size - 1)
    with pytest.raises(PlanError, match="too large"):
        read_plan(plan, library)


def test_the_limit_on_a_plan_is_generous() -> None:
    assert plan_module.MAX_PLAN_BYTES >= 64 * 1024 * 1024


def test_a_folder_in_place_of_the_plan_is_an_error_not_a_crash(
    tmp_path: Path, library: Path
) -> None:
    with pytest.raises(PlanError):
        read_plan(tmp_path, library)
