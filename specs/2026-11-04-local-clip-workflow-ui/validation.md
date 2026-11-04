# Validation — Phase 18: Local clip workflow UI

Verified on 2026-11-04. Checked items below are supported by the automated
regressions, real local execution, browser checks and source inspection detailed
in the execution record at the end. No paid review call was made.

### Output artifacts

- [x] Example clip receives base output `saida/IMG_5885-explorer/extract` and
  produces `<base>/clip_006__vector_names.py/extract` without duplicate nesting.
- [x] Review receives that extraction directory and writes to sibling `revisao`.
- [x] Output base override and paths with spaces work correctly.
- [x] Extraction preserves raw OCR, requested extension, metadata, parameters,
  CSV, failure report, frames and prepared review manifest/evidence.
- [x] Review preserves original OCR and produces existing review artifacts.
- [x] UI shows resolved paths and existing-output behavior before starting.

### Metadata

- [x] Inventory includes all supported videos directly in the chosen folder,
  excludes non-video files and works without `clips.json`.
- [x] `.py.mp4` infers `py`; supported `md`/`txt` suffixes infer correctly;
  missing/unsupported suffixes show editable `txt` fallback.
- [x] Dropdown override is respected independently for each clip.
- [x] Recorded engine, crop and time parameters match submitted UI settings.

### OCR / fidelity

- [x] UI explicitly selects Paddle for crop and extraction by default; available
  alternatives match each operation's supported engines.
- [x] Extraction includes `--prepare-review` by default.
- [x] Unset start/end times are omitted; explicit start `0` survives; valid partial
  windows work and invalid/out-of-bounds windows are rejected.
- [x] Pasted crop flags populate the intended clip and preserve numeric values.
- [x] Crop preview still supports before/after inspection and editing.
- [x] Existing uncertainty, gaps, evidence and original/revised separation remain.

### Error handling

- [x] Missing, empty or unreadable directories and disappeared clips produce
  useful errors without freezing the interface.
- [x] Invalid crop/time/extension settings are rejected before launching work.
- [x] Pasted shell syntax and unrelated flags cannot execute commands.
- [x] Missing OCR runtime/models, bad metadata, empty OCR and unwritable output
  retain existing error semantics and any failure artifacts.
- [x] Review-only rejects missing manifest/evidence with a per-clip message.
- [x] Failed extraction blocks its dependent review, including when old review
  inputs already exist; other clips can continue.
- [x] Failed processes have failed status rather than a completed indicator;
  credentials never appear in browser payloads or displayed logs.
- [x] Duplicate submissions cannot start competing writes to the same destination.

### Offline (no network)

- [x] Folder discovery, frontend assets, crop and extraction work locally with
  cached models; browser file upload is unnecessary.
- [x] Server binds only to `127.0.0.1` and requires no external frontend assets.
- [x] Optional visual review is identified as the existing paid API operation;
  automatic checks simulate API calls and dry-run validates locally.

### Batch workflow and progress

- [x] Single-clip crop and multi-clip processing selections work independently.
- [x] Extraction-only, review-only and combined modes execute the intended stages.
- [x] Combined review begins only after successful extraction and input validation.
- [x] Review command explicitly uses `--image-detail original --system-certs
  --max-output-tokens 64000` and never receives an OCR engine flag.
- [x] Review model/credential configuration follows existing behavior.
- [x] Queue totals, current clip/stage, pending/running/succeeded/failed/blocked
  states and incremental logs reflect actual execution while UI remains responsive.
- [x] Percentages/counts come from real data; unsupported stages are indeterminate.
- [x] Stage settings remain attached to the correct clip during progress updates.
- [x] Shutdown handles managed subprocesses without leaving orphan processes.

### Technical (ruff, mypy, real script run)

- [x] `uv run ruff check .` passes.
- [x] `uv run mypy` covers new modules and passes.
- [x] Relevant pytest tests and existing CLI regressions pass, including unchanged
  default engines, review options, extension and output paths for direct CLI use.
- [x] Frontend stack decision is documented; if React is used, its type/build
  checks pass and setup/serving instructions are reproducible.
- [x] Real local UI-launched short Paddle extraction succeeds in a dedicated
  validation destination; review dry-run validates its prepared evidence.
