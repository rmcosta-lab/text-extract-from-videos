# Plan — Phase 18: Local clip workflow UI

## 1. Architecture and compatibility baseline

- Inspect extraction CLI, crop-preview app, review planning and configuration
  loading; record supported engines, extensions, output nesting and defaults.
- Assess UI state complexity (inventory, per-clip forms, queue and live logs).
  Prefer existing vanilla JS; adopt React only with a documented benefit, updating
  tech-stack/build instructions if chosen, as authorized by the user.
- Define a separate launcher and focused modules for settings/path resolution,
  command construction, queue execution and HTTP endpoints. Keep pipeline code
  shared and unchanged; add new Python modules to mypy's checked paths.

## 2. Folder inventory and typed settings

- Implement local folder browsing and editable path with clear access errors;
  list supported video files directly in the folder without needing a manifest.
- Define Pydantic models for clips, selected actions, crop/time settings, output
  extension, resolved paths and per-stage job status.
- Implement source suffix inference and `txt` fallback with supported overrides.
- Resolve `<project>/clip` to `<project>/extract`, preserve the full video stem,
  and resolve review to the extraction directory's sibling `revisao`.
- Support an explicit base output override and show all final paths in the UI.

## 3. Crop suggestion and command adapters

- Integrate the existing crop preview as a managed local operation, including
  engine and optional time window. Reuse its before/after and edit capabilities.
- Parse pasted crop flags using an allowlist and existing numeric validation;
  reject malformed, duplicate or unrelated flags rather than executing text.
- Generate structured argument lists using the current Python environment and
  resolved script paths. Support paths with spaces; do not use a shell.
- Explicitly pass `paddle` and `--prepare-review` for UI extraction defaults.
  Omit absent times, preserve `0`, and pass the selected supported extension.
- Pass review defaults and sibling output explicitly; reuse existing model/key
  configuration without exposing credentials. Do not pass an OCR engine to review.

## 4. Background queue and progress

- Implement sequential execution outside the request handler with stable job and
  clip identifiers, separate stage states, logs, exit codes and output locations.
- Support extraction, review, and extraction-then-review actions. Validate prepared
  evidence for review-only and again after a successful combined extraction.
- On extraction failure, block dependent review even if stale artifacts exist;
  continue other queued clips and retain all independent results.
- Stream subprocess output or expose incremental polling. Use actual counters
  where available and indeterminate activity otherwise; keep log storage bounded.
- Avoid duplicate submissions or simultaneous jobs writing the same destination.
  Define launcher shutdown behavior so managed processes do not remain orphaned.

## 5. Frontend workflow and documentation

- Build folder selection, inventory, single/multi-selection and per-clip forms.
- Add crop launch, paste/validation feedback, optional times, engine selectors,
  extension inference/override and resolved output preview.
- Add the three actions, queue overview, current stage, live logs, actionable
  failures and artifact locations. Clearly identify optional paid visual review.
- Keep configuration and progress readable during long runs; retain selection
  and per-clip settings when ordinary progress updates arrive.
- Document launch/setup, conventional paths, existing-output behavior and the
  distinction between UI and CLI defaults, including review prerequisites.

## 6. Verification

- Test meaningful path, inference, argument and validation cases from
  `validation.md`; exercise the queue with fake processes and mocked review calls.
- Run existing CLI regression tests to verify unchanged defaults/artifact contracts.
- Run `uv run ruff check .`, `uv run mypy` and relevant pytest suites. If React is
  adopted, also run its documented type/build checks.
- Perform a real short local Paddle extraction through the UI into a dedicated
  validation output directory and validate prepared review inputs via dry-run.
- Manually verify folder selection, crop preview, batch progress and failures;
  validate all three action paths with simulated review calls, not paid requests.
- Record outcomes and environmental limitations; do not mark unmet checks passed.
