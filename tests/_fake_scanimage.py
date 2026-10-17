"""A fake ``scanimage`` executable for tests that run a real subprocess.

``install()`` writes a Python script named ``scanimage`` into a directory; ``fake_env()`` builds an
environment whose PATH is only that directory and whose ``FAKE_SCANIMAGE_SPEC`` tells the script
what to do. The script mimics the parts of the real batch mode that the runner relies on: it
writes ``<pattern>.part`` files, renames them when a page is done, and prints "Scanning page N" /
"Scanned page N. (scanner status = S)" on stderr (scanimage.c prints both in batch mode; the runner
only reads the second).

Spec keys (all optional): ``pages`` (int) or ``numbers`` (list of page numbers), ``exit_code``,
``stderr_lines`` (extra lines at the end), ``stderr_hex`` (raw bytes written last),
``page_delay_s``, ``rename_delay_s`` (gap between "Scanned page" and the rename),
``split_lines`` (write the "Scanned page" line in two pieces), ``fail_last_page_status``
(report the last page as failed with this status), ``close_stderr`` (close fd 2 after the pages),
``hang`` (sleep up to 30 s after the pages, or until signalled), ``ignore_sigterm``,
``sigterm_marker`` (file created when SIGTERM arrives, then exit with status 2 like scanimage
does), ``record_to`` (file that receives argv, the FAKE_PROBE variable, whether stdin was at
EOF and whether the script is a session leader), ``grandchild`` (start a process that inherits
stderr and outlives the script; "flood" makes it write to stderr non-stop until the pipe closes),
``unterminated_stderr_bytes`` (write this many bytes, then "END", without a newline),
``early_stderr_lines`` (lines said right after the pages, before ``hang`` and before the exit),
``exit_delay_s`` (sleep this long just before exiting, like scanimage's slow exit path),
``die_by_signal`` (signal number the script sends itself after ``early_stderr_lines``: it dies of
it, as scanimage does from a crash or an outside kill, and its exit status is minus the number),
``page_sources`` (list of PNG files, one per page: the pages are then real PNGs, not ``b"fake"``,
drawn from those files the way the argv asks: RGB for ``--mode Color``, 8-bit grey for
``--mode Gray``, resampled to ``--resolution`` and saved with that resolution; any other mode
makes the script fail like a scanner that does not know it; the page count defaults to the
number of files) and ``no_dpi`` (leave the resolution out of the PNGs, as a scanimage that
writes none would).
"""

import json
import stat
import sys
import textwrap
from pathlib import Path
from typing import Any

SPEC_ENV = "FAKE_SCANIMAGE_SPEC"

_SCRIPT = textwrap.dedent(
    """\
    #!{python}
    import io, json, os, signal, sys, time

    spec = json.loads(os.environ["{spec_env}"])
    argv = sys.argv[1:]
    batch = next((a for a in argv if a.startswith("--batch=")), "--batch=").split("=", 1)[1]
    err = sys.stderr.buffer
    PNG_MODES = {{"Color": "RGB", "Gray": "L"}}


    def value_after(flag):
        return argv[argv.index(flag) + 1]


    def png_page(source):
        from PIL import Image
        mode = value_after("--mode")
        if mode not in PNG_MODES:
            sys.stderr.write("fake scanimage: cannot scan in mode %s\\n" % mode)
            sys.exit(2)
        dpi = int(value_after("--resolution"))
        with Image.open(source) as opened:
            source_dpi = round(opened.info["dpi"][0])
            picture = opened.convert(PNG_MODES[mode])
        if dpi != source_dpi:
            size = tuple(round(side * dpi / source_dpi) for side in picture.size)
            picture = picture.resize(size, Image.Resampling.NEAREST)
        out = io.BytesIO()
        picture.save(out, "PNG", **({{}} if spec.get("no_dpi") else {{"dpi": (dpi, dpi)}}))
        return out.getvalue()


    def say(text):
        err.write(text.encode())
        err.flush()


    if spec.get("record_to"):
        record = {{"argv": argv, "probe": os.environ.get("FAKE_PROBE"),
                   "stdin_eof": sys.stdin.read() == "",
                   "session_leader": os.getsid(0) == os.getpid()}}
        open(spec["record_to"], "w").write(json.dumps(record))

    if spec.get("ignore_sigterm"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    elif spec.get("sigterm_marker"):
        def on_term(signum, frame):
            open(spec["sigterm_marker"], "w").write("terminated")
            os._exit(2)
        signal.signal(signal.SIGTERM, on_term)

    if spec.get("grandchild"):
        import subprocess
        if spec["grandchild"] == "flood":
            code = "import os\\nwhile True: os.write(2, b'x' * 4096)"
        else:
            code = "import time; time.sleep(10)"
        subprocess.Popen(
            [sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )

    sources = spec.get("page_sources", [])
    numbers = spec.get("numbers") or list(range(1, spec.get("pages", len(sources)) + 1))
    for index, n in enumerate(numbers):
        say("Scanning page %d\\n" % n)
        time.sleep(spec.get("page_delay_s", 0))
        part = (batch % n) + ".part"
        is_last = index == len(numbers) - 1
        failed = is_last and spec.get("fail_last_page_status")
        if not failed:
            open(part, "wb").write(png_page(sources[index]) if sources else b"fake")
        status = spec["fail_last_page_status"] if failed else 0
        line = "Scanned page %d. (scanner status = %d)\\n" % (n, status)
        if spec.get("split_lines"):
            say(line[:12])
            time.sleep(0.2)
            say(line[12:])
        else:
            say(line)
        time.sleep(spec.get("rename_delay_s", 0))
        if not failed:
            os.rename(part, batch % n)

    # One write, so that a busy machine cannot stop this process between two of the lines: a pipe
    # write this small is atomic, and the reader gets all the lines or none of them.
    if spec.get("early_stderr_lines"):
        say("".join(text + "\\n" for text in spec["early_stderr_lines"]))
    if spec.get("die_by_signal"):
        os.kill(os.getpid(), spec["die_by_signal"])
        time.sleep(30)
    if spec.get("unterminated_stderr_bytes"):
        err.write(b"x" * spec["unterminated_stderr_bytes"] + b"END")
        err.flush()
    if spec.get("close_stderr"):
        os.close(2)
    if spec.get("hang"):
        time.sleep(30)
    for text in spec.get("stderr_lines", []):
        say(text + "\\n")
    if spec.get("stderr_hex"):
        err.write(bytes.fromhex(spec["stderr_hex"]))
        err.flush()
    time.sleep(spec.get("exit_delay_s", 0))
    sys.exit(spec.get("exit_code", 0))
    """
)


def install(bin_dir: Path, name: str = "scanimage") -> Path:
    """Write the fake executable as ``bin_dir/name`` and return the directory."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    script.write_text(_SCRIPT.format(python=sys.executable, spec_env=SPEC_ENV))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def fake_env(bin_dir: Path, **spec: Any) -> dict[str, str]:
    """Environment for run_scan: PATH is only ``bin_dir`` so the fake is the scanimage found."""
    return {"PATH": str(bin_dir), "LANG": "C", SPEC_ENV: json.dumps(spec)}
