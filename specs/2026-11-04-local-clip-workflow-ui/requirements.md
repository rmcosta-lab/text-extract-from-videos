# Requirements — Phase 18: Local clip workflow UI

## Objective

Make the existing clip-to-code workflow usable through a local frontend while
preserving every existing CLI default, argument, artifact and fidelity rule.
Implement all of [Phase 18](../roadmap.md#phase-18--local-clip-workflow-ui-cli-compatibility-preserved).
The user explicitly selected Phase 18; pending Phase 16 evaluation work remains
outside this phase and is not marked complete.

## Scope

### Included

- A separate UI entrypoint bound to `127.0.0.1`, local folder browsing and an
  editable directory path. Discover all supported video files directly inside
  the selected folder without uploads or a required `clips.json`.
- Clip inventory, single selection for crop suggestion, multi-selection for
  processing, and per-clip settings and execution states.
- Existing `suggest_crop.py` preview/edit workflow, optional start/end times,
  and engine selection defaulting to `paddle` in the UI.
- Pasted crop flags parsed into validated numeric fields, never executed as
  command text. Apply the settings to the intended clip explicitly.
- Optional extraction start/end times per clip, an OCR engine selector defaulting
  to `paddle`, and `--prepare-review` enabled by default in UI-generated commands.
- Infer the code extension after removing the video suffix:
  `clip_006__vector_names.py.mp4` selects `py`. Offer a per-clip dropdown for
  currently supported `txt`, `md`, `py`; unknown/missing suffixes use editable
  `txt` with an explicit indication that inference was unavailable.
- Three batch actions: extraction only, review only, extraction then review.
  Process a sequential queue without blocking the UI. A failed extraction blocks
  only its dependent review; other clips remain independently trackable.
- Actual progress, live logs, current stage, queue totals, errors and output paths.
  Do not fabricate percentages where the underlying operation supplies none.

### Excluded

- Changing CLI defaults or OCR/review algorithms; implementing video segmentation.
- Replacing the current crop heuristic, adding new output formats or OCR engines.
- Remote hosting, video uploads, multi-user operation or parallel GPU processing.
- Durable queue recovery across server restarts, scheduling and paid quality
  comparison experiments. Existing CLI recovery features remain available.

## Deliverables / output artifacts

- Local frontend, typed Python API/orchestration modules and separate launcher;
  usage documentation and tests covering the full workflow.
- Preserve existing extraction artifacts documented in [README](../../README.md),
  including the raw text, requested code extension, metadata, parameters, OCR CSV,
  failure report, frame evidence and prepared review manifest.
- Preserve existing visual review artifacts, raw responses, reviewed code,
  report, diffs and provenance; never modify original OCR to present a review.
- For `saida/IMG_5885-explorer/clip/clip_006__vector_names.py.mp4`, pass extraction
  `--output saida/IMG_5885-explorer/extract`. The existing CLI creates
  `saida/IMG_5885-explorer/extract/clip_006__vector_names.py/extract`.
- Review receives that directory via `--extraction`, and explicit
  `--output saida/IMG_5885-explorer/extract/clip_006__vector_names.py/revisao`.
  The review destination is a sibling of `extract`, not its child.
- Display resolved destinations before execution. Allow a base output override
  for directories outside the conventional `<project>/clip` layout.

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | User selected all Phase 18 requirements. |
| Backend | Python 3.13, FastAPI, uvicorn, Pydantic and existing module seams. |
| Frontend | Start with static HTML and vanilla JS. User permits React if implementation complexity justifies it. Document the assessment before building; if selected, update tech-stack and document build/serving requirements. |
| CLI compatibility | Pass UI defaults explicitly through an adapter; do not change existing command defaults. |
| Engines | `paddle` by default for crop/extraction; expose only engines supported by each operation. Review has no OCR engine flag. |
| Review defaults | Explicit `--image-detail original --system-certs --max-output-tokens 64000`. |
| Review configuration | Reuse existing model, reasoning and credential configuration. Do not expose secrets in browser responses or logs. |
| Network | Folder browsing, crop and extraction stay local with cached models. Visual review retains the existing optional paid OpenAI API workflow, identified in the UI. |
| Execution | Sequential background queue; structured subprocess argument lists, no shell interpolation. |
| Review-only | Use existing prepared extraction; validate manifest and referenced evidence before starting review. |
| Validation | Ruff, mypy, relevant tests, real local script run and manual UI workflow; simulated API calls in automated tests. |

## Fidelity & error-handling rules

Follow [mission](../mission.md), [tech-stack](../tech-stack.md), README and
[review workflow](../../docs/review-workflow.md). The core local-only principle
applies to OCR; optional visual review follows the existing documented API exception.

- Never invent, silently correct or hide uncertain code. Preserve uncertainty
  markers, missing-line reports, original evidence and frame/time provenance.
- Omit unset time flags, preserve an explicit start of `0`, and reuse existing
  timestamp, crop and video-boundary validation.
- Report missing/unreadable/empty directories, missing videos, invalid settings,
  unwritable output paths, missing runtimes/models, undetectable FPS and empty OCR
  actionably. Preserve artifacts written by existing failure paths.
- Validate review prerequisites for each clip. Failed or invalid extraction must
  not cause a review of stale artifacts from a previous run.
- Track pending, running, succeeded, failed and blocked stages independently.
  Report actual exit status and retain useful logs without leaking credentials.
- Existing overwrite behavior must remain visible to users before launching a
  run targeting existing output; do not silently claim an old artifact is new.

Implementation decision: retain vanilla JS. Per-clip form state and periodic job
snapshots do not justify introducing a React/Node build. The local frontend has
no external asset dependencies. See the validation record for browser evidence.
