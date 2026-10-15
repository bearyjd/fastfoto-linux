"""Inside a Flatpak sandbox the shim comes from ``$FF680W_SHIM`` only (review round 1, item 3).

The manifest sets the variable to the shim built into the Flatpak. A shim in the user's home
(``~/.local/lib/fastfoto-linux``, which the sandbox sees as its own home) or in a checkout is
something the Flatpak did not ship, so it is not even a candidate there.
"""

from pathlib import Path

import pytest

from fastfoto_linux.scanner import shim_trust
from fastfoto_linux.scanner.target import SHIM_FILENAME, default_shim_candidates

SHIM_IN_APP = Path("/app/lib/fastfoto-linux") / SHIM_FILENAME


@pytest.fixture
def home_and_checkout(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """An environment with a HOME holding a user-built shim, and a checkout with a built one."""
    home = tmp_path / "home"
    (home / ".local" / "lib" / "fastfoto-linux").mkdir(parents=True)
    (home / ".local" / "lib" / "fastfoto-linux" / SHIM_FILENAME).write_bytes(b"")
    repo = tmp_path / "repo"
    (repo / "tools" / "usb-gap-shim").mkdir(parents=True)
    (repo / "tools" / "usb-gap-shim" / SHIM_FILENAME).write_bytes(b"")
    return {"HOME": str(home), "FF680W_SHIM": str(SHIM_IN_APP)}, repo


def in_flatpak(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, present: bool = True) -> None:
    marker = tmp_path / ".flatpak-info"
    if present:
        marker.write_text("[Application]\n")
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", marker)


def test_inside_a_flatpak_the_variable_is_the_only_candidate(
    home_and_checkout: tuple[dict[str, str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, repo = home_and_checkout
    in_flatpak(monkeypatch, tmp_path)
    assert default_shim_candidates(env, repo_root=repo) == (SHIM_IN_APP,)


def test_inside_a_flatpak_without_the_variable_there_is_no_candidate(
    home_and_checkout: tuple[dict[str, str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, repo = home_and_checkout
    in_flatpak(monkeypatch, tmp_path)
    assert default_shim_candidates({"HOME": env["HOME"]}, repo_root=repo) == ()
    assert default_shim_candidates({**env, "FF680W_SHIM": ""}, repo_root=repo) == ()


def test_outside_a_flatpak_the_home_and_the_checkout_are_still_searched(
    home_and_checkout: tuple[dict[str, str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, repo = home_and_checkout
    in_flatpak(monkeypatch, tmp_path, present=False)
    candidates = default_shim_candidates(env, repo_root=repo)
    assert len(candidates) == 3
    assert candidates[0] == SHIM_IN_APP
    assert candidates[-1] == repo / "tools" / "usb-gap-shim" / SHIM_FILENAME
