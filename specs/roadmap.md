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

## Phase 2 — Frame preprocessing & selection
- `preprocess_frame()`: grayscale, resize, adaptive/Otsu threshold, sharpen/denoise.
- `is_frame_blurry()` via Laplacian variance; skip blurry frames.
- SSIM / diff to skip near-duplicate frames.
- Adaptive `sample_step` by detected FPS (30 / 60 / 120).
- `--crop-*` flags wired into preprocessing.

## Phase 3 — Line-number-aware reconstruction
- `parse_code_lines()`: detect and split leading line numbers from content.
- `merge_ocr_results()`: consolidate multiple reads of the same line; pick best
  by confidence, sharpness, frequency; order by line number.
- Emit `[OCR_UNCERTAIN]` markers for low-confidence lines. **Never invent code.**

## Phase 4 — No-line-number reconstruction
- Reconstruct order by video time.
- Remove scroll-induced duplicates; `rapidfuzz` fuzzy consolidation of repeats.

## Phase 5 — Gap detection & failure report
- `detect_missing_lines()`: flag gaps in numbering with surrounding timestamps.
- `relatorio_falhas.md`: video summary, detected FPS, frames analyzed, frames
  discarded (low sharpness), lines extracted, missing lines, low-confidence
  passages, unextractable sections, and capture recommendations.

## Phase 6 — Robustness & polish
- Handle all named error cases with clear messages (missing `ffprobe`/
  `tesseract`, undetectable FPS, empty OCR, permissions).
- `rich` logging/progress throughout.
- Short logic explanation + example command in the README.

## Future (not scheduled)
- PaddleOCR backend behind the existing OCR interface.
- Local vision-language model.
- Optional LLM review pass that flags — but never fabricates — code.
