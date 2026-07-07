# Requirements — Phase 14: Quality & refactoring

## Objective

Apply the deep review's consistency findings with **no behavior change**: the
same inputs produce the same artifacts, CLI messages, and web responses
(verified against the sample video before/after).

## Scope

### Included

- **Typed exceptions at the parameter-validation seams**: new
  `InvalidExtractionParameterError` raised by `_parse_timestamp`,
  `CropBox.validate_against`, and `resolve_extraction_parameters` (pattern
  already set by `InvalidVideoMetadataError`); `main()` translates to a CLI
  exit at the boundary. `suggest_crop.py` stops catching `typer.Exit` and
  fabricating a different message — `_crop_error` now returns the CLI
  message verbatim, and its `main()` catches the typed error from
  `create_app`.
- **Shared names become public**: `_fail` → `fail`, `_require_cv2` →
  `require_cv2`; `suggest_crop.py` imports `MatLike` from
  `extract_code_from_video` instead of duplicating the TYPE_CHECKING shim.
- **Crop reuse**: `_apply_crop_view` deleted; both web endpoints call the
  CLI's `apply_crop()`.
- **`main()` dedup**: the three near-identical failure blocks
  (`FailureReport` + `write_outputs` + `fail`) collapse into one
  `_bail_with_report(...)` helper.
- **Nits**: dead `_combined_confidence` alias removed; both OCR engines share
  `_assemble_ocr_result()` for the sort/aggregate tail (each still computes
  its own mean confidence — word-level for Tesseract, line-level for Paddle,
  exactly as before); crop CLI options become `typer.Option(min=0)` ints
  (dropping the `None`/`or 0` dance and the generic ValidationError catch);
  `_candidate_frame_window` returns a `CandidateFrameWindow` NamedTuple;
  `sampling_strategy` set via `model_copy` instead of post-construction
  mutation; `Field(default_factory=list)` consistency in `suggest_crop.py`;
  `_line_boxes` drops its mypy-appeasing asserts for explicit narrowing;
  crop-preview zero-crop notice says "em nenhum frame amostrado".

### Excluded

- Splitting the monolith into a package (optional follow-up; the spec locks
  the entrypoint, not the file layout — do only if requested).
- Removing `TextGeometry.text_right` or splitting a `resolve_segment_window`
  seam (low value relative to churn).
