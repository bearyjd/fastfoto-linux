"""The generator that turns uv.lock into the Flatpak's offline wheel sources."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.flatpak.helpers import generator

HEX = "ab" * 32


def wheel_entry(filename: str, digit: str = "a") -> dict[str, Any]:
    return {
        "url": f"https://files.example.org/packages/{filename}",
        "hash": f"sha256:{digit * 64}",
        "size": 1,
    }


def package(
    name: str,
    version: str = "1.0",
    *,
    wheels: tuple[dict[str, Any], ...] = (),
    deps: tuple[str, ...] = (),
    dev: tuple[str, ...] = (),
) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "version": version, "wheels": list(wheels)}
    if deps:
        entry["dependencies"] = [{"name": dep} for dep in deps]
    if dev:
        entry["dev-dependencies"] = {"dev": [{"name": dep} for dep in dev]}
    return entry


def lock_of(*packages: dict[str, Any]) -> dict[str, Any]:
    root = package("app", deps=("lib",), dev=("tool",))
    root["source"] = {"editable": "."}
    return {"version": 1, "package": [root, *packages]}


def test_the_newest_glibc_manylinux_wheel_for_cp313_on_x86_64_is_chosen() -> None:
    old = "lib-1.0-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
    new = "lib-1.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    lock = lock_of(
        package("lib", wheels=(wheel_entry(new, "b"), wheel_entry(old, "a"))), package("tool")
    )
    [chosen] = generator().runtime_wheels(lock)
    assert (chosen.name, chosen.filename, chosen.sha256) == ("lib", new, "b" * 64)
    assert chosen.url.endswith(new)


def test_abi3_wheels_count_for_cp313() -> None:
    name = "lib-1.0-cp37-abi3-manylinux_2_28_x86_64.whl"
    [chosen] = generator().runtime_wheels(lock_of(package("lib", wheels=(wheel_entry(name),))))
    assert chosen.filename == name


def test_a_pure_python_wheel_is_taken() -> None:
    name = "lib-1.0-py3-none-any.whl"
    [chosen] = generator().runtime_wheels(lock_of(package("lib", wheels=(wheel_entry(name),))))
    assert chosen.filename == name


@pytest.mark.parametrize(
    "filename",
    [
        "lib-1.0-cp313-cp313-musllinux_1_2_x86_64.whl",
        "lib-1.0-cp313-cp313-manylinux_2_28_aarch64.whl",
        "lib-1.0-cp313-cp313-macosx_11_0_arm64.whl",
        "lib-1.0-cp313-cp313-win_amd64.whl",
        "lib-1.0-cp312-cp312-manylinux_2_28_x86_64.whl",
        "lib-1.0-cp314-cp314-manylinux_2_28_x86_64.whl",
    ],
)
def test_wheels_for_other_platforms_and_pythons_are_never_chosen(filename: str) -> None:
    lock = lock_of(package("lib", wheels=(wheel_entry(filename),)))
    with pytest.raises(generator().WheelSelectionError, match="lib"):
        generator().runtime_wheels(lock)


def test_a_package_that_has_only_a_source_archive_is_an_error_naming_it() -> None:
    lock = lock_of(package("lib"))
    with pytest.raises(generator().WheelSelectionError, match="lib"):
        generator().runtime_wheels(lock)


def test_dependencies_of_dependencies_are_followed_and_the_dev_group_is_not() -> None:
    plain = "-1.0-py3-none-any.whl"
    lock = lock_of(
        package("lib", wheels=(wheel_entry("lib" + plain),), deps=("deep",)),
        package("deep", wheels=(wheel_entry("deep" + plain),)),
        package("tool", wheels=(wheel_entry("tool" + plain),)),
    )
    assert [wheel.name for wheel in generator().runtime_wheels(lock)] == ["deep", "lib"]


def test_the_runtime_module_installs_offline_with_hashes_from_the_desktop_requirements() -> None:
    plain = "lib-1.0-py3-none-any.whl"
    module = generator().runtime_module(lock_of(package("lib", wheels=(wheel_entry(plain, "c"),))))
    assert module["name"] == "python-deps"
    assert module["buildsystem"] == "simple"
    [command] = module["build-commands"]
    for flag in ("--no-index", "--require-hashes", "--no-deps", "--prefix=${FLATPAK_DEST}"):
        assert flag in command
    assert "-r requirements-desktop.txt" in command
    assert module["sources"][0] == {"type": "file", "path": "../requirements-desktop.txt"}
    assert module["sources"][1:] == [
        {"type": "file", "url": f"https://files.example.org/packages/{plain}", "sha256": "c" * 64}
    ]


def test_rendering_is_stable_json_with_a_final_newline() -> None:
    text = generator().render({"b": 1, "a": [1]})
    assert text.endswith("}\n")
    assert json.loads(text) == {"b": 1, "a": [1]}
    assert text == generator().render({"b": 1, "a": [1]})


LOCK_URL = "https://files.example.org/packages/lib-1.0-py3-none-any.whl"
LOCK_TEXT = f"""\
version = 1

