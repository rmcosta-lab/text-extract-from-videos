# Validation — Phase 14: Quality & refactoring

### Behavior preserved

- [x] Full `run_sample.py` run matches the Phase 13 baseline exactly:
      740 lines, 28 `[OCR_UNCERTAIN]`, 6 unextractable spans, 3350 missing
      lines; `sampling_strategy` still recorded in `metadata_video.json`.
- [x] Oversized crop still fails with the same "crop leaves no image area"
      message (now via the typed exception); negative crop gets typer's
      `min=0` message; inverted window still fails actionably.
- [x] `/api/crop` 422 detail still contains "no image area" (existing test).

### Refactors

- [x] `suggest_crop.py` no longer catches `typer.Exit` and no longer imports
      underscore-private names; web crop errors reuse the CLI message.
- [x] `_apply_crop_view` gone; both endpoints call `apply_crop()`.
- [x] `main()` failure blocks collapsed into `_bail_with_report()`.
- [x] `_combined_confidence` removed; engines share `_assemble_ocr_result()`.
- [x] `CandidateFrameWindow` NamedTuple; `model_copy` for
      `sampling_strategy`; `Field(default_factory=list)`; `_line_boxes`
      explicit narrowing; crop-preview zero-crop wording fixed.

### Technical

- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy` passes.
- [x] `pytest` passes (66 tests, updated exception expectations).
