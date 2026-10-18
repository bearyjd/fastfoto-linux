<!-- Generated: 2026-10-17 | Files scanned: 28 | Token estimate: ~800 -->
<!-- AUTO-GENERATED -->
# Photo pipeline (src/fastfoto_linux/)

Entry: `pipeline/process.py:process_pages(pages, settings, ...)` with `ProcessSettings` -> `ProcessResult`. One sheet at a time; a bad sheet is recorded, never raised.

Stages in order:
1. Load: `pipeline/io.py:load_frame` (PNG + dpi), `scan_time`
2. Crop/detect: `pipeline/crop.py:detect_photo` -> `Detection`/`Box` (`find_photo_box`), `crop(frame, box)`
3. Sides: `pipeline/sides.py:iter_photos` / `assemble_photos` yield `Photo`; `BackPolicy`; `mirrored_front_box`, `front_needs_correction`
   - front/back choice: `pipeline/side_order.py:decide_sides` -> `SideDecision`; paper score `pipeline/ink.py:paper_score`
   - sheet problems: `pipeline/issues.py:sheet_issue`; failures saved raw via `pipeline/unprocessed.py:save_unprocessed`
4. Orient: `enhance/orient.py:auto_orient` (`decide_orientation`, face-based via `enhance/faces.py:FaceDetector`) when `settings.orienter` is set
5. Restore: `enhance/restore.py:restore_colour` (`RestoreSettings`; cast in `enhance/restore_cast.py`)
6. Red-eye: `enhance/redeye.py:remove_red_eye` (`find_red_eyes`, `apply_fixes`; `enhance/fullres.py:detect_faces_full_res`)
   - stages 5-6 are `settings.enhancers` (built in `cli/options.py:build_settings`); a failing step keeps the original (`process._prepare`)
7. Output: `output/writer.py:write_photo` -> `WrittenFiles`; names `output/naming.py:photo_paths`; EXIF/XMP `output/metadata.py:build_exif/build_xmp`; staging `output/files.py`

## Key constants (all geometry in mm, via `pipeline/geometry.py:mm_to_px`)
- `pipeline/crop.py`: `WORK_DPI`, `TAIL_*`, `BACKGROUND_PRIOR_RGB`, `FOREGROUND_DISTANCE`, `OPEN_KERNEL_MM`
- `pipeline/sides.py`: `FRONT_FROM_BACK_X_OFFSET_MM`, `FRONT_BACK_SIZE_TOLERANCE_MM`
- `pipeline/side_order.py`: `PAPER_TIE_MARGIN`, `BACK_LIKE_PAPER_SCORE`, `TIE_BREAK_RECENT_SHEETS`
- `pipeline/ink.py`: `INK_GREY_BELOW`, `PAPER_MIN_GREY`, `HANDWRITING_*`
- `pipeline/print_sizes.py`: `PRINT_SIZES_INCH`, `SIZE_TOLERANCE_MM`
- `enhance/orient.py`: `CANDIDATE_ROTATIONS`, `CONFIDENCE_FLOOR`; `enhance/faces.py`: `MODEL_FILENAME`, `DEFAULT_SCORE_THRESHOLD`
- `enhance/restore.py`: `MAX_CLIP_PCT`, `MAX_SATURATION_GAIN`; `enhance/redeye.py`: `MIN_FACE_SCORE`, `PUPIL_*`
- `output/writer.py`: `MIN_QUALITY`, `MAX_QUALITY`; `output/metadata.py`: `MAX_NOTES_CHARS`

Errors: `pipeline/batch_errors.py` (`BatchError`, `NoPhotoOnSheetError`, `UnreadablePageError`, `PageResolutionError`).
<!-- /AUTO-GENERATED -->
