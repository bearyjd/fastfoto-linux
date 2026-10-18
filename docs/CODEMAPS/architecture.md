<!-- Generated: 2026-10-17 | Files scanned: 122 | Token estimate: ~950 -->
<!-- AUTO-GENERATED -->
# Architecture

```
 ffscan (cli.app:main)            fastfoto (gui.qt.app:main)
   cmd_devices|scan|process|doc|library     Qt/QML -> gui.qt.bridge -> gui.controller
        \                                    /        (worker thread: gui.worker)
         +--------------+-------------------+
                        v
   session/  run_session (photos) | run_document_session (docs)
     scanner.check_scanner -> scanner.run_scan -> raw pages (PNG, temp or .raw/<UTC>/)
                        |
          +-------------+--------------+
          v                            v
   pipeline/process_pages         documents/build_document
   (crop, sides, orient,          (analyse: load, trim, blank,
    enhance/, output/)             encode; write: pdf, ocr, publish)
          v                            v
   album JPEGs (+EXIF/XMP)        searchable PDF in output folder
          \________ session settles raw pages (settle_raw_dir) ________/
```

Scanner path: `scanimage` (SANE epsonds) + preloaded USB gap shim (USB), or SANE net (LAN).
Flatpak (`packaging/flatpak/*.yml`) bundles app, SANE, shim, tesseract. `tools/install-desktop.sh` is the user-level installer (venv + shim + menu entry).

## Modules (src/fastfoto_linux/)
- `scanner/` transport: `target.resolve_target` (USB vs net), `job.ScanJob/build_argv/build_env`, `run.run_scan`, `precheck.check_scanner`, `unstick.ensure_ready`, `libusb`, `usb.find_usb_scanners`, `network`, `shim_trust.select_shim`, `unclean`, `stderr_monitor`, `errors`
- `session/` UI-neutral orchestration: `run.run_session`, `documents.run_document_session`, `scanning` (shared scan/settle), `raw` (raw folder), `request` (`ScanRequest`, `DocumentScanRequest`, `RawPolicy`), `result`
- `pipeline/` photos: `process.process_pages`, `sides` (`iter_photos`, `Photo`, `BackPolicy`), `crop`, `side_order`, `ink`, `io`, `issues`, `unprocessed`, `print_sizes`, `geometry`
- `enhance/` `orient`, `restore`/`restore_cast`, `redeye`, `faces` (YuNet), `fullres`
- `output/` `writer.write_photo/write_unprocessed`, `naming`, `metadata` (EXIF/XMP), `files`, `errors`
- `documents/` PDF pipeline (see documents.md)
- `library/` existing-library tools for `ffscan library`: `plan`, `decide`, `apply`, `jpeg_exif`, `tiff`, `safety`, `confine`, `walk`, `manifest`, `fdio`
- `cli/` `app` (parser, exit codes), `cmd_*`, `options`, `doc_options`, `*_summary`, `errors`
- `gui/` see gui.md; `models/` YuNet ONNX + licence; `imaging.py` shared image helpers
<!-- /AUTO-GENERATED -->
