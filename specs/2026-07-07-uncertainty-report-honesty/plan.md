# Plan — Phase 12: Uncertainty & report honesty

All changes in `extract_code_from_video.py` unless noted.

1. **Constants**: add `OCR_UNCERTAIN_CONFIDENCE_PADDLE = 95.0`,
   `MIN_AGREEMENT_SHARE = 0.5`, `MIN_READS_FOR_AGREEMENT = 3` next to
   `OCR_UNCERTAIN_CONFIDENCE`. Add `uncertain_confidence_for(engine)` near
   `EngineName`.
2. **`_best_read()`**: accept `uncertain_confidence` keyword; pick the winner
   among non-empty reads when any exist; compute fuzzy agreement of the whole
   group with the winner via `_same_line()`; flag uncertain on low/missing
   confidence **or** contested agreement. Thread the keyword through
   `merge_ocr_results()` and `reconstruct_by_time()`; `main()` passes
   `uncertain_confidence_for(engine_name)`.
3. **`run_ocr()`**: near-duplicate discards record `usable=True` (covered by
   the accepted neighbor); update `FrameOutcome`/`unextractable_sections()`
   docstrings and the report span wording.
4. **`prepare_output_tree()`**: also remove the five run artifacts
   (`RUN_ARTIFACT_FILENAMES`) so failures cannot leave stale outputs.
5. **`FailureReport`**: new `reads_without_line_number: int = 0`; `main()`
   fills it on the numbered path; rendered in "Linhas extraídas".
6. **`write_failure_report()`**: new `_missing_line_entries()` collapses the
   leading never-shown run (before is None) into one range entry.
7. **`PaddleOCREngine.__init__`**: `_paddle_models_cached()` heuristic
   (`$PADDLE_PDX_CACHE_HOME` or `~/.paddlex`, `official_models/` non-empty);
   `_warn(...)` when absent.
8. **`suggest_crop.py`**: `sample_frame_indices(start_frame: int | None = None)`
   with an explicit `is None` test; `read_sampled_frames()` passes `None`
   when `window.start_defaulted`.
9. Update the Phase 12 roadmap bullet from "fail actionably" to "warn
   actionably" for missing Paddle models.
10. Regenerate `saida/` locally via `sample-video/run_sample.py` (untracked;
    validation evidence only).
