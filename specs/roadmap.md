# Roadmap

High-level implementation order in **very small phases**. Each phase is a small,
verifiable increment that leaves the tool runnable. Full behavior and
deliverables are defined in [`README.md`](../README.md); fidelity rules come from
[`mission.md`](./mission.md); technology from [`tech-stack.md`](./tech-stack.md).

Phase 1 is a **thin vertical slice**: end-to-end but minimal, proving the whole
pipeline runs before any quality work.

---

## ~~Phase 0 — Project skeleton~~ ✅
- ~~`.venv` + dependency install per README.~~
- ~~`extract_code_from_video.py` with a `typer` CLI exposing `--video` and
  `--output` (crop flags declared, may be unused for now).~~
- ~~Creates the output directory tree; fails clearly if the video is missing or
  the output dir is unwritable.~~

## ~~Phase 1 — Thin vertical slice (walking skeleton)~~ ✅
Goal: metadata → sample → OCR → raw dump, end to end. **No** merging, line
reconstruction, or failure report yet.
- ~~`get_video_metadata()` via `ffprobe`, OpenCV fallback → `metadata_video.json`.~~
- ~~`sample_frames()` with a fixed step (adaptive-by-FPS comes later).~~
- ~~Define the **OCR engine interface** and the `pytesseract` implementation;
  `run_ocr()` on the whole frame (or a single hardcoded crop).~~
- ~~Write `ocr_raw.csv` (text, frame, time, confidence, frame image path) and a
  naive concatenated `codigo_extraido.txt`.~~
- ~~Save used frames to `frames_usados/`.~~
- ~~**Exit criterion:** one real video produces all raw artifacts without crashing.~~

## ~~Phase 2 — Frame preprocessing & selection~~ ✅
- ~~`preprocess_frame()`: grayscale, resize, adaptive/Otsu threshold, sharpen/denoise.~~
- ~~`is_frame_blurry()` via Laplacian variance; skip blurry frames.~~
- ~~SSIM / diff to skip near-duplicate frames.~~
- ~~Adaptive `sample_step` by detected FPS (30 / 60 / 120).~~
- ~~`--crop-*` flags wired into preprocessing.~~

## ~~Phase 3 — Line-number-aware reconstruction~~ ✅
- ~~`parse_code_lines()`: detect and split leading line numbers from content.~~
- ~~`merge_ocr_results()`: consolidate multiple reads of the same line; pick best
  by confidence, sharpness, frequency; order by line number.~~
- ~~Emit `[OCR_UNCERTAIN]` markers for low-confidence lines. **Never invent code.**~~

## ~~Phase 4 — No-line-number reconstruction~~ ✅
- ~~Reconstruct order by video time.~~
- ~~Remove scroll-induced duplicates; `rapidfuzz` fuzzy consolidation of repeats.~~

## ~~Phase 5 — Gap detection & failure report~~ ✅
- ~~`detect_missing_lines()`: flag gaps in numbering with surrounding timestamps.~~
- ~~`relatorio_falhas.md`: video summary, detected FPS, frames analyzed, frames
  discarded (low sharpness), lines extracted, missing lines, low-confidence
  passages, unextractable sections, and capture recommendations.~~

## ~~Phase 6 — Robustness & polish~~ ✅
- ~~Handle all named error cases with clear messages (missing `ffprobe`/
  `tesseract`, undetectable FPS, empty OCR, permissions).~~
- ~~`rich` logging/progress throughout.~~
- ~~Short logic explanation + example command in the README.~~

## ~~Phase 7 — Deep-review fidelity fixes~~ ✅
- ~~Preserve code spacing and indentation from OCR instead of rebuilding lines
  with single-space word joins.~~
- ~~Improve line-number reconstruction for real editor captures where gutter
  numbers and code text may be OCR'd as separate blocks/lines.~~
- ~~Keep the CLI usable for `--help` and actionable dependency errors even when
  heavy runtime dependencies like OpenCV are missing.~~
- ~~Broaden line-number parsing to handle common OCR/editor forms such as
  `12:print(...)` or `12|print(...)`.~~
- ~~Ensure `frames_usados/` contains only frames from the current run, avoiding
  stale images from previous executions.~~
- ~~On empty OCR, still write inspectable artifacts such as `ocr_raw.csv`,
  `codigo_extraido.txt`, and `relatorio_falhas.md` before exiting.~~
