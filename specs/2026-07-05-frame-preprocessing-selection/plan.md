# Plan — Phase 2: Frame preprocessing & selection

## 1. Crop model & validation

- `CropBox` pydantic model (left, top, right, bottom, all ≥ 0, default 0) built
  from the existing `--crop-*` typer options.
- `apply_crop(image, crop) -> image`: slice the frame; validate against the
  video resolution once, up front — fail clearly if the crop leaves no area.
- No crop flags → identity (whole frame), preserving Phase 1 behavior.

## 2. Preprocessing — `preprocess_frame()`

- Signature: `(image, crop) -> processed grayscale image` (NumPy array).
- Pipeline order: crop → grayscale (`cv2.cvtColor`) → resize/upscale
  (`cv2.resize`, scale factor constant, e.g. 2× with cubic interpolation) →
  threshold (Otsu via `cv2.threshold(..., THRESH_OTSU)`, or
  `cv2.adaptiveThreshold` — pick one as default, keep it a small seam) →
  light sharpen or denoise (`cv2.filter2D` kernel / `fastNlMeansDenoising`)
  only where it measurably helps Tesseract.
- Module-level tunable constants (scale factor, block size, etc.) named and
  grouped, not magic numbers inline.

## 3. Frame selection — `is_frame_blurry()` + SSIM dedup

- `is_frame_blurry(gray_image) -> bool`: `cv2.Laplacian(...).var()` under a
  `BLUR_THRESHOLD` constant. Computed on the cropped grayscale image *before*
  thresholding.
- Near-duplicate check: `skimage.metrics.structural_similarity` between the
  current cropped grayscale frame and the last **accepted** frame (both resized
  small for speed); skip when score > `SSIM_THRESHOLD` constant.
- Order per candidate: blur check first, then SSIM against the last kept frame.
- Track `frames_discarded_blurry` and `frames_discarded_duplicate` counters in
  a small pydantic `SelectionStats` model, logged at the end via `rich`
  (feeds `relatorio_falhas.md` in Phase 5).
- If selection discards *every* sampled frame, fail with a clear message.

## 4. Adaptive sampling — `sample_frames()` step by FPS

- `adaptive_sample_step(fps) -> int`: tiers for ≈30 / ≈60 / ≈120 fps (e.g.
  steps 15 / 30 / 60 — roughly one candidate every 0.5 s regardless of FPS);
  values in between snap to the nearest tier.
- Replace the `FIXED_SAMPLE_STEP` usage in `main()`; keep the constant only if
  it serves as the 30 fps tier base.
- `sampling_strategy` string becomes e.g. `"adaptive_fps=60,step=30"` and flows
  into `metadata_video.json` unchanged in shape.

## 5. Pipeline wiring — `run_ocr()` and `main()`

- `run_ocr()` consumes preprocessed images: for each sampled frame → crop +
  preprocess → blur/SSIM gates → save the **preprocessed** image to
  `frames_usados/` → `engine.recognize()` → `OCRRow`.
- `main()` builds `CropBox` from the typer options, validates it against the
  metadata resolution, and passes it down; `rich` progress preserved.
- Outputs (`write_outputs()`) unchanged — same files, same columns.

## 6. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on one actual video: artifacts produced, sampling strategy
  in `metadata_video.json` reflects the adaptive step, skip counters logged,
  and a run with `--crop-*` flags produces visibly cropped images in
  `frames_usados/`.
- Validate every checkbox in `validation.md`.
