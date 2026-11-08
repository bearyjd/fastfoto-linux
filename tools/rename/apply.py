#!/usr/bin/env python3
"""Rename the product: display name and Flatpak app ID, in tracked files and file names.

Dry run by default; ``--apply`` writes (and refuses a dirty tree). Only two exact tokens are
replaced, so the import package ``fastfoto_linux``, ``ffscan``, ``ff680w_*`` and descriptive
phrases such as "Epson FastFoto FF-680W" are never touched. A fallback name is one command:

    tools/rename/apply.py --apply --old-name Feedshot --name Albumfeed
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OLD_NAME = "FastFoto Linux"
DEFAULT_NEW_NAME = "Feedshot"
APP_ID_PREFIX = "io.github.bearyjd."
NAME_PATTERN = re.compile(r"[A-Z][A-Za-z0-9]*")

# Never rewritten: planning notes, the lockfile, this tool and its tests (they quote the tokens).
EXCLUDED_PREFIXES = (".omc/", "tools/rename/", "tests/rename/")
EXCLUDED_FILES = ("uv.lock",)
# Historic mentions that must survive any rename, e.g. the README line about the previous name.
PROTECTED_PHRASES = ("formerly {old_name}",)


@dataclass(frozen=True)
class Plan:
    moves: tuple[tuple[str, str], ...]
    edits: tuple[tuple[str, int], ...]


def app_id(name: str) -> str:
    return APP_ID_PREFIX + name.replace(" ", "")


def token_pattern(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])")


def replace_tokens(text: str, old_name: str, new_name: str) -> tuple[str, int]:
    """Replace the app ID, then the display name, leaving protected phrases untouched."""
    masks = {}
    for i, phrase in enumerate(p.format(old_name=old_name) for p in PROTECTED_PHRASES):
        mask = f"\0protected{i}\0"
        masks[mask] = phrase
        text = text.replace(phrase, mask)
    count = 0
    for old, new in ((app_id(old_name), app_id(new_name)), (old_name, new_name)):
        text, n = token_pattern(old).subn(new, text)
        count += n
    for mask, phrase in masks.items():
        text = text.replace(mask, phrase)
    return text, count


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def tracked_files(root: Path) -> list[str]:
    names = git(root, "ls-files", "-z").split("\0")
    return [
        n for n in names if n and not n.startswith(EXCLUDED_PREFIXES) and n not in EXCLUDED_FILES
    ]


def read_text(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (UnicodeDecodeError, OSError):
        return None


def make_plan(root: Path, old_name: str, new_name: str) -> Plan:
    id_pattern, new_id = token_pattern(app_id(old_name)), app_id(new_name)
    files = tracked_files(root)
    moves = tuple((f, id_pattern.sub(new_id, f)) for f in files if id_pattern.search(f))
    renamed = {src: dst for src, dst in moves}
    edits = []
    for name in files:
        if (root / name).is_symlink():
            continue  # a link is moved with its name but its content is never written through
        text = read_text(root / name)
        if text is None:
            continue
        count = replace_tokens(text, old_name, new_name)[1]
        if count:
            edits.append((renamed.get(name, name), count))
    return Plan(moves, tuple(edits))


def blocked_destinations(root: Path, plan: Plan) -> list[str]:
    """Destinations a move cannot reach: taken, duplicated, or under a path that is a file."""
    blocked, seen = [], set()
    for _, dst in plan.moves:
        ancestors = [root / parent for parent in Path(dst).parents if str(parent) != "."]
        # lexists: a dangling symlink is "missing" to exists() but still occupies the name
        under_file = any(
            os.path.lexists(p) and (p.is_symlink() or not p.is_dir()) for p in ancestors
        )
        if os.path.lexists(root / dst) or dst in seen or under_file:
            blocked.append(dst)
        seen.add(dst)
    return blocked


def run_plan(root: Path, plan: Plan, old_name: str, new_name: str) -> None:
    for src, dst in plan.moves:
        (root / dst).parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", src, dst)
    for name, _ in plan.edits:
        path = root / name
        updated = replace_tokens(read_text(path) or "", old_name, new_name)[0]
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(updated)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default=DEFAULT_NEW_NAME, help="new display name (one word)")
    parser.add_argument("--old-name", default=DEFAULT_OLD_NAME, help="name currently in the tree")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args(argv)
    if not NAME_PATTERN.fullmatch(args.name):
        parser.error("--name must be one capitalised alphanumeric word (it forms the app ID)")
    if args.name == args.old_name:
        parser.error("--name equals --old-name")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    plan = make_plan(root, args.old_name, args.name)
    mode = "apply" if args.apply else "dry run"
    print(f"{mode}: {args.old_name!r} -> {args.name!r}")
    for src, dst in plan.moves:
        print(f"  git mv {src} -> {dst}")
    for name, count in plan.edits:
        print(f"  edit {name} ({count} replacement{'s' if count != 1 else ''})")
    if not args.apply:
        print("dry run only; pass --apply to write")
        return 0
    if git(root, "status", "--porcelain").strip():
        print("refusing to run: the working tree is dirty; commit or stash first", file=sys.stderr)
        return 1
    taken = blocked_destinations(root, plan)
    if taken:
        print(
            f"refusing to run: destination already exists or is blocked: {', '.join(taken)}",
            file=sys.stderr,
        )
        return 1
    run_plan(root, plan, args.old_name, args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
