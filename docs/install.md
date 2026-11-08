# Install

Pick one. Both install for your user only; neither needs `sudo` for the app itself.

## Native install (Fedora and other distributions with PySide6 and Kirigami)

Two things must come from your distribution first.

- **SANE**, with the `epsonds` backend and the `scanimage` command (the `sane-backends` packages
  of your distribution). The app drives the scanner through `scanimage`.
- **Qt**: PySide6 and Kirigami. On Fedora:

  ```sh
  sudo dnf install python3-pyside6 kf6-kirigami
  ```

From a checkout of the repository:

```sh
tools/install-desktop.sh --dry-run     # list what it would do, change nothing
tools/install-desktop.sh               # install; run it again to update
tools/install-desktop.sh --uninstall   # remove only what it installed
```

The installer builds the USB gap shim (it needs `make` and `gcc`), creates a virtual environment
under `~/.local/share/fastfoto-linux/venv`, installs hashed wheels only, adds a menu entry, and
links `fastfoto` and `ffscan` into `~/.local/bin`. Put that folder on your `PATH`.

Without PySide6 and Kirigami, `fastfoto` says what to install and exits with status 3; the
`ffscan` command line needs neither.

### Searchable text (OCR)

OCRmyPDF comes with the app. Tesseract does not. Where Homebrew is installed, run
`brew install tesseract`. On an immutable system without Homebrew, run
`rpm-ostree install tesseract tesseract-osd` and reboot. On classic Fedora, run
`sudo dnf install tesseract tesseract-osd`. The installer prints the right command for your system.

## Flatpak (x86_64 only)

The Flatpak brings its own Qt, Kirigami, the SANE `epsonds` backend, the USB gap shim and OCR
(English and page orientation). It is not on Flathub yet; build it from a checkout. You need
`flatpak`, `flatpak-builder` and the Flathub remote.

```sh
flatpak-builder --user --install-deps-from=flathub --force-clean --repo=repo build-dir \
  packaging/flatpak/io.github.bearyjd.Feedshot.yml
flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo repo \
  fastfoto-linux.flatpak io.github.bearyjd.Feedshot
flatpak --user install fastfoto-linux.flatpak
flatpak run io.github.bearyjd.Feedshot
```

What the sandbox may do: use every device node of the host (`--device=all`, which includes the GPU
and not only the scanner; it is needed because libusb and SANE open `/dev/bus/usb/...` themselves
and do not use the USB portal), use the network (for the command line's `--net HOST` Wi-Fi option), read and write your Pictures
folder, and show windows on Wayland or X11. Other output folders are granted through the desktop
portal. Settings are kept in `~/.var/app/io.github.bearyjd.Feedshot/`.

## Command line only

```sh
uv sync
make -C tools/usb-gap-shim     # the USB shim; needs gcc and make
uv run ffscan devices          # USB scanners, and whether the shim was found
```

If the scanner is not listed, see the [Runbook](RUNBOOK.md).