- ~~Add basic Pydantic constraints for metadata invariants such as positive FPS,
  dimensions, and frame counts.~~
- ~~Clarify the output-writing seam: either `write_outputs()` writes the full
  output tree or it is renamed to reflect the narrower core-output role.~~

## ~~Phase 8 — Segment parameters & real-case extraction review~~ ✅
- ~~Add CLI parameters to select the video start and end time used for extraction.~~
- ~~Record the effective extraction parameters in a JSON file inside the output
  directory.~~
- ~~Use frames from a real case in `frames_usados/` to evaluate extraction-quality
  improvements, especially captures where a line is followed by the code text.~~

## ~~Phase 9 — PaddleOCR backend~~ ✅
Goal: add a second OCR engine behind the existing `OCREngine` seam without
touching the pipeline that consumes it, then prove it on the sample video.
- ~~Add `PaddleOCREngine` implementing `OCREngine.recognize(image) -> OCRResult`,
  with a lazy import and an `OCREngineUnavailableError` mirroring the Tesseract
  path (clear install hint when `paddleocr` is missing).~~
- ~~Map PaddleOCR's per-line boxes and scores into `OCRResult` / `OCRLine` /
  `OCRWord`, preserving geometry so spacing reconstruction and line-number logic
  keep working. **Never invent code**; low scores → `[OCR_UNCERTAIN]` as today.~~
- ~~Add an `--engine {tesseract,paddle}` CLI flag (default `tesseract`) that
  selects the engine at the single instantiation seam; the rest of the pipeline
  still depends only on `OCREngine`.~~
- ~~Record the chosen engine in the extraction-parameters JSON.~~
- ~~**Exit criterion:** `python sample-video/run_sample.py` runs clean on the
  default engine, and the same run with `--engine paddle` produces the full
  `saida/` artifact tree; compare the two outputs to confirm PaddleOCR is a
  drop-in with no pipeline changes. `ruff` and `mypy` pass.~~

## ~~Phase 10 — Crop suggestion preview (web)~~ ✅
Goal: before processing a whole video, automatically suggest crop parameters
that isolate the line-number gutter + code area, and let the user review/tune
them in a small local web page.
- ~~Auto-suggest `--crop-left/-top/-right/-bottom` values for a given video by
  analyzing **frame 30** as the reference frame.~~
- ~~Implement as a **separate script** (own entrypoint), reusing shared pieces by
  importing from `extract_code_from_video.py` (metadata, frame reading,
  preprocessing, OCR engine selection) — no duplication of that logic.~~
- ~~Serve a local web page showing the reference frame **before and after** the
  crop, with the suggested crop values displayed so they are easy to copy into
  the main CLI.~~
- ~~Allow editing the crop values in the page; the backend re-crops frame 30 and
  the page updates with the new preview.~~
- ~~Allow choosing the OCR engine used by the suggestion heuristic
  (`tesseract` default, `paddle` optional) — same engines as the main CLI.~~
- ~~**Exit criterion:** running the tool against `sample-video/IMG_5430.MOV`
  opens the page, shows a sensible auto-suggested crop for frame 30, and
  editing a value refreshes the cropped preview. `ruff` and `mypy` pass.~~

## ~~Phase 11 — Multi-frame crop analysis~~ ✅
Goal: make the crop suggestion in `suggest_crop.py` representative of the
**whole video**, not just frame 30. Code scrolls and line numbers grow wider
(9 → 10 → 100…), so a single reference frame can suggest a crop that cuts
digits off the gutter or clips long code lines later in the video.
- ~~Sample **multiple frames across the video's duration** (reusing the existing
  frame-reading/preprocessing/OCR seams) and run the crop heuristic on each.~~
- ~~Combine the per-frame results into one crop for the entire video:
  - `--crop-left`: conservative enough that **no sampled frame's line-number
    gutter is cut** (take the leftmost detected gutter edge).
  - `--crop-right`: tight enough that **no sampled frame's code text is
    clipped**, while still excluding the noise column (minimap/scrollbar)
    when one is consistently detected.
  - Top/bottom follow the same "never cut detected text" rule across frames.~~
- ~~Keep the honesty rules: frames with empty OCR contribute nothing; if no
  frame yields text, the suggestion stays a zero crop with the explicit
  "no text detected" notice.~~
