"""Scanner transport: find the FF-680W (USB first, network fallback) and run scan jobs."""

from fastfoto_linux.scanner.errors import (
    InvalidConfigDirError,
    InvalidHostError,
    InvalidShimPathError,
    NoDocumentsError,
    OutputDirError,
    OutputNotEmptyError,
    ScanCancelledError,
    ScanError,
    ScannerError,
    ScannerNotFoundError,
    ShimMissingError,
)
from fastfoto_linux.scanner.job import (
    MAX_LENGTH_MM,
    SUPPORTED_DPI,
    Mode,
    ScanJob,
    Source,
    build_argv,
    build_env,
)
from fastfoto_linux.scanner.network import (
    sane_net_device_name,
    validate_host,
    write_sane_net_config,
)
from fastfoto_linux.scanner.run import ScanResult, run_scan
from fastfoto_linux.scanner.target import ScanTarget, default_shim_candidates, resolve_target
from fastfoto_linux.scanner.usb import UsbScanner, find_usb_scanners

__all__ = [
    "MAX_LENGTH_MM",
    "SUPPORTED_DPI",
    "InvalidConfigDirError",
    "InvalidHostError",
    "InvalidShimPathError",
    "Mode",
    "NoDocumentsError",
    "OutputDirError",
    "OutputNotEmptyError",
    "ScanCancelledError",
    "ScanError",
    "ScanJob",
    "ScanResult",
    "ScanTarget",
    "ScannerError",
    "ScannerNotFoundError",
    "ShimMissingError",
    "Source",
    "UsbScanner",
    "build_argv",
    "build_env",
    "default_shim_candidates",
    "find_usb_scanners",
    "resolve_target",
    "run_scan",
    "sane_net_device_name",
    "validate_host",
    "write_sane_net_config",
]
