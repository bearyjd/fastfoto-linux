import logging
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fastfoto_linux.scanner.errors import (
    InvalidConfigDirError,
    InvalidHostError,
    InvalidShimPathError,
    ScannerError,
    ScannerNotFoundError,
    ShimMissingError,
)
from fastfoto_linux.scanner.target import ScanTarget, default_shim_candidates, resolve_target
from tests._fake_sysfs import add_usb_device

SHIM_NAME = "ff680w_usb_gap.so"


@pytest.fixture
def sysfs(tmp_path: Path) -> Path:
    path = tmp_path / "devices"
    path.mkdir()
    return path


@pytest.fixture
def shim(tmp_path: Path) -> Path:
    path = tmp_path / "libs" / SHIM_NAME
    path.parent.mkdir()
    path.write_bytes(b"")
    return path


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "sane-config"


# --- default_shim_candidates ---------------------------------------------------------------


def test_candidates_are_empty_without_env_or_repo_build(tmp_path: Path) -> None:
    assert default_shim_candidates({}, repo_root=tmp_path) == ()


def test_candidates_start_with_the_ff680w_shim_env_var(tmp_path: Path) -> None:
    env = {"FF680W_SHIM": str(tmp_path / "custom.so"), "HOME": str(tmp_path / "home")}

    candidates = default_shim_candidates(env, repo_root=tmp_path / "repo")

    assert candidates == (
        tmp_path / "custom.so",
        tmp_path / "home" / ".local" / "lib" / "fastfoto-linux" / SHIM_NAME,
    )


def test_candidates_ignore_an_empty_ff680w_shim_value(tmp_path: Path) -> None:
    candidates = default_shim_candidates({"FF680W_SHIM": ""}, repo_root=tmp_path)

    assert candidates == ()


def test_candidates_expand_a_tilde_in_the_env_var(tmp_path: Path) -> None:
    env = {"FF680W_SHIM": "~/shim.so", "HOME": str(tmp_path)}

    assert default_shim_candidates(env, repo_root=tmp_path / "repo")[0] == tmp_path / "shim.so"


def test_candidates_expand_only_the_current_users_tilde(tmp_path: Path) -> None:
    home = str(tmp_path / "alice")
    repo = tmp_path / "repo"

    assert default_shim_candidates({"FF680W_SHIM": "~", "HOME": home}, repo_root=repo)[0] == Path(
        home
    )
    other_user = default_shim_candidates({"FF680W_SHIM": "~bob/x.so", "HOME": home}, repo_root=repo)
    assert other_user[0] == Path("~bob/x.so")


def test_candidates_end_with_the_repo_build_only_when_it_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    built = repo / "tools" / "usb-gap-shim" / SHIM_NAME
    built.parent.mkdir(parents=True)
    env = {"HOME": str(tmp_path / "home")}

    assert default_shim_candidates(env, repo_root=repo) == (
        tmp_path / "home" / ".local" / "lib" / "fastfoto-linux" / SHIM_NAME,
    )

    built.write_bytes(b"")
    assert default_shim_candidates(env, repo_root=repo)[-1] == built


def test_default_repo_root_only_yields_files() -> None:
    assert all(path.is_file() for path in default_shim_candidates({}))


# --- resolve_target: USB paths -------------------------------------------------------------


def test_usb_scanner_with_shim_resolves_to_a_usb_target(sysfs: Path, shim: Path) -> None:
    add_usb_device(sysfs, "1-1", busnum="1", devnum="2")

    target = resolve_target(sysfs_root=sysfs, shim_candidates=[shim])

    assert target == ScanTarget(device="epsonds:libusb:001:002", shim=shim, sane_config_dir=None)


def test_usb_wins_over_a_configured_network_host_and_leaves_config_alone(
    sysfs: Path, shim: Path, config_dir: Path
) -> None:
    add_usb_device(sysfs, "1-1")

    target = resolve_target(
        sysfs_root=sysfs, shim_candidates=[shim], net_host="scanner.local", config_dir=config_dir
    )

    assert target.device.startswith("epsonds:libusb:")
    assert target.sane_config_dir is None
    assert not config_dir.exists()


def test_first_existing_shim_candidate_is_used(sysfs: Path, shim: Path, tmp_path: Path) -> None:
    add_usb_device(sysfs, "1-1")
    missing = tmp_path / "nowhere" / SHIM_NAME
    a_directory = tmp_path / "libs"

    target = resolve_target(sysfs_root=sysfs, shim_candidates=[missing, a_directory, shim])

    assert target.shim == shim


def test_with_two_scanners_the_lowest_bus_and_device_is_used_and_a_warning_logged(
    sysfs: Path, shim: Path, caplog: pytest.LogCaptureFixture
) -> None:
    add_usb_device(sysfs, "2-1", busnum="2", devnum="5")
    add_usb_device(sysfs, "1-1", busnum="1", devnum="9")

    with caplog.at_level(logging.WARNING, logger="fastfoto_linux.scanner.target"):
        target = resolve_target(sysfs_root=sysfs, shim_candidates=[shim])

    assert target.device == "epsonds:libusb:001:009"
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_usb_without_shim_and_without_network_raises_with_the_build_command(
    sysfs: Path, tmp_path: Path
) -> None:
    add_usb_device(sysfs, "1-1")

    with pytest.raises(ShimMissingError, match=r"make -C tools/usb-gap-shim"):
        resolve_target(sysfs_root=sysfs, shim_candidates=[tmp_path / "nope.so"])


