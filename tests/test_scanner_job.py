import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from fastfoto_linux.scanner.job import (
    MAX_LENGTH_MM,
    SUPPORTED_DPI,
    Mode,
    ScanJob,
    Source,
    build_argv,
    build_env,
)

DEVICE = "epsonds:libusb:001:002"
SHIM = Path("/opt/shim/ff680w_usb_gap.so")


def make_job(tmp_path: Path, **overrides: object) -> ScanJob:
    fields: dict[str, object] = {"device": DEVICE, "output_dir": tmp_path / "out"}
    fields.update(overrides)
    return ScanJob(**fields)  # type: ignore[arg-type]


def batch_arg(tmp_path: Path, prefix: str = "page") -> str:
    return f"--batch={tmp_path / 'out'}/{prefix}-%04d.png"


def test_enum_values_are_the_exact_strings_scanimage_expects() -> None:
    assert [s.value for s in Source] == ["ADF Front", "ADF Duplex"]
    assert [m.value for m in Mode] == ["Lineart", "Gray", "Color"]


def test_supported_dpi_and_max_length_match_the_device() -> None:
    assert SUPPORTED_DPI == (50, 75, 100, 150, 200, 240, 300, 360, 400, 600)
    assert MAX_LENGTH_MM == 393.7


def test_job_defaults(tmp_path: Path) -> None:
    job = make_job(tmp_path)

    assert job.source is Source.DUPLEX
    assert job.mode is Mode.COLOR
    assert job.resolution == 600
    assert job.deskew is True
    assert job.max_length_mm == 393.7
    assert job.file_prefix == "page"


def test_job_is_frozen(tmp_path: Path) -> None:
    job = make_job(tmp_path)

    with pytest.raises(FrozenInstanceError):
        job.resolution = 300  # type: ignore[misc]


def test_default_argv_is_an_exact_tuple(tmp_path: Path) -> None:
    argv = build_argv(make_job(tmp_path))

    assert argv == (
        "scanimage",
        "-d",
        DEVICE,
        "--source",
        "ADF Duplex",
        "--mode",
        "Color",
        "--resolution",
        "600",
        "-y",
        "393.7",
        "--adf-skew=yes",
        "--format=png",
        batch_arg(tmp_path),
    )
    assert isinstance(argv, tuple)
    assert all(isinstance(item, str) for item in argv)


def test_argv_for_front_gray_300_without_deskew_and_short_length(tmp_path: Path) -> None:
    job = make_job(
        tmp_path,
        source=Source.FRONT,
        mode=Mode.GRAY,
        resolution=300,
        deskew=False,
        max_length_mm=152.5,
        file_prefix="front_scan-2",
    )

    assert build_argv(job) == (
        "scanimage",
        "-d",
        DEVICE,
        "--source",
        "ADF Front",
        "--mode",
        "Gray",
        "--resolution",
        "300",
        "-y",
        "152.5",
        "--adf-skew=no",
        "--format=png",
        batch_arg(tmp_path, "front_scan-2"),
    )


def test_argv_for_lineart_and_whole_number_length(tmp_path: Path) -> None:
    argv = build_argv(make_job(tmp_path, mode=Mode.LINEART, max_length_mm=100.0))

    assert argv[argv.index("--mode") + 1] == "Lineart"
    assert argv[argv.index("-y") + 1] == "100"


def test_argv_uses_the_given_scanimage_executable(tmp_path: Path) -> None:
    argv = build_argv(make_job(tmp_path), scanimage="/usr/bin/scanimage")

    assert argv[0] == "/usr/bin/scanimage"


def test_argv_never_asks_for_the_ignored_adf_crp_option(tmp_path: Path) -> None:
    assert not any("adf-crp" in arg for arg in build_argv(make_job(tmp_path)))


def test_percent_signs_in_the_output_dir_are_escaped_for_scanimages_printf(
    tmp_path: Path,
) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "100%done")

    batch = build_argv(job)[-1]

    assert batch == f"--batch={tmp_path / '100%%done'}/page-%04d.png"
    assert batch.removeprefix("--batch=") % 7 == f"{tmp_path / '100%done'}/page-0007.png"


@pytest.mark.parametrize("dpi", SUPPORTED_DPI)
def test_every_supported_resolution_is_accepted(tmp_path: Path, dpi: int) -> None:
    argv = build_argv(make_job(tmp_path, resolution=dpi))

    assert argv[argv.index("--resolution") + 1] == str(dpi)


@pytest.mark.parametrize("dpi", [0, 1, 72, 599, 601, 1200, -300])
def test_unsupported_resolution_is_rejected(tmp_path: Path, dpi: int) -> None:
    with pytest.raises(ValueError, match="resolution"):
        make_job(tmp_path, resolution=dpi)


@pytest.mark.parametrize("prefix", ["", "a b", "a/b", "../x", "page%d", "päge", "a.b", "new\nline"])
def test_unsafe_file_prefix_is_rejected(tmp_path: Path, prefix: str) -> None:
    with pytest.raises(ValueError, match="file_prefix"):
        make_job(tmp_path, file_prefix=prefix)


