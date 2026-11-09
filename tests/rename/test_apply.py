"""tools/rename/apply.py: the display-name and app-id rename, dry-run by default."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OLD_ID = "io.github.bearyjd.FastFotoLinux"


def load_apply():
    spec = importlib.util.spec_from_file_location("rename_apply", ROOT / "tools/rename/apply.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply = load_apply()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


FILES = {
    f"packaging/{OLD_ID}.desktop": f"Name=FastFoto Linux\nIcon={OLD_ID}\n",
    "README.md": (
        "# FastFoto Linux\nformerly FastFoto Linux\n"
        "Scans with the Epson FastFoto FF-680W via `ffscan`.\n"
    ),
    "src/fastfoto_linux/mod.py": "import fastfoto_linux\nNAME = 'FastFoto'\nFF = 'ff680w_gap'\n",
    ".omc/plans/x.md": "FastFoto Linux\n",
    "uv.lock": "name = 'FastFoto Linux'\n",
    "tools/rename/apply.py": "# FastFoto Linux\n",
    "logo.bin": "",
}


@pytest.fixture
def repo(tmp_path):
    for rel, text in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (tmp_path / "logo.bin").write_bytes(b"FastFoto Linux \xff\xfe")
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.test", "add", "-A")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "x")
    return tmp_path


def test_dry_run_is_the_default_and_changes_nothing(repo, capsys):
    assert apply.main(["--root", str(repo)]) == 0
    assert git(repo, "status", "--porcelain") == ""
    out = capsys.readouterr().out
    assert "dry run" in out
    assert f"packaging/{OLD_ID}.desktop" in out


def test_apply_renames_paths_and_replaces_exact_tokens(repo):
    assert apply.main(["--root", str(repo), "--apply"]) == 0
    new_id = "io.github.bearyjd.Feedshot"
    desktop = repo / f"packaging/{new_id}.desktop"
    assert desktop.read_text() == f"Name=Feedshot\nIcon={new_id}\n"
    assert not (repo / f"packaging/{OLD_ID}.desktop").exists()
    # the move is a git mv: staged as a rename, not a delete plus an untracked file
    assert f"-> packaging/{new_id}.desktop" in git(repo, "status", "--porcelain")


def test_apply_leaves_nominative_and_out_of_scope_text_alone(repo):
    apply.main(["--root", str(repo), "--apply"])
    readme = (repo / "README.md").read_text()
    assert readme.startswith("# Feedshot\nformerly FastFoto Linux\n")
    assert "Epson FastFoto FF-680W" in readme
    assert "`ffscan`" in readme
    assert (repo / "src/fastfoto_linux/mod.py").read_text() == FILES["src/fastfoto_linux/mod.py"]
    for rel in (".omc/plans/x.md", "uv.lock", "tools/rename/apply.py"):
        assert (repo / rel).read_text() == FILES[rel]
    assert (repo / "logo.bin").read_bytes() == b"FastFoto Linux \xff\xfe"


def test_apply_refuses_a_dirty_tree(repo, capsys):
    (repo / "README.md").write_text("changed\n")
    assert apply.main(["--root", str(repo), "--apply"]) == 1
    assert "dirty" in capsys.readouterr().err
    assert (repo / "README.md").read_text() == "changed\n"
    assert (repo / f"packaging/{OLD_ID}.desktop").exists()


def test_name_parameter_allows_a_fallback_name(repo):
    apply.main(["--root", str(repo), "--apply", "--name", "Albumfeed"])
    assert (repo / "packaging/io.github.bearyjd.Albumfeed.desktop").exists()
    assert (repo / "README.md").read_text().startswith("# Albumfeed\n")


def test_second_run_switches_from_the_previous_name(repo):
    apply.main(["--root", str(repo), "--apply"])
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "y")
    apply.main(["--root", str(repo), "--apply", "--old-name", "Feedshot", "--name", "Albumfeed"])
    assert (repo / "packaging/io.github.bearyjd.Albumfeed.desktop").exists()
    assert (repo / "README.md").read_text().startswith("# Albumfeed\nformerly FastFoto Linux\n")


@pytest.mark.parametrize("bad", ["Feed Shot", "feed/shot", "", "FastFoto Linux"])
def test_rejects_names_that_cannot_be_an_app_id_component(repo, bad):
    with pytest.raises(SystemExit):
        apply.main(["--root", str(repo), "--name", bad])


def test_whole_words_only_so_longer_names_are_not_rewritten(tmp_path):
    (tmp_path / "a.md").write_text("Feedshot Feedshots FeedshotPro (Feedshot)\n")
    text, count = apply.replace_tokens((tmp_path / "a.md").read_text(), "Feedshot", "Albumfeed")
    assert text == "Albumfeed Feedshots FeedshotPro (Albumfeed)\n"
    assert count == 2


def test_edits_keep_utf8_and_crlf_line_endings(repo):
    (repo / "docs.md").write_bytes("Größe FastFoto Linux\r\nnaïve\r\n".encode())
    git(repo, "add", "docs.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "docs")
    assert apply.main(["--apply", "--root", str(repo)]) == 0
    assert (repo / "docs.md").read_bytes() == "Größe Feedshot\r\nnaïve\r\n".encode()


def test_tracked_symlinks_are_never_written_through(repo, tmp_path):
    outside = tmp_path.parent / "outside-target.md"
    outside.write_text("FastFoto Linux\n")
    (repo / "link.md").symlink_to(outside)
    git(repo, "add", "link.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "link")
    assert apply.main(["--apply", "--root", str(repo)]) == 0
    assert outside.read_text() == "FastFoto Linux\n"


def test_a_move_whose_destination_exists_fails_before_anything_changes(repo, capsys):
    dst = f"packaging/{OLD_ID.replace('FastFotoLinux', 'Feedshot')}.desktop"
    (repo / dst).write_text("taken\n")
    git(repo, "add", dst)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "collision")
    assert apply.main(["--apply", "--root", str(repo)]) == 1
    assert "already exists or is blocked" in capsys.readouterr().err
    assert (repo / f"packaging/{OLD_ID}.desktop").exists()
    assert "FastFoto Linux" in (repo / "README.md").read_text()


def test_a_longer_id_in_a_file_name_is_not_moved_and_a_symlink_is_moved_not_edited(repo, tmp_path):
    longer = f"packaging/{OLD_ID}Extra.desktop"
    (repo / longer).write_text("Icon=x\n")
    (repo / f"packaging/{OLD_ID}.link").symlink_to("README.md")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "more")
    assert apply.main(["--apply", "--root", str(repo)]) == 0
    assert (repo / longer).exists()
    moved = repo / "packaging/io.github.bearyjd.Feedshot.link"
    assert moved.is_symlink() and not (repo / f"packaging/{OLD_ID}.link").exists()


def test_a_destination_under_a_file_is_blocked_before_anything_changes(repo):
    (repo / "pkg").write_text("a file where a folder is needed\n")
    plan = apply.Plan(moves=(("README.md", "pkg/sub/README.md"),), edits=())
    assert apply.blocked_destinations(repo, plan) == ["pkg/sub/README.md"]


def test_two_moves_to_the_same_destination_are_blocked(repo):
    plan = apply.Plan(moves=(("a.md", "x/z.md"), ("b.md", "x/z.md")), edits=())
    assert apply.blocked_destinations(repo, plan) == ["x/z.md"]


def test_the_script_is_executable():
    assert (ROOT / "tools/rename/apply.py").stat().st_mode & 0o111


def test_a_dangling_symlink_at_a_destination_or_ancestor_is_blocked(repo):
    (repo / "gone-dst").symlink_to("missing-target")
    (repo / "gone-dir").symlink_to("missing-dir")
    plan = apply.Plan(moves=(("a.md", "gone-dst"), ("b.md", "gone-dir/x.md")), edits=())
    assert apply.blocked_destinations(repo, plan) == ["gone-dst", "gone-dir/x.md"]
