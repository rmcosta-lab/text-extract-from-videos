# Validation — Phase 2: Frame preprocessing & selection

### Output artifacts

- [x] A real script run still creates `metadata_video.json`, `ocr_raw.csv`,
      `codigo_extraido.txt`, and `frames_usados/` under `--output`.
- [x] `frames_usados/` contains the **preprocessed** images actually fed to
      OCR, one per `ocr_raw.csv` row, filenames matching the CSV.
- [x] Skipped frames (blurry / near-duplicate) appear neither in
      `frames_usados/` nor as rows in `ocr_raw.csv`.
- [x] `relatorio_falhas.md` is still NOT produced (deferred to Phase 5).

### Metadata

- [x] `metadata_video.json` records the adaptive sampling strategy, including
      the detected FPS tier and the step used (e.g. `"adaptive_fps=60,step=30"`).
- [x] The step follows the FPS tiers: ≈30 fps → small step, ≈60 fps → medium,
      ≈120 fps → large (verified on at least two different-FPS inputs, real or
      synthetic).

### Preprocessing / crop

- [x] Preprocessing applies crop → grayscale → resize → adaptive/Otsu
      threshold (and sharpen/denoise where wired) in that order; saved frame
      images are grayscale/binarized, not raw color frames.
- [x] With no `--crop-*` flags, the whole frame is processed (Phase 1
      behavior preserved).
- [x] With `--crop-*` flags, saved frame images have the expected reduced
      dimensions and content.
- [x] A crop that leaves no image area (e.g. left+right ≥ width) fails
      clearly before processing, exit code 1.

### Frame selection

- [x] `is_frame_blurry()` uses Laplacian variance against the threshold
      constant; a synthetically blurred frame is skipped and counted.
- [x] Near-duplicate frames (SSIM above threshold vs. the last accepted
      frame) are skipped and counted; a static-screen video yields far fewer
      OCR rows than sampled candidates.
- [x] Discard counters (blurry, duplicate) are logged at the end of the run.

### OCR / fidelity

- [x] OCR is still called only through the `OCREngine` interface; no module
      outside the engine implementation imports `pytesseract`.
- [x] `engine.recognize()` receives the preprocessed image — the same image
      saved to `frames_usados/`.
- [x] No invented content: `codigo_extraido.txt` remains the naive
      concatenation of `ocr_raw.csv` rows; preprocessing/skipping never adds
      or reorders text.

### Error handling

- [x] All Phase 0/1 errors preserved: missing video, unwritable output dir,
      missing `tesseract`, FPS undetectable, zero decoded frames — each still
      a clear error, exit code 1.
- [x] Every sampled frame discarded by selection → clear error (nothing to
      OCR), not silently empty artifacts.

### Offline (no network)

- [x] The run performs no network calls; all processing is local.

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] A real end-to-end run on one actual video completes without crashing,
      with preprocessing, selection, adaptive sampling, and crop all
      exercised at least once across the validation runs.
