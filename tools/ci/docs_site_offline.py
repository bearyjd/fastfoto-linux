"""Fail if the built docs site loads anything from another host.

A plain `<a href="https://...">` link is allowed (nothing is fetched until a visitor clicks it).
Everything a browser fetches by itself is not: scripts, stylesheets, fonts, images, frames,
`@import` and `url(...)` in CSS. Usage: python3 tools/ci/docs_site_offline.py SITE_DIR
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

EXTERNAL = re.compile(r"^\s*(?:https?:)?//", re.IGNORECASE)
CSS_EXTERNAL = re.compile(
    r"(?:@import\s+(?:url\()?\s*|url\(\s*)['\"]?\s*((?:https?:)?//[^'\")\s]+)", re.IGNORECASE
)
LOADED_ATTRS = {"src", "href", "data", "poster", "srcset", "action"}
SAFE_LINK_RELS = {"canonical", "alternate", "next", "prev", "author", "license"}


class _Finder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_style = tag == "style"
        values = {name: value or "" for name, value in attrs}
        is_link = tag == "link" and SAFE_LINK_RELS & set(values.get("rel", "").lower().split())
        if tag not in ("a", "area") and not is_link:
            for name, value in values.items():
                if name in LOADED_ATTRS and EXTERNAL.match(value):
                    self.found.append(f"<{tag} {name}={value!r}>")
        if "style" in values:
            self.found.extend(f"<{tag} style: {m}>" for m in CSS_EXTERNAL.findall(values["style"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.found.extend(f"<style>: {m}" for m in CSS_EXTERNAL.findall(data))


def external_references(html: str) -> list[str]:
    finder = _Finder()
    finder.feed(html)
    finder.close()
    return finder.found


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not Path(argv[1]).is_dir():
        print("usage: docs_site_offline.py SITE_DIR", file=sys.stderr)
        return 2
    problems: list[str] = []
    root = Path(argv[1])
    for path in sorted(root.rglob("*")):
        if path.suffix == ".html":
            found = external_references(path.read_text(encoding="utf-8"))
        elif path.suffix == ".css":
            found = CSS_EXTERNAL.findall(path.read_text(encoding="utf-8"))
        else:
            continue
        problems.extend(f"{path.relative_to(root)}: {item}" for item in found)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(problems)} external reference(s) in {root.name}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
