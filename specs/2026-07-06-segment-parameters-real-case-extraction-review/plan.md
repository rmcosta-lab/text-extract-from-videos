# Plan — Phase 8: Segment parameters & real-case extraction review

1. CLI and parameter model

- Add `--start-time` and `--end-time` options to the Typer CLI.
- Support a clear timestamp input format, with validation errors that explain
  the accepted forms.
- Introduce a Pydantic model for requested and effective extraction parameters.
- Include crop settings, segment bounds, and any derived defaults in the model.
- update exemple in Readme

2. Segment validation

- Resolve omitted bounds deterministically: start at `0`, end at detected
  duration when available.
- Validate that start is non-negative and end, when present, is greater than
  start.
- Validate segment bounds against video duration when metadata provides a
  usable duration.
- Produce clear errors for impossible segments without hiding existing metadata
  or dependency errors.

3. Sampling integration

- Thread the effective extraction parameters through the pipeline without
  hidden global state.
- Update `sample_frames()` so candidate frames begin at the selected start time
  and stop at the selected end time.
- Preserve adaptive sampling by detected FPS inside the selected interval.
- Keep saved frame names, OCR rows, and reports traceable to original frame
  numbers and original video timestamps.

4. Output artifact

- Write an extraction-parameters JSON artifact inside the output directory.
- Keep JSON serialization consistent with existing Pydantic/model output style.
- Ensure the artifact records both user-provided values and effective resolved
  values.
- Make the artifact available even when later OCR or reconstruction steps
  produce empty results where practical.

5. Real-case extraction review

- Inspect representative frames from a real case in `frames_usados/`.
- Focus review on captures where a line number is followed by code text or OCR
  splits gutter and code into adjacent blocks.
- Use the review to adjust parsing, grouping, or confidence handling only when
  the change improves fidelity.
- Preserve raw OCR evidence and uncertainty markers for ambiguous cases.

6. Verification

- Run `ruff` formatting/lint checks.
- Run `mypy`.
- Run the script against a real video or representative local case, including a
  segment-bounded invocation.
- Confirm all expected artifacts are produced:
  `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
  `metadata_video.json`, the extraction-parameters JSON file, and
  `frames_usados/`.
