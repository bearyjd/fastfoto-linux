"""A fake ``ocrmypdf`` executable for tests that run a real subprocess.

``install()`` writes a Python script named ``ocrmypdf`` into a directory; put that directory on
PATH and describe what the script does with ``FAKE_OCRMYPDF_SPEC`` (``spec_env()``). The script
takes the two last arguments as input and output file, like the real tool.

Spec keys (all optional): ``mode`` is ``copy`` (the default: output = input), ``mark`` (a copy
with a marker line appended), ``fail`` (exit status 2), ``empty`` (exit 0 with an empty output),
``garbage`` (exit 0 with bytes that are not a PDF), ``no_output`` (exit 0, nothing written),
``short`` (exit 0 with a one-page PDF) or ``hang`` (sleep up to 60 s). ``ignore_sigterm`` makes it
survive SIGTERM, ``child`` starts a grandchild that sleeps, ``chatter`` is text written to stdout
and stderr (stands for recognised text), ``flood`` is a number of bytes written to both (more than a
pipe holds), ``record_to`` is a file that receives argv, its own pid and
the grandchild's.
"""

import json
import stat
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SPEC_ENV = "FAKE_OCRMYPDF_SPEC"
MARKER = b"\n%fake-ocr-text-layer\n"

_SCRIPT = textwrap.dedent(
    """\
    #!{python}
    import json, os, signal, subprocess, sys, time

    spec = json.loads(os.environ["{spec_env}"])
    argv = sys.argv[1:]
    source, target = argv[-2], argv[-1]
    mode = spec.get("mode", "copy")

    if spec.get("ignore_sigterm"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    child = None
    if spec.get("child"):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    if spec.get("record_to"):
        record = {{"argv": argv, "pid": os.getpid(), "child": child.pid if child else None}}
        open(spec["record_to"], "w").write(json.dumps(record))
    if spec.get("chatter"):
        sys.stdout.write(spec["chatter"] + "\\n")
        sys.stderr.write(spec["chatter"] + "\\n")
        sys.stdout.flush()
        sys.stderr.flush()

    if spec.get("flood"):
        for stream in (sys.stdout, sys.stderr):
            stream.write("x" * spec["flood"])
            stream.flush()

    data = open(source, "rb").read()
    if mode == "hang":
        end = time.monotonic() + 60
        while time.monotonic() < end:
            time.sleep(0.05)
    elif mode == "fail":
        sys.exit(2)
    elif mode == "no_output":
        pass
    elif mode == "empty":
        open(target, "wb").write(b"")
    elif mode == "garbage":
        open(target, "wb").write(b"this is not a pdf" * 10)
    elif mode == "short":
        open(target, "wb").write(bytes.fromhex(spec["short_pdf_hex"]))
    elif mode == "mark":
        open(target, "wb").write(data + {marker!r})
    else:
        open(target, "wb").write(data)
    """
)


def install(directory: Path) -> Path:
    """Write the fake ``ocrmypdf`` into ``directory`` and make it executable."""
    script = directory / "ocrmypdf"
    script.write_text(
        _SCRIPT.format(python=sys.executable, spec_env=SPEC_ENV, marker=MARKER), encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def spec_env(**spec: Any) -> dict[str, str]:
    """The environment variable that tells the fake what to do."""
    return {SPEC_ENV: json.dumps(spec)}


def put_on_path(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the fake and make it the only thing on PATH; returns the script."""
    directory.mkdir(parents=True, exist_ok=True)
    script = install(directory)
    monkeypatch.setenv("PATH", str(directory))
    return script


def configure(monkeypatch: pytest.MonkeyPatch, **spec: Any) -> None:
    """Tell the fake what to do in this test."""
    for key, value in spec_env(**spec).items():
        monkeypatch.setenv(key, value)


def no_ocr_on_path(directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH without any ``ocrmypdf``, even on a machine that has the real one."""
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PATH", str(directory))


def read_record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def process_alive(pid: int) -> bool:
    """True while ``pid`` runs; a zombie that only waits to be reaped counts as gone."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


def wait_until_gone(pid: int, timeout_s: float = 3.0) -> bool:
    """True once ``pid`` is gone; a killed process takes a moment to disappear."""
    deadline = time.monotonic() + timeout_s
    while process_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def when_started(record: Path, action: Callable[[], None], *, timeout_s: float = 30.0) -> None:
    """Run ``action`` in a thread as soon as the fake has started and written its record."""

    def wait_then_act() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                json.loads(record.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):  # not there yet, or half written
                time.sleep(0.02)
                continue
            action()
            return

    threading.Thread(target=wait_then_act, daemon=True).start()