@pytest.mark.parametrize("prefix", ["page", "Scan_01", "a-b_c", "X"])
def test_safe_file_prefix_is_accepted(tmp_path: Path, prefix: str) -> None:
    assert make_job(tmp_path, file_prefix=prefix).file_prefix == prefix


@pytest.mark.parametrize("length", [0.0, -1.0, 393.8, 1000.0, math.nan, math.inf])
def test_out_of_range_max_length_is_rejected(tmp_path: Path, length: float) -> None:
    with pytest.raises(ValueError, match="max_length_mm"):
        make_job(tmp_path, max_length_mm=length)


def test_max_length_upper_bound_is_inclusive(tmp_path: Path) -> None:
    assert make_job(tmp_path, max_length_mm=MAX_LENGTH_MM).max_length_mm == 393.7


@pytest.mark.parametrize("device", ["", "   ", "-A", "--batch=x"])
def test_empty_or_option_like_device_is_rejected(tmp_path: Path, device: str) -> None:
    with pytest.raises(ValueError, match="device"):
        make_job(tmp_path, device=device)


def test_unknown_source_and_mode_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ADF Back"):
        make_job(tmp_path, source="ADF Back")
    with pytest.raises(ValueError, match="Mono"):
        make_job(tmp_path, mode="Mono")


def test_output_dir_must_be_a_path(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="output_dir"):
        make_job(tmp_path, output_dir=str(tmp_path))


# --- build_env -----------------------------------------------------------------------------


def test_build_env_without_extras_returns_an_equal_but_new_dict() -> None:
    base = {"PATH": "/usr/bin", "LANG": "C"}

    env = build_env(base)

    assert env == base
    assert env is not base


def test_build_env_accepts_any_mapping_and_never_mutates_the_input() -> None:
    base = MappingProxyType({"LD_PRELOAD": "/x/libfoo.so", "SANE_CONFIG_DIR": "/etc/sane.d"})

    env = build_env(base, shim=SHIM, sane_config_dir=Path("/tmp/cfg"))

    assert dict(base) == {"LD_PRELOAD": "/x/libfoo.so", "SANE_CONFIG_DIR": "/etc/sane.d"}
    env["EXTRA"] = "1"
    assert "EXTRA" not in base


def test_build_env_sets_ld_preload_to_the_shim_when_none_was_set() -> None:
    assert build_env({}, shim=SHIM)["LD_PRELOAD"] == str(SHIM)


def test_build_env_prepends_the_shim_to_an_existing_ld_preload() -> None:
    env = build_env({"LD_PRELOAD": "/x/libfoo.so /y/libbar.so"}, shim=SHIM)

    assert env["LD_PRELOAD"] == f"{SHIM} /x/libfoo.so /y/libbar.so"


def test_build_env_treats_a_blank_ld_preload_as_unset() -> None:
    assert build_env({"LD_PRELOAD": "  "}, shim=SHIM)["LD_PRELOAD"] == str(SHIM)


def test_build_env_does_not_add_the_shim_twice() -> None:
    base = {"LD_PRELOAD": f"/x/libfoo.so {SHIM}"}

    assert build_env(base, shim=SHIM)["LD_PRELOAD"] == base["LD_PRELOAD"]


def test_build_env_leaves_ld_preload_alone_without_a_shim() -> None:
    assert build_env({"LD_PRELOAD": "/x/libfoo.so"})["LD_PRELOAD"] == "/x/libfoo.so"
    assert "LD_PRELOAD" not in build_env({})


@pytest.mark.parametrize("bad", ["/opt/my shim/gap.so", "/opt/a:b/gap.so", "/opt/tab\t/gap.so"])
def test_build_env_rejects_shim_paths_that_ld_preload_would_split(bad: str) -> None:
    with pytest.raises(ValueError, match="LD_PRELOAD"):
        build_env({}, shim=Path(bad))


def test_build_env_sets_sane_config_dir_without_trailing_colon() -> None:
    env = build_env({}, sane_config_dir=Path("/tmp/cfg"))

    assert env["SANE_CONFIG_DIR"] == "/tmp/cfg"


def test_build_env_keeps_an_existing_sane_config_dir_when_none_is_requested() -> None:
    env = build_env({"SANE_CONFIG_DIR": "/etc/sane.d"}, shim=SHIM)

    assert env["SANE_CONFIG_DIR"] == "/etc/sane.d"


def test_build_env_overrides_sane_config_dir_when_one_is_requested() -> None:
    env = build_env({"SANE_CONFIG_DIR": "/etc/sane.d"}, sane_config_dir=Path("/tmp/cfg"))

    assert env["SANE_CONFIG_DIR"] == "/tmp/cfg"


def test_build_env_preserves_unrelated_variables() -> None:
    env = build_env({"PATH": "/usr/bin", "HOME": "/h"}, shim=SHIM, sane_config_dir=Path("/c"))

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/h"
