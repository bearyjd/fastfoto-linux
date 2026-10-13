from pathlib import Path

from tests._skips import has_scans, scans_dir_from_env, skip_reason


def test_scans_dir_defaults_when_env_missing_or_empty(tmp_path: Path) -> None:
    assert scans_dir_from_env({}, tmp_path) == tmp_path.resolve()
    assert scans_dir_from_env({"FASTFOTO_REAL_SCANS": ""}, tmp_path) == tmp_path.resolve()


def test_scans_dir_uses_env_and_expands_user(tmp_path: Path) -> None:
    env = {"FASTFOTO_REAL_SCANS": "~/scans", "HOME": str(tmp_path)}
    assert scans_dir_from_env(env, Path("/unused")) == (tmp_path / "scans").resolve()


def test_has_scans_detects_supported_suffixes_recursively_and_case_insensitively(
    tmp_path: Path,
) -> None:
    assert not has_scans(tmp_path / "missing")
    (tmp_path / "notes.txt").write_text("x")
    assert not has_scans(tmp_path)
    (tmp_path / "batch").mkdir()
    (tmp_path / "batch" / "PHOTO-001.TIF").write_bytes(b"x")
    assert has_scans(tmp_path)


def test_real_scans_always_skipped_in_ci_even_when_present(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"x")
    assert skip_reason("real_scans", {"CI": "true"}, tmp_path) is not None


def test_real_scans_run_locally_only_when_present(tmp_path: Path) -> None:
    assert skip_reason("real_scans", {}, tmp_path) is not None
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert skip_reason("real_scans", {}, tmp_path) is None


def test_hardware_requires_explicit_opt_in(tmp_path: Path) -> None:
    assert skip_reason("hardware", {}, tmp_path) is not None
    assert skip_reason("hardware", {"FASTFOTO_HARDWARE": "yes"}, tmp_path) is not None
    assert skip_reason("hardware", {"FASTFOTO_HARDWARE": "1"}, tmp_path) is None
    assert skip_reason("hardware", {"FASTFOTO_HARDWARE": "1", "CI": "true"}, tmp_path) is not None


def test_unmarked_tests_never_skipped(tmp_path: Path) -> None:
    assert skip_reason("slow", {"CI": "true"}, tmp_path) is None
