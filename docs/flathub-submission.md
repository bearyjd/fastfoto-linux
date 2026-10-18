# Flathub submission checklist

Nothing has been submitted. This page is what the maintainer does by hand, and the text a Flathub
reviewer will want for each permission. Requirements pages:
<https://docs.flathub.org/docs/for-app-authors/requirements> and
<https://docs.flathub.org/docs/for-app-authors/submission>.

## What is ready in this repository

- `packaging/flatpak/flathub/`: the submission root. It holds the manifest, the two generated
  Python module files, the two hashed requirements files they read, and `flathub.json`
  (`only-arches: [x86_64]`). The manifest builds the tagged release from git; the manifest that CI
  builds (`packaging/flatpak/`) uses the local checkout. `tests/flatpak/test_flathub_variant.py`
  keeps the two in step (same sandbox permissions, same modules; only the app and shim sources
  differ).
- Metainfo (`packaging/io.github.bearyjd.FastFotoLinux.metainfo.xml`): licence, OARS content
  rating, release entry, URLs, developer, branding colours, keywords, display requirement.
- Python dependencies are hashed wheels listed as sources (no network at build time).
- The app ID `io.github.bearyjd.FastFotoLinux` is on the code-hosting pattern
  `io.github.<user>.<App>` that Flathub accepts for a repository owned by that user (but see the
  linter finding below).

## Known linter finding: the app ID and the repository name

`flatpak-builder-lint manifest` reports `appid-url-not-reachable`: for an `io.github.<user>.<App>`
ID it opens `https://github.com/<user>/<app>` with the last part lower-cased and without hyphens,
that is `https://github.com/bearyjd/fastfotolinux`, which does not exist (the repository is
`fastfoto-linux`). The maintainer has to choose before submitting: rename the repository to
`fastfotolinux` (GitHub redirects the old name; update the URLs in the metainfo, the manifest and
the README), ask the Flathub reviewers for an exception in the submission PR, or change the app ID
(which renames every file that carries it). Decide this first, because the app ID cannot change
after publication.

## Placeholders to fill (search for `TODO(release)`)

1. Cut the release tag (for example `v0.0.1`, matching `version` in `pyproject.toml` and the
   `<release>` in the metainfo; set the release date to the real day).
2. In `packaging/flatpak/flathub/io.github.bearyjd.FastFotoLinux.yml`, set `tag:` and `commit:` of
   both git sources (`usb-gap-shim` and `fastfoto-linux`) to that tag and
   `git rev-parse <tag>^{commit}`.
3. Take real screenshots of the released app and add a `<screenshots>` block to the metainfo (https
   URLs that resolve; Flathub requires at least one).
4. Re-run the checks below.

## Checks to run before submitting

```sh
flatpak install --user flathub org.flatpak.Builder
appstreamcli validate --pedantic --explain packaging/io.github.bearyjd.FastFotoLinux.metainfo.xml
desktop-file-validate packaging/io.github.bearyjd.FastFotoLinux.desktop
cd packaging/flatpak/flathub
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.bearyjd.FastFotoLinux.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream \
  ../../io.github.bearyjd.FastFotoLinux.metainfo.xml
flatpak run org.flatpak.Builder --user --install-deps-from=flathub --force-clean \
  --repo=repo build-dir io.github.bearyjd.FastFotoLinux.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

## Permissions: what to tell the reviewer

- `--device=all`: scanning is over USB. libusb (and so SANE's `epsonds` backend) opens
  `/dev/bus/usb/BBB/DDD` itself. There is no portal for USB scanners (the USB portal hands out
  devices to an app that asks for one by ID through D-Bus, and SANE does not use it), so the
  device nodes must be visible in the sandbox. `--device=all` is the only way to expose them;
  `--device=dri` is not requested because `all` already includes it.
- `LD_PRELOAD` USB gap shim (`FF680W_SHIM=/app/lib/fastfoto-linux/ff680w_usb_gap.so`): the
  FF-680W firmware ignores a command that is sent right after its reply. The shim enforces a small gap
  before a USB write that follows a reply, only for that scanner, and is preloaded only into the `scanimage` child process, by the app.
  It is built from source in the manifest (`tools/usb-gap-shim/`); no prebuilt binary is used.
  The environment variable only names where the shim is; the app sets `LD_PRELOAD` itself.
- `--share=network`: the Wi-Fi fallback (`ffscan scan --net HOST`) connects to the scanner over
  TCP on the local network. Nothing else uses the network; there is no telemetry or update check.
- `--filesystem=xdg-pictures`: the scanned photos and PDFs are written to a folder the user types or
  picks under Pictures. The portal's folder picker also works for any other folder, but
  its file system has no file locks, so Pictures is granted for the normal case.
- `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc`: the Qt/Kirigami window.
- `TESSDATA_PREFIX`: points at the English and orientation data the Flatpak ships.
- Trademark: the description says the project is independent and not affiliated with Seiko Epson;
  "Epson FastFoto FF-680W" names the supported hardware only.

## After acceptance

- Flathub creates `github.com/flathub/io.github.bearyjd.FastFotoLinux`; the maintainer gets
  write access to it by accepting the invitation. Later changes are PRs against that repository.
- `x-checker-data` on the two git sources lets the flathub bot (flatpak-external-data-checker)
  open a PR when a newer `vX.Y.Z` tag exists; the tarball and wheel sources have no checker, so
  regenerate the wheel modules (`tools/flatpak/gen_wheel_sources.py`) and copy them into the
  submission root when `uv.lock` changes.
- Each release: bump the version and the metainfo `<release>`, tag it, let the bot (or a PR) move
  `tag:` and `commit:`, and check the build log on the Flathub buildbot.
- Keep the permissions list above in step with the manifest; a new permission needs a reviewer's
  approval again.

## Submitting (by hand)

1. Fork `flathub/flathub` (all branches, not only master).
2. Create a branch from `new-pr`, copy the contents of `packaging/flatpak/flathub/` into the
   branch root, and open a PR against the `new-pr` base branch titled
   `Add io.github.bearyjd.FastFotoLinux`.
3. Answer the review; the bot builds a test build when a maintainer comments `bot, build`.