[[package]]
name = "app"
version = "0"
source = {{ editable = "." }}
dependencies = [{{ name = "lib" }}]

[[package]]
name = "lib"
version = "1.0"
wheels = [{{ url = "{LOCK_URL}", hash = "sha256:{"a" * 64}", size = 1 }}]
"""


def test_main_writes_the_runtime_module_and_check_agrees_with_what_it_wrote(
    tmp_path: Path,
) -> None:
    lock, out = tmp_path / "uv.lock", tmp_path / "python-deps.json"
    lock.write_text(LOCK_TEXT)
    assert generator().main(["runtime", "--lock", str(lock), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["name"] == "python-deps"
    assert generator().main(["runtime", "--lock", str(lock), "--output", str(out), "--check"]) == 0


def test_check_fails_for_a_stale_or_missing_file_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock, out = tmp_path / "uv.lock", tmp_path / "python-deps.json"
    lock.write_text(LOCK_TEXT)
    arguments = ["runtime", "--lock", str(lock), "--output", str(out), "--check"]
    assert generator().main(arguments) == 1
    assert not out.exists()
    out.write_text("{}\n")
    assert generator().main(arguments) == 1
    assert out.read_text() == "{}\n"
    assert "out of date" in capsys.readouterr().err


def test_a_lock_that_cannot_be_satisfied_exits_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(LOCK_TEXT.replace('{ name = "lib" }', '{ name = "gone" }'))
    code = generator().main(["runtime", "--lock", str(lock), "--output", str(tmp_path / "x.json")])
    assert code == 1
    assert "gone" in capsys.readouterr().err


REQUIREMENTS = f"""\
hatchling==1.2.3 \\
    --hash=sha256:{"1" * 64} \\
    --hash=sha256:{"2" * 64}
pathspec==4.5 \\
    --hash=sha256:{"3" * 64} \\
    --hash=sha256:{"4" * 64}
"""


def releases(name: str, version: str) -> list[dict[str, str]]:
    sdist = {
        "filename": f"{name}-{version}.tar.gz",
        "url": "https://f.example/s",
        "sha256": "2" * 64,
    }
    wheel = {
        "filename": f"{name}-{version}-py3-none-any.whl",
        "url": f"https://f.example/{name}",
        "sha256": "1" * 64 if name == "hatchling" else "3" * 64,
    }
    return [sdist, wheel]


def test_build_wheels_are_the_pure_python_wheels_whose_hash_the_requirements_list() -> None:
    wheels = generator().build_wheels(REQUIREMENTS, releases)
    assert [(w.name, w.version, w.sha256) for w in wheels] == [
        ("hatchling", "1.2.3", "1" * 64),
        ("pathspec", "4.5", "3" * 64),
    ]


def test_a_wheel_whose_hash_the_requirements_do_not_list_is_refused() -> None:
    def unlisted(name: str, version: str) -> list[dict[str, str]]:
        return [
            {"filename": f"{name}-{version}-py3-none-any.whl", "url": "u", "sha256": HEX},
        ]

    with pytest.raises(generator().WheelSelectionError, match="hatchling"):
        generator().build_wheels(REQUIREMENTS, unlisted)


def test_the_build_module_installs_into_a_folder_the_app_does_not_ship() -> None:
    module = generator().build_module(generator().build_wheels(REQUIREMENTS, releases))
    assert module["name"] == "python-build-deps"
    [command] = module["build-commands"]
    assert "--target=${FLATPAK_DEST}/build-backend" in command
    assert "-r requirements-build.txt" in command
    assert "--require-hashes" in command
    assert module["sources"][0] == {"type": "file", "path": "../requirements-build.txt"}
    assert [s["sha256"] for s in module["sources"][1:]] == ["1" * 64, "3" * 64]


def test_main_builds_the_build_module_from_the_requirements(tmp_path: Path) -> None:
    requirements, out = tmp_path / "requirements-build.txt", tmp_path / "python-build-deps.json"
    requirements.write_text(REQUIREMENTS)
    arguments = ["build", "--requirements", str(requirements), "--output", str(out)]
    assert generator().main(arguments, lookup=releases) == 0
    assert json.loads(out.read_text())["name"] == "python-build-deps"
