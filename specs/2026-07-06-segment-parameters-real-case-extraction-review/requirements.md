# Requirements — Phase 8: Segment parameters & real-case extraction review

## Objective

Add explicit extraction segment controls so a run can process only a selected
time range from a video, persist the effective extraction settings for
inspection, and use real-case frames to review extraction quality around editor
captures where line numbers and code text may be OCR'd separately.

The implementation must preserve the project's fidelity-first rule: never
invent code, prefer uncertainty markers or report entries over guessed content,
and keep every output traceable to frames and timestamps.

## Scope

### Included

- Add CLI parameters to select the video start and end time used for extraction.
- Validate the requested segment against the detected video duration when
  duration is available.
- Apply the selected segment to frame sampling so only frames within the
  effective interval are considered.
- Record the effective extraction parameters in a JSON file inside the output
  directory.
- Include crop values and segment timing in the recorded parameters so a run is
  reproducible from output artifacts.
- Use frames from a real case in `frames_usados/` to evaluate extraction-quality
  improvements, especially captures where a line is followed by the code text.
- Keep all existing required outputs:
  `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
  `metadata_video.json`, and `frames_usados/`.

### Excluded

- No new OCR engine backend.
- No network calls, external APIs, or cloud processing.
- No LLM-based reconstruction or correction.
- No change to the core rule that unreadable or uncertain code must be marked
  rather than fabricated.

## Deliverables / Output Artifacts

- Updated `extract_code_from_video.py` CLI with segment start/end options.
- Updated sampling behavior that respects the effective segment bounds.
- A new JSON artifact in the output directory containing the effective
  extraction parameters for the run.
- Existing output artifacts continue to be produced and remain inspectable even
  for empty OCR or partial failure cases where possible.
- Notes, fixtures, or validation evidence from the real-case frame review as
  appropriate for the codebase.

## Decisions

| Decision | Choice | Source |
| --- | --- | --- |
| Scope | Include all Phase 8 roadmap items as-is. | User answer |
| Implementation approach | Decide based on `specs/tech-stack.md` and `specs/mission.md`. | User answer |
| Validation | Standard checks are enough: `ruff`, `mypy`, and a real script run. | User answer |
| CLI framework | Continue using `typer`. | `specs/tech-stack.md` |
| Structured data | Use Pydantic models for extraction parameters and other structured outputs. | `specs/tech-stack.md` |
| Runtime boundary | Run entirely offline with no network calls. | `specs/mission.md`, `specs/tech-stack.md` |
| Fidelity rule | Preserve uncertainty, gaps, and raw OCR evidence; never invent code. | `specs/mission.md`, `README.md` |

## Fidelity & Error-Handling Rules

- Segmenting must not change OCR content or reconstruction behavior outside
  limiting which frames are eligible for processing.
- If the user provides an invalid segment, fail with a clear, actionable
  message rather than silently processing the full video.
- If only one segment bound is provided, use a deterministic default for the
  other bound: start defaults to the beginning of the video, and end defaults to
  the detected video duration when available.
- If duration cannot be detected, the tool must still behave predictably and
  report any limits it could not verify.
- All timestamps written to artifacts must remain traceable to the original
  video timeline.
- Empty OCR, missing dependencies, undetectable FPS, missing video, and
  unwritable output directory behavior must remain clear and inspectable per the
  README.
- Real-case review must evaluate whether extraction quality improved or
  regressed; it must not manually patch or infer missing code.
