"""Where the corpus lives: no default, absolute, no symlinks, outside the checkout."""

import os

import pytest

from fastfoto_linux.evaluation.corpus_manifest import CorpusError
from fastfoto_linux.evaluation.corpus_storage import ENV_VAR, corpus_root, manifest_path
from tests.corpus.helpers import fake_checkout


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "corpus"
    path.mkdir()
    return path


def test_an_explicit_directory_is_used(root) -> None:
    assert corpus_root(root, {}) == root
    assert manifest_path(root, {}) == root / "MANIFEST.json"


def test_the_environment_is_the_fallback_and_explicit_wins(root, tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    assert corpus_root(None, {ENV_VAR: str(root)}) == root
    assert corpus_root(other, {ENV_VAR: str(root)}) == other


@pytest.mark.parametrize("env", [{}, {ENV_VAR: ""}])
def test_there_is_no_default_corpus_path(env) -> None:
    with pytest.raises(CorpusError, match=ENV_VAR):
        corpus_root(None, env)


def test_a_relative_environment_path_is_refused(root, monkeypatch) -> None:
    monkeypatch.chdir(root.parent)
    with pytest.raises(CorpusError, match="absolute"):
        corpus_root(None, {ENV_VAR: "corpus"})


@pytest.mark.parametrize("suffix", ["/../corpus", "/./"])
def test_dot_components_are_refused(root, suffix) -> None:
    with pytest.raises(CorpusError, match="absolute"):
        corpus_root(None, {ENV_VAR: str(root) + suffix})


def test_a_missing_directory_is_refused(tmp_path) -> None:
    with pytest.raises(CorpusError, match="cannot open"):
        corpus_root(tmp_path / "nope", {})


def test_a_symlinked_root_or_ancestor_is_refused(root, tmp_path) -> None:
    (tmp_path / "link").symlink_to(root)
    with pytest.raises(CorpusError, match="cannot open"):
        corpus_root(tmp_path / "link", {})
    (root / "inner").mkdir()
    with pytest.raises(CorpusError, match="cannot open"):
        corpus_root(tmp_path / "link" / "inner", {})


def test_a_root_inside_or_equal_to_a_checkout_is_refused(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "fastfoto-linux"\n')
    (repo / "data" / "deeper").mkdir(parents=True)
    for inside in (repo, repo / "data", repo / "data" / "deeper"):
        with pytest.raises(CorpusError, match="outside the fastfoto-linux checkout"):
            corpus_root(inside, {})


def test_another_project_checkout_is_fine(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "someone-else"\n')
    assert corpus_root(repo, {}) == repo


def test_an_unreadable_pyproject_is_reported_as_unverifiable_not_as_a_checkout(tmp_path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can read a mode 000 file")
    ancestor = fake_checkout(tmp_path / "anc")
    (ancestor / "corpus").mkdir()
    (ancestor / "pyproject.toml").chmod(0)
    try:
        with pytest.raises(CorpusError, match="cannot verify") as info:
            corpus_root(ancestor / "corpus", {})
    finally:
        (ancestor / "pyproject.toml").chmod(0o644)
    assert "outside" not in str(info.value)


def test_a_nul_in_the_path_is_a_corpus_error(tmp_path) -> None:
    with pytest.raises(CorpusError):
        corpus_root(None, {ENV_VAR: str(tmp_path) + "/a\0b"})
