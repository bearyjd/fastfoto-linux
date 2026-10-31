<!-- Generated: 2026-10-17 | Files scanned: 28 | Token estimate: ~1000 -->
<!-- AUTO-GENERATED -->
# Documents pipeline (src/fastfoto_linux/documents/)

Entry: `build.py:build_document(pages, settings, ...)` = `write_document(analyse_document(...))` -> `DocumentResult`.
- `settings.py`: `DocumentSettings`, `CheckedSettings`, `check_settings` (refuses bad name/langs/missing ocrmypdf before any work)
- `draft.py`: frozen data between the halves: `TrimBox`, `PageAnalysis`, `DocumentDraft` (`kept`, `dropped`), `OutputPart`
- `analyse.py:analyse_document` -> `DocumentDraft`: checks every page file, then per sheet load, trim, judge blank, encode (keeps verdict, trim box, bytes; no pixels)
- `write.py:write_document` -> `DocumentResult`: assemble PDF from the draft, OCR (`_searchable`), publish

Stages inside analyse (per sheet, duplex pair together) and write:
1. Load: `loader.py:load_page` -> `LoadedPage` (`inspect_page`, `require_size`); PNG only
2. Trim: `trim.py:trim_page` -> `Trimmed`; backing band `band.py:band_cut`/`EdgeRule`/`backing_mask`; safety check `guard.py:holds_content`; scanner streak `streak.py:streak_pixels`/`with_streak`
3. Blank: `blank.py:is_blank_beside` (thin wrapper) -> `assess.py:blank_verdict` (`BlankVerdict`, the only blank decision); skipped when `keep_blank`
   - marks `marks.py:find_marks` -> `Mark` (`darkest_channel`, `BLANK_MARGIN_MM`); holes `holes.py:all_are_holes`, `hole_report`
4. Flags (explain, never drop/keep): `assess.py:assess_page` -> `PageAssessment`; `draft.py:Flag`, `BoxN` (mark box), `PageAnalysis.flags/ink/describe()`
   - `bleed.py`: `show_through`, `set_off`, `frame_boxes`; `inkmap.py`: `ink_map` (20 dpi `InkMap`), `hit_rates`, `lies_on`
   - `neighbours.py:with_neighbour_flags`: SET_OFF from neighbouring sheets, once all sheets are analysed
5. Encode: `encode.py:encode_page` -> `EncodedPage` (JPEG colour/grey, CCITT G4 bilevel via `bilevel.py:binarise`); modes `modes.py:ColourMode`/`output_mode`
6. Assemble (write): `pdf.py:assemble_pdf` (img2pdf, no re-encode)
7. OCR (write): `ocr.py:run_ocr` -> `OcrOutcome` (`OcrMode`, `OcrStatus`, `validate_langs`); failure falls back to plain PDF
   - tools: `ocr_tools.py` (`find_ocrmypdf`, `find_tesseract`, `ocr_missing_parts`, `ocr_environment`); version gates `ocr_version.py` (`ocrmypdf_version`, `accepts_rasterizer`); exit-code text `ocr_codes.py:describe_exit`
8. Publish (write): `publish.py:publish_pdf` / `require_output_folder` (no overwrite)

Support: `units.py:mm_to_px`; errors `errors.py` (`DocumentError`, `AllPagesBlankError`, `OcrMissingError`, `DocumentCancelledError`, `DocumentSettingsError`, ...). Public names re-exported in `documents/__init__.py`.

## Entry points
- Session: `session/documents.py:run_document_session` (scan -> `build_document` -> settle raw; `build_document` is injectable); request `session/request.py:DocumentScanRequest`; result `DocumentSessionResult`, `DocumentRawReason`
- CLI: `cli/cmd_doc.py` (`ffscan doc process|scan`: `run_process`, `run_scan_command`, `process_command`); options `cli/doc_options.py` (`add_document_options`, `add_document_scan_options`, `build_settings`); summaries `cli/doc_summary.py`
- GUI: `gui/docform.py`, `gui/docside.py`, `gui/docreport.py`, `gui/documents.py`
- Export presets: `DocumentSettings.preset` (write-time only), `encode.py:encode_page(preset=)`; `docs/design/export-presets.md`
- Design notes: `docs/design/documents.md`
<!-- /AUTO-GENERATED -->
