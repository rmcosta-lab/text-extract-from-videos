# Plan — Phase 15: Correctness fixes

All in `extract_code_from_video.py` unless noted.

1. `run_ocr`: track `last_accepted_usable`; the near-duplicate branch records
   `usable=last_accepted_usable`; set it from each accepted frame's OCR result.
2. `adaptive_sample_step`: `if fps < LOW_FPS_THRESHOLD: return max(1, round(fps/2))`
   else the tier lookup; add `LOW_FPS_THRESHOLD = 24.0`. In `main()` the strategy
   label uses `round(metadata.fps)`.
3. `_metadata_from_opencv`: after the `fps <= 0` guard, add a `total_frames <= 0`
   guard with an ffprobe-install hint.
4. `_missing_line_entries`: rewrite to group `missing` into contiguous runs and
   collapse runs `>= MISSING_RUN_COLLAPSE_MIN` via a new `_collapsed_run_entry`
   (leading → "nunca exibidas"; interior → "entre os tempos …"); add the
   constant.
5. `write_outputs`: reorder so `write_ocr_raw` is last (code + report first).
6. `sample_frames`: read back `CAP_PROP_POS_FRAMES` after the seek and `_warn`
   on mismatch.
7. `suggest_crop.py`: `read_sampled_frames` raises
   `InvalidExtractionParameterError` when `window.expected_candidate_frames == 0`;
   `create_app` reads the HTML template first (raise `ReferenceFrameError` if
   unreadable); `main` probes the port with a socket bind before scheduling the
   browser (needs `import socket`).
8. Tests (`test_extract_code_from_video.py`): `adaptive_sample_step` tiers +
   low-fps floor; `_missing_line_entries` interior-collapse and short-gap
   itemization; `run_ocr` duplicate-inherits-empty / duplicate-inherits-usable
   (synthetic noise frames, `importorskip` cv2/skimage).
   (`test_suggest_crop.py`): sub-frame window raises.
9. Verify: ruff/format/mypy/pytest (74) + a full `run_sample.py` run matching
   the baseline (740 lines, 28 uncertain, 6 spans; report now range-collapsed).
