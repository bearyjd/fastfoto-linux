<!-- Generated: 2026-10-17 | Files scanned: 20 | Token estimate: ~850 -->
# Documents pipeline (src/fastfoto_linux/documents/)

Entry: `build.py:build_document(...)` with `DocumentSettings` -> `DocumentResult`; `check_settings` refuses bad input before any work. `analyse.py`, `write.py`, `draft.py` do not exist on main; `build.py` holds the flow.

Per page, per sheet (duplex pair kept together):
1. Load: `loader.py:load_page` -> `LoadedPage` (`inspect_page`, `require_size`); PNG only
2. Trim: `trim.py:trim_page` -> `Trimmed`; backing band `band.py:band_cut`/`EdgeRule`/`backing_mask`; safety check `guard.py:holds_content`; scanner streak `streak.py:streak_pixels`/`with_streak`
3. Blank: `blank.py:is_blank_beside` (duplex back with nothing); marks `marks.py:find_marks` -> `Mark`; staple/punch holes `holes.py:all_are_holes`; skipped when `keep_blank`
4. Encode: `encode.py:encode_page` -> `EncodedPage` (JPEG colour/grey, CCITT G4 bilevel via `bilevel.py:binarise`); modes `modes.py:ColourMode`/`output_mode`
5. Assemble: `pdf.py:assemble_pdf` (img2pdf, no re-encode)
6. OCR: `ocr.py:run_ocr` -> `OcrOutcome` (`OcrMode`, `OcrStatus`, `validate_langs`); failure falls back to plain PDF
   - tools: `ocr_tools.py` (`find_ocrmypdf`, `find_tesseract`, `ocr_missing_parts`, `ocr_environment`); version gates `ocr_version.py` (`ocrmypdf_version`, `accepts_rasterizer`); exit-code text `ocr_codes.py:describe_exit`
7. Publish: `publish.py:publish_pdf` / `require_output_folder` (no overwrite)

Support: `units.py:mm_to_px`; errors `errors.py` (`DocumentError`, `AllPagesBlankError`, `OcrMissingError`, `DocumentCancelledError`, `DocumentSettingsError`, ...). Public names re-exported in `documents/__init__.py`.

## Entry points
- Session: `session/documents.py:run_document_session` (scan -> `build_document` -> settle raw); request `session/request.py:DocumentScanRequest`; result `DocumentSessionResult`, `DocumentRawReason`
- CLI: `cli/cmd_doc.py` (`ffscan doc process|scan`: `run_process`, `run_scan_command`, `process_command`); options `cli/doc_options.py` (`add_document_options`, `add_document_scan_options`, `build_settings`); summaries `cli/doc_summary.py`
- GUI: `gui/docform.py`, `gui/docside.py`, `gui/docreport.py`, `gui/documents.py`
- Design notes: `docs/design/documents.md`