def test_shim_missing_error_names_the_places_that_were_searched(
    sysfs: Path, tmp_path: Path
) -> None:
    add_usb_device(sysfs, "1-1")
    searched = tmp_path / "searched-here" / SHIM_NAME

    with pytest.raises(ShimMissingError) as excinfo:
        resolve_target(sysfs_root=sysfs, shim_candidates=[searched])

    assert str(searched) in str(excinfo.value)


def test_usb_without_shim_falls_back_to_the_network_when_a_host_is_given(
    sysfs: Path, tmp_path: Path, config_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    add_usb_device(sysfs, "1-1")

    with caplog.at_level(logging.WARNING, logger="fastfoto_linux.scanner.target"):
        target = resolve_target(
            sysfs_root=sysfs,
            shim_candidates=[tmp_path / "nope.so"],
            net_host="scanner.local",
            config_dir=config_dir,
        )

    assert target == ScanTarget(
        device="epsonds:net:scanner.local", shim=None, sane_config_dir=config_dir
    )
    assert any(record.levelno == logging.WARNING for record in caplog.records)


# --- resolve_target: network and failure paths ---------------------------------------------


def test_no_usb_scanner_uses_the_network_host_and_writes_the_private_config(
    sysfs: Path, config_dir: Path
) -> None:
    add_usb_device(sysfs, "1-1", vendor="1d6b", product="0002")

    target = resolve_target(
        sysfs_root=sysfs, shim_candidates=[], net_host="10.0.0.5", config_dir=config_dir
    )

    assert target == ScanTarget(
        device="epsonds:net:10.0.0.5", shim=None, sane_config_dir=config_dir
    )
    assert (config_dir / "dll.conf").read_text() == "epsonds\n"
    assert (config_dir / "epsonds.conf").read_text() == "net 10.0.0.5\n"


def test_nothing_found_raises_scanner_not_found(sysfs: Path, shim: Path) -> None:
    with pytest.raises(ScannerNotFoundError):
        resolve_target(sysfs_root=sysfs, shim_candidates=[shim])


def test_missing_sysfs_root_and_no_host_raises_scanner_not_found(tmp_path: Path) -> None:
    with pytest.raises(ScannerNotFoundError):
        resolve_target(sysfs_root=tmp_path / "absent", shim_candidates=[])


@pytest.mark.parametrize("host", ["a b", "x\nnet evil", "#", ""])
def test_invalid_network_host_is_rejected_even_when_usb_would_work(
    sysfs: Path, shim: Path, config_dir: Path, host: str
) -> None:
    add_usb_device(sysfs, "1-1")

    with pytest.raises(InvalidHostError):
        resolve_target(
            sysfs_root=sysfs, shim_candidates=[shim], net_host=host, config_dir=config_dir
        )


def test_network_host_without_config_dir_is_a_usage_error(sysfs: Path, shim: Path) -> None:
    add_usb_device(sysfs, "1-1")

    with pytest.raises(ValueError, match="config_dir"):
        resolve_target(sysfs_root=sysfs, shim_candidates=[shim], net_host="scanner.local")


def test_scan_target_is_frozen() -> None:
    target = ScanTarget(device="epsonds:net:scanner.local")

    with pytest.raises(FrozenInstanceError):
        target.device = "other"  # type: ignore[misc]
    assert target.shim is None
    assert target.sane_config_dir is None


# --- review findings: shim path, config dir, ScanTarget.env --------------------------------


@pytest.mark.parametrize("directory", ["with space", "with:colon", "with\ttab"])
def test_usb_shim_path_that_ld_preload_cannot_hold_is_a_scanner_error(
    sysfs: Path, tmp_path: Path, directory: str
) -> None:
    add_usb_device(sysfs, "1-1")
    bad_shim = tmp_path / directory / SHIM_NAME
    bad_shim.parent.mkdir()
    bad_shim.write_bytes(b"")

    with pytest.raises(InvalidShimPathError) as excinfo:
        resolve_target(sysfs_root=sysfs, shim_candidates=[bad_shim])

    assert isinstance(excinfo.value, ScannerError)
    assert "LD_PRELOAD" in str(excinfo.value)


def test_config_dir_with_a_colon_is_rejected_up_front_even_when_usb_would_work(
    sysfs: Path, shim: Path, tmp_path: Path
) -> None:
    add_usb_device(sysfs, "1-1")

    with pytest.raises(InvalidConfigDirError):
        resolve_target(
            sysfs_root=sysfs,
            shim_candidates=[shim],
            net_host="scanner.local",
            config_dir=tmp_path / "a:b",
        )


def test_usb_target_env_preloads_the_shim_and_drops_a_stale_network_config(shim: Path) -> None:
    target = ScanTarget(device="epsonds:libusb:001:002", shim=shim)
    base = {"PATH": "/usr/bin", "LD_PRELOAD": "/x/libfoo.so", "SANE_CONFIG_DIR": "/stale"}

    env = target.env(base)

    assert env["LD_PRELOAD"] == f"{shim} /x/libfoo.so"
    assert "SANE_CONFIG_DIR" not in env
    assert env["PATH"] == "/usr/bin"
    assert base == {"PATH": "/usr/bin", "LD_PRELOAD": "/x/libfoo.so", "SANE_CONFIG_DIR": "/stale"}


def test_network_target_env_points_sane_at_the_private_config(config_dir: Path) -> None:
    target = ScanTarget(device="epsonds:net:scanner.local", sane_config_dir=config_dir)

    env = target.env({"PATH": "/usr/bin"})

    assert env == {"PATH": "/usr/bin", "SANE_CONFIG_DIR": str(config_dir)}
