"""Build a fake ``/sys/bus/usb/devices`` tree for scanner discovery tests."""

from pathlib import Path

# keyword -> sysfs attribute file; the default value describes a plugged-in FF-680W
DEFAULT_ATTRIBUTES = {
    "vendor": "04b8",
    "product": "016b",
    "busnum": "1",
    "devnum": "2",
}
ATTRIBUTE_FILES = {
    "vendor": "idVendor",
    "product": "idProduct",
    "busnum": "busnum",
    "devnum": "devnum",
}


def add_usb_device(root: Path, name: str, **overrides: str | None) -> Path:
    """Create ``root/name`` with attribute files; an override of ``None`` leaves a file out."""
    unknown = overrides.keys() - DEFAULT_ATTRIBUTES.keys()
    if unknown:
        raise TypeError(f"unknown sysfs attributes: {sorted(unknown)}")
    entry = root / name
    entry.mkdir(parents=True)
    for key, value in {**DEFAULT_ATTRIBUTES, **overrides}.items():
        if value is not None:
            (entry / ATTRIBUTE_FILES[key]).write_text(f"{value}\n")
    return entry
