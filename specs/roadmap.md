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

## Future (not scheduled)
- Local vision-language model.
- Optional LLM review pass that flags — but never fabricates — code.