- ~~The web preview keeps working: show the combined suggestion (and which
  frames informed it), with the same edit/re-crop flow.~~
- ~~**Exit criterion:** against `sample-video/IMG_5430.MOV`, the suggested crop
  keeps every line number fully visible on the left and no code line clipped
  on the right across the sampled frames. `ruff` and `mypy` pass.~~

## ~~Phase 12 — Uncertainty & report honesty (deep-review fixes)~~ ✅
Goal: make the honesty mechanism trustworthy in practice — the July 2026 deep
review of `main` showed a real PaddleOCR run emitting visibly garbled lines with
**zero** `[OCR_UNCERTAIN]` markers and a report claiming zero low-confidence
passages.
- ~~Per-engine uncertainty thresholds (Paddle scores sit at 95+ even for
  garbage; the single Tesseract-calibrated cutoff of 60 never fires) **plus**
  an engine-independent disagreement signal: mark a line uncertain when reads
  of the same line diverge (low winner fuzzy-support share), regardless of
  confidence.~~
- ~~In `_best_read()`, never let empty (gutter-only) reads outvote non-empty
  reads of the same line; a weakly-supported winner is flagged uncertain.~~
- ~~Near-duplicate discards no longer inflate "Trechos impossíveis de
  extrair" — their content was captured by the accepted neighbor frame.~~
- ~~`prepare_output_tree()` clears **all** run-scoped artifacts, not just
  `frames_usados/`, so a mid-run failure cannot leave stale outputs mixed with
  fresh metadata.~~
- ~~Report polish: collapse a leading run of never-shown line numbers into one
  range entry; count reads dropped for having no detectable line number; warn
  actionably when PaddleOCR models are not cached yet (a first run would
  download them from the network — offline promise).~~
- ~~Fix `suggest_crop.py` sampling: an explicit `--start-time 0` must be
  respected (falsy-int `or` bug).~~
- ~~Regenerate `saida/` via `sample-video/run_sample.py` so the local evidence
  matches the committed runner.~~

## ~~Phase 13 — Reproducible tooling & pipeline tests~~ ✅
Goal: the quality gates become reproducible and the fidelity-critical logic
gets a regression net.
- ~~Commit a `pyproject.toml` pinning the ruff ruleset (one that justifies the
  existing `# noqa: PLC0415` markers), formatter settings, mypy strictness,
  and pytest config.~~
- ~~`test_extract_code_from_video.py`: pure-function tests for
  `parse_code_lines()`, `merge_ocr_results()`/`_best_read()` (including the
  Phase 12 behaviors), `reconstruct_by_time()`/`_overlap_length()`,
  `detect_missing_lines()`, `_parse_timestamp()`, `_candidate_frame_window()`,
  `_reconstruct_words()`, `unextractable_sections()` — no video or OCR backend
  needed, following the `FakeEngine` pattern from `test_suggest_crop.py`.~~
- ~~Clean `requirements.txt`: drop unused `tqdm`; note that `pillow` is a
  pytesseract dependency.~~

## ~~Phase 14 — Quality & refactoring~~ ✅
Goal: apply the deep review's consistency findings without behavior changes.
- ~~Library seams raise typed exceptions (pattern already set by
  `InvalidVideoMetadataError`) instead of calling `_fail()`/`typer.Exit`;
  `main()` translates at the CLI boundary; `suggest_crop.py` stops catching
  `typer.Exit` and fabricating a different message.~~
- ~~`suggest_crop.py` imports `apply_crop()` instead of re-implementing it
  (`_apply_crop_view`); names shared across the two entrypoints become public
  (`fail`, `require_cv2`, `console`, `MatLike`).~~
- ~~Collapse the three near-identical failure blocks in `main()` into one
  `_bail_with_report(...)` helper; sweep the remaining low-severity nits
  (dead `_combined_confidence` alias, duplicated OCR-result assembly tails,
  `Field(default_factory=list)` consistency, crop CLI options via
  `typer.Option(min=0)`, `_candidate_frame_window` returning a typed object,
  `sampling_strategy` set without post-construction mutation, crop-preview
  wording).~~

## Future (not scheduled)
- Local vision-language model.
- Optional LLM review pass that flags — but never fabricates — code.
