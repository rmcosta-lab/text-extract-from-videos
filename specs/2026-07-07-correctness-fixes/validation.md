# Validation — Phase 15: Correctness fixes

### Near-duplicate outcomes

- [x] A near-duplicate of a blank-OCR accepted frame is recorded unusable
      (`test_run_ocr_duplicate_inherits_empty_neighbor_outcome`).
- [x] A near-duplicate of a text-bearing accepted frame stays usable
      (`test_run_ocr_duplicate_inherits_usable_neighbor_outcome`).

### Low-FPS sampling

- [x] 30/60/120 keep steps 15/30/60; 25/50/240 snap to tiers; 10→5, 23→12,
      1→1 use the half-rate floor (`test_adaptive_sample_step_*`).

### Missing-line report

- [x] A long interior run collapses to one range entry; a 2-line gap stays
      itemized; the leading-run collapse still works
      (`test_missing_line_entries_*`).

### Sub-frame window

- [x] A valid window between two frame timestamps raises
      `InvalidExtractionParameterError`
      (`test_read_sampled_frames_rejects_a_subframe_window`).

### Behavior preserved

- [x] Full tesseract run: same 740 lines, 3350 missing, 28 `[OCR_UNCERTAIN]`,
      6 unextractable spans (identical to baseline); `relatorio_falhas.md` now
      renders those 3350 as 17 range + 83 individual entries (was ~3341
      individual lines).

### Technical

- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy` passes.
- [x] `pytest` passes (74 tests).
