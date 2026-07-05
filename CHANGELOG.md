# Changelog

## 2026-07-05

- Complete Phase 2 — frame preprocessing & selection: `preprocess_frame()` (crop → grayscale → 2× upscale → Otsu threshold → denoise) feeding OCR the preprocessed image, blur skipping via Laplacian variance (`is_frame_blurry()`), near-duplicate skipping via SSIM against the last accepted frame, FPS-adaptive sampling step (30/60/120 tiers recorded in `metadata_video.json`), and `--crop-*` flags wired in with clear validation errors; add phase spec (`specs/2026-07-05-frame-preprocessing-selection/`).
- Complete Phase 1 — thin vertical slice: end-to-end pipeline from video metadata (`ffprobe` with OpenCV fallback → `metadata_video.json`), fixed-step frame sampling, and whole-frame OCR via a `pytesseract` engine behind an OCR interface, to raw artifacts (`ocr_raw.csv`, naive `codigo_extraido.txt`, `frames_usados/`); add phase spec (`specs/2026-07-05-thin-vertical-slice/`).
- Complete Phase 0 — project skeleton: `typer` CLI (`extract_code_from_video.py`) with `--video`/`--output` and declared crop flags, output directory tree creation, and clear errors for missing video or unwritable output; add `.gitignore` and phase spec (`specs/2026-07-05-project-skeleton/`).
- Align phase/review skills with the Python CLI OCR project scope.
- Initialize project with README, mission, roadmap, and tech stack specifications; add changelog and deep review skills.
- Initial commit.
