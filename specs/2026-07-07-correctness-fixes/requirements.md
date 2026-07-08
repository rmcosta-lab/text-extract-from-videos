# Requirements — Phase 15: Correctness fixes (deep-review perspective A)

## Objective

Close the correctness findings from the deep review's bug-hunting perspective
(the one cut off by the session limit and re-run afterward). These fix behavior
on inputs the earlier phases did not exercise; the fidelity contract (never
invent code, honest reporting) is unchanged and the sample run's extracted code
is byte-for-byte identical.

## Scope

### Included

- **Near-duplicate outcome inherits text status** (`run_ocr`,
  `extract_code_from_video.py`): a frame discarded as a near-duplicate is
  recorded `usable` only when the accepted neighbor it duplicates actually
  yielded text. A duplicate of a blank-OCR frame is still unextractable — the
  Phase 12 fix over-corrected by marking every duplicate usable, under-reporting
  spans over static unreadable regions.
- **Low-FPS sampling** (`adaptive_sample_step`): below `LOW_FPS_THRESHOLD`
  (24 fps) the step is `round(fps / 2)` instead of snapping to the 30/60/120
  tiers; the canonical tiers are unchanged. The strategy label reports the real
  detected FPS (`round(metadata.fps)`), not the nearest tier.
- **Missing-line report collapse** (`_missing_line_entries`): any contiguous
  run of at least `MISSING_RUN_COLLAPSE_MIN` (4) absent line numbers — leading
  or interior — renders as one range entry, so a single mid-file gutter misread
  cannot flood `relatorio_falhas.md`. Shorter runs stay itemized. Totals
  unchanged.
- **Sub-frame time window** (`read_sampled_frames`, `suggest_crop.py`): a valid
  window with no frame timestamp inside it raises
  `InvalidExtractionParameterError` instead of silently analyzing a frame
  outside the window.
- **Robustness**:
  - OpenCV fallback with an undetectable frame count fails with a targeted
    "frame count could not be determined … install ffprobe" message instead of
    "may be corrupt".
  - `write_outputs` writes the human-readable code and report *before* the
    pandas-backed CSV, so a missing-pandas failure (or a bail path) still leaves
    the inspectable artifacts and the actionable message.
  - `create_app` reads `crop_preview.html` first and fails fast if it is
    missing, before the slow sampling + OCR pass.
  - `suggest_crop`'s server probes the port (socket bind) before scheduling the
    browser tab, so a busy port yields the actionable "try another --port"
    message instead of uvicorn's bare `SystemExit`.
  - `sample_frames` reads the position back after a seek and warns if the
    decoder landed off the requested frame (keyframe-only seeking), so
    approximate frame numbers are surfaced, not hidden.

### Excluded

- Renumbering frames after an off-target seek (warning only — renumbering would
  destabilize the step/forced-frame alignment).
- Any change to OCR recognition, preprocessing, or the reconstruction winners.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Low-FPS threshold | 24 fps | Below film rate the tiers sample >1 s apart; screen recorders at 30/60/120 keep exact current behavior |
| Missing-run collapse size | 4 | Small gaps (1–3) stay named and useful; wider runs are noise to be summarized |
| Off-target seek | warn, don't renumber | Renumbering risks breaking sampling math; a warning keeps the output honest |
| Sub-frame window | reuse `expected_candidate_frames == 0` | Same condition the extraction CLI bails on; no new math |
