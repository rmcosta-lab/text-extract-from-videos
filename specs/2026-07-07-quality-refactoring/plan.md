# Plan — Phase 14: Quality & refactoring

1. Add `InvalidExtractionParameterError`; convert `_invalid_timestamp`,
   `CropBox.validate_against`, and `resolve_extraction_parameters` from
   `fail()` to `raise`; wrap the validate/resolve calls in `main()` with a
   translate-to-`fail` boundary.
2. Rename `_fail` → `fail`, `_require_cv2` → `require_cv2` (cross-module
   names are public API); `suggest_crop.py` imports `MatLike` and
   `apply_crop`, drops `_apply_crop_view` and its TYPE_CHECKING shim, and
   `_crop_error` returns the typed error's message via `_plain()`.
3. Extract `_bail_with_report(...)`; collapse the three failure blocks.
4. Nits: delete `_combined_confidence`; share `_assemble_ocr_result()`
   between engines (per-engine confidence preserved); crop options
   `typer.Option(min=0)`; `CandidateFrameWindow` NamedTuple;
   `sampling_strategy` via `model_copy`; `Field(default_factory=list)`;
   `_line_boxes` explicit narrowing; crop-preview wording.
5. Update tests: `typer.Exit` expectations become
   `InvalidExtractionParameterError` (both suites).
6. Verify: gates plus a full `run_sample.py` run producing identical results
   to the Phase 13 baseline (740 lines, 28 uncertain, 6 spans), and the CLI
   error paths (oversized crop, negative crop, inverted window).
