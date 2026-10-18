<!-- Generated: 2026-10-17 | Files scanned: 33 | Token estimate: ~850 -->
<!-- AUTO-GENERATED -->
# Desktop app (src/fastfoto_linux/gui/)

Three layers; only `qt/` imports PySide6 (excluded from the main coverage run, tested in the `gui (fedora)` CI job).

## Plain Python (gui/*.py, no Qt)
- `state.py`: `Mode` (PHOTOS, DOCUMENTS), `State`, `transition`, `can_transition`, `is_busy`, `can_cancel`, `final_state`
- `controller.py:Controller`: page state, folder, banner, scanner check; `set_mode`; owns the two sides
- `worker.py:Worker` (one job thread: `check`, `scan`, `scan_documents`, `process_kept`, `cancel`) reports through `WorkerSink`
- `modes.py`: `ModeSide` protocol, `PhotosSide`, `View`, `WorkerPort`; `docside.py:DocumentsSide`
- Forms/validation: `form.py:ScanForm`, `docform.py:DocumentForm`, `validate_document_form`, `to_document_settings`
- Text/banners: `report.py` (`Banner`, `result_banner`, `error_banner`), `docreport.py`
- Items: `photos.py:PhotoItem`, `documents.py:DocumentItem`; `prefs.py` (load/save forms and mode, JSON in user config); `doctools.py` (Documents-mode seams the tests replace)

## Qt bridge (gui/qt/)
- `app.py:main` (engine, Kirigami check, signal handling, error dialog); `bridge.py:Bridge(QObject)` exposes controller to QML
- `photos_model.py`, `documents_model.py:DocumentsModel`, `documents_view.py:DocumentsView`
- `messages.py`: Qt message filter (`install_message_filter`, `filtering_handler`, `is_known_noise`) drops known harmless Qt warnings, passes the rest through

## QML (gui/qml/)
`Main.qml` (Kirigami.ApplicationWindow, `pageStack.initialPage: ScanPage`) -> `ScanPage.qml`; `ModeSwitch.qml`; `FormPanel.qml` / `DocumentFormPanel.qml`; `ResultsView.qml` / `DocumentsView.qml`; `PhotoCell.qml`.

## State machine
IDLE -> CHECKING -> READY | NO_SCANNER; READY -> SCANNING -> PROCESSING -> DONE; SCANNING|PROCESSING -> CANCELLING -> CANCELLED|DONE; any run may end FAILED. Kept pages of a cancelled/failed scan can go straight to PROCESSING. Table: `state.py:_TRANSITIONS`.

## Photos vs Documents wiring
- `Controller.set_mode` swaps the active side (`PhotosSide` / `DocumentsSide`) and saves the mode; blocked while busy (`ActionBlockedError`).
- The shared folder belongs to the Photos form in both modes.
- `ScanPage.qml` switches panels and results with `bridge.mode === "photos" | "documents"`.
- Documents scans run `Worker.scan_documents` -> `session.run_document_session`; Photos run `Worker.scan` -> `session.run_session`.
<!-- /AUTO-GENERATED -->