- [x] Manual UI check covers folder selection, clip settings, crop preview,
  progress, failures and all three modes using simulated review where needed.
- [x] Actual results and environmental limitations are recorded before completion;
  no paid API comparison is required by this phase.

### Execution record

- `uv run --no-sync ruff check .`: passed.
- `uv run --no-sync ruff format --check`: 119 files already formatted.
- `uv run --no-sync mypy`: passed, 52 source files.
- `uv run --no-sync pytest -m 'not integration and not gpu'
  --basetemp .cache/phase18-regression-3`: **216 passed, 10 deselected**.
  This includes **29 workbench tests** for inference, paths, safe crop parsing,
  explicit defaults, time/crop preflight, original artifact preservation, all
  three queue modes, stale-review blocking, concurrent submission rejection,
  local HTTP access, secret redaction, real child-process shutdown, and review
  artifact generation through the actual review CLI with a mocked API client.
- Existing CLI signature regressions assert Tesseract, `prepare_review=False`,
  `txt`, review `high`, 12,000 tokens and `system_certs=False` remain unchanged.
  Existing OCR/review tests cover fidelity, runtime errors and evidence integrity.
- Browser: loaded `saida/IMG_5885-explorer/clip`, discovered **28 videos**;
  exercised folder browsing, independent selection/settings, `clip_023.mp4`'s
  `txt` fallback and manual `md` override, and preservation of another clip's
  start/end values across selection and progress updates.
- Real UI-launched Paddle extraction of `clip_006__vector_names.py.mp4`, seconds
  **2–4**, initially without crop and then with pasted preview values
  `--crop-left 21 --crop-top 175 --crop-right 0 --crop-bottom 3`: both succeeded,
  **4 frames OCR'd, all with text**. Outputs are isolated under
  `saida/phase18-validation/clip_006__vector_names.py/extract`; original example
  extraction/review directories were not modified.
- The persisted parameters confirm `paddle`, `py`, `prepare_review=true`, the
  selected time window and the pasted crop. Existing metadata, raw OCR, reports,
  original/review frames and manifest were produced by the unchanged CLI.
- Real `review_ocr.py --dry-run` with the requested UI defaults passed against
  those cropped extraction artifacts: 1 block, 122 lines, 4 frames, 803,188 image
  bytes. No model/key or paid request was needed. Actual review artifact writing
  and original OCR preservation were separately verified with the mocked API.
- Real crop preview: Paddle selected on first load, original/cropped images and
  sampled thumbnails loaded (14 images); editing left from 21 to 2 updated the
  displayed crop, restoring the suggestion worked, and the copied flags were
  applied in the subsequent successful extraction. Starting extraction closed
  the managed preview; its URL was removed and closure appeared in the logs.
- Browser submissions for extraction, review-only and combined actions were also
  exercised with intercepted simulated job responses; all preserved the selected
  clip's settings and rendered the appropriate stages. These simulations were
  removed before finishing. HTTP-to-queue-to-review-artifact integration is
  covered independently by the mocked API tests, not by browser interception.
- Desktop and mobile layouts were inspected in screenshots at
  `saida/phase18-validation/workbench-desktop.png` and `workbench-mobile.png`.
  The 390px viewport had no horizontal overflow. Visible labels, keyboard focus,
  local assets, actual stage counts and indeterminate running states were checked.
- Cached Paddle models were reused; the existing engine disables model-source
  connectivity checks for cached runs. The workbench adds no remote assets or OCR
  network calls. Only optional review retains the documented API behavior.
- Environment notes: the sandbox initially denied starting installed `ffprobe`;
  the real local server was rerun with approved elevated execution and succeeded.
  `UV_CACHE_DIR` was set to `.cache/uv-phase18` because the global uv cache was
  inaccessible. `--no-sync` reused the existing configured environment.
- Tooling fixes: exclude generated `.cache` contents from Ruff discovery; remove
  an obsolete `frames_kept` constructor argument from an existing test (it is a
  computed property). Neither change modifies production CLI behavior.

No implementation acceptance check remains blocked. User review of the overall
workflow is recommended before `/finish-phase`; it is not a substitute for any
of the checks above. The roadmap phase remains open pending that finish workflow.
