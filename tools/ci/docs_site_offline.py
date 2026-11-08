"""Fail-closed check that the built docs site makes no request to another host.

Usage: python3 tools/ci/docs_site_offline.py SITE_DIR

Every file of the site is read as text. A URL-like string (a scheme such as http:, https:, ws:,
javascript: or data:, or a protocol-relative //host) is a failure wherever it is, after the text is
normalised the way a browser would (character references, CSS escapes, tabs and newlines removed),
EXCEPT in these places:
  * the href of an <a> element (a link is fetched only when a visitor clicks it); javascript: and
    other script-bearing schemes there still fail;
  * the exact namespace names in NAMESPACES (labels, not requests);
  * text between tags outside <script> and <style> (displayed, never fetched);
  * CSS comments (stripped), and data:image/... URLs;
  * search/search_index.json, the page text for the search box, which holds URLs written in prose;
  * the theme's own bundles under assets/javascripts and assets/stylesheets, which are checked
    against the hosts in VENDOR_HOSTS instead (the packages are pinned by hash, see
    packaging/requirements-docs.txt). A new host in a new theme version fails until it is reviewed.
Duplicate src, href or srcset attributes fail (browsers use the first, other tools the last).
"""

import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Labels that are compared with strings, never fetched.
NAMESPACES = (
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1998/Math/MathML",
    "http://www.sitemaps.org/schemas/sitemap/0.9",
)
VENDOR_DIRS = ("assets/javascripts/", "assets/stylesheets/")
# Hosts that appear in the theme's bundles, with why each is harmless. All are in comments or
# strings that no code path of this site reaches, except the three marked "dead code".
VENDOR_HOSTS = {
    "www.w3.org": "SVG namespace",
    "www.mozilla.org": "MPL licence header of a bundled library",
    "developer.mozilla.org": "documentation link in a comment or an error message",
    "github.com": "source and issue links in comments and deprecation messages",
    "api.github.com": "dead code: repository facts, only used when repo_url is set (it is not)",
    "unpkg.com": "dead code: loads mermaid and a polyfill only for pages that use them (none)",
    "${e}": "dead code: GitLab facts, only used when repo_url is set (it is not)",
    "${base}": "dead code: same, in the bundle's source map (read only by browser dev tools)",
    "rxjs.dev": "deprecation links in RxJS error messages",
    "bit.ly": "short links in RxJS comments",
    "t.ly": "short links in RxJS comments",
    "www.npmjs.com": "link in a comment",
    "snowball.tartarus.org": "stemmer licence comment (lunr-languages)",
    "tartarus.org": "stemmer credit comment",
    "code.google.com": "stemmer credit comment",
    "wiki.ecmascript.org": "link in a comment",
    "wiki.commonjs.org": "link in a comment",
    "underscorejs.org": "link in a comment",
    "people.mozilla.org": "link in a comment",
    "lunrjs.com": "link in a comment",
    "clipboardjs.com": "link in a comment",
    "fontawesome.com": "licence comment of the bundled icons",
    "benediktmeurer.de": "link in a comment",
    "chasen.org": "link in a comment (Japanese segmenter of lunr-languages)",
    "docs.python.org": "link in a comment (word segmenter of lunr-languages)",
    "en.wikipedia.org": "link in a comment",
    "msdn.microsoft.com": "link in a comment",
    "narwhaljs.org": "link in a comment",
}
DATA_ONLY = ("search/search_index.json",)
BINARY = {".png", ".gz", ".ico", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}
MARKUP = {".html", ".htm", ".svg", ".xml"}
SCRIPT_SCHEMES = {
    "http",
    "https",
    "ftp",
    "ftps",
    "ws",
    "wss",
    "file",
    "javascript",
    "vbscript",
    "blob",
}
SCHEME = re.compile(r"(?<![\w.+-])([A-Za-z][A-Za-z0-9+.-]*):(//)?([^\s'\"`)<>]*)")
RELATIVE = re.compile(r"""(?:^|['"(=,;\s])(//[^\s/*'")<>][^\s'")<>]*)""")
HOST = re.compile(r"(?:https?|ftps?|wss?)://([^/\s'\"`)<>?#\\]+)", re.IGNORECASE)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_HEX = re.compile(r"\\([0-9a-fA-F]{1,6})[ \t\n\r\f]?")


def normalise(text: str) -> str:
    """The text as a browser would read a URL in it."""
    text = html.unescape(text)
    text = CSS_HEX.sub(lambda m: chr(min(int(m[1], 16), 0x10FFFF)), text)
    text = re.sub(r"\\(.)", r"\1", text, flags=re.DOTALL)
    return re.sub(r"[\t\n\r\x00]", "", text)


def scan_text(text: str, css: bool = False) -> list[str]:
    """The URL-like strings in text that a browser could fetch."""
    for label in NAMESPACES:
        text = re.sub(re.escape(label) + r"(?![\w./~%-])", "", text)
    if css:
        text = CSS_COMMENT.sub("", text)
    found: list[str] = []
    for variant in (text, normalise(text)):
        for m in SCHEME.finditer(variant):
            scheme, slashes, rest = m[1].lower(), m[2], m[3]
            if scheme == "data":
                if not rest.lower().startswith("image/"):
                    found.append(m[0])
            elif scheme in SCRIPT_SCHEMES or slashes:
                found.append(m[0])
        found.extend(m[1] for m in RELATIVE.finditer(variant))
    return sorted(set(found))


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: list[str] = []
        self._raw = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._raw = tag if tag in ("script", "style") else ""
        names = [name for name, _ in attrs]
        for name in ("src", "href", "srcset"):
            if names.count(name) > 1:
                self.found.append(f"<{tag}> repeats {name}=")
        seen: set[str] = set()
        for name, value in attrs:
            if name in seen:
                continue
            seen.add(name)
            hits = scan_text(value or "", css=name == "style")
            if tag == "a" and name == "href":
                hits = [h for h in hits if not re.match(r"(?i)(https?:)?//", h)]
            self.found.extend(f"<{tag} {name}=...> {hit}" for hit in hits)

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag: str) -> None:
        self._raw = ""

    def handle_data(self, data: str) -> None:
        if self._raw:
            self.found.extend(scan_text(data, css=self._raw == "style"))

    def handle_comment(self, data: str) -> None:
        self.found.extend(scan_text(data))

    def handle_decl(self, decl: str) -> None:
        self.found.extend(scan_text(decl))


def scan_vendor(text: str) -> list[str]:
    hosts = {m[1].lower() for variant in (text, normalise(text)) for m in HOST.finditer(variant)}
    return sorted(h for h in hosts if h not in VENDOR_HOSTS)


def scan_file(rel: str, text: str) -> list[str]:
    suffix = Path(rel).suffix
    if rel.startswith(VENDOR_DIRS):
        return scan_vendor(text)
    if suffix in MARKUP:
        page = _Page()
        page.feed(text)
        page.close()
        return page.found
    return scan_text(text, css=suffix == ".css")


def check_site(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or path.suffix in BINARY or rel in DATA_ONLY:
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        problems.extend(f"{rel}: {item}" for item in scan_file(rel, text))
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not Path(argv[1]).is_dir():  # noqa: PLR2004
        print("usage: docs_site_offline.py SITE_DIR", file=sys.stderr)
        return 2
    problems = check_site(Path(argv[1]))
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(problems)} external reference(s) in the built site")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
