# Tech Stack

Locked technology decisions for the project. Dependencies are declared in
[`pyproject.toml`](../pyproject.toml), with installation steps in
[`README.md`](../README.md); this document
records the *choices among alternatives* and the *conventions* that bind future
work.

## Language & runtime

- **Python 3.13** in a local virtualenv (`.venv`) managed by **uv**.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
- Tooling is in the `dev` group; NVIDIA OCR is in `paddle-gpu`.
- Runs entirely offline; no network calls at runtime.

## CLI & data modeling

- **CLI framework: `typer`.** (Not argparse.) Single entrypoint
  `extract_code_from_video.py` exposing `--video` and `--output`, plus the crop
  flags `--crop-left/-top/-right/-bottom`.
- **Result models: `pydantic`.** (Not plain dataclasses.) All structured
  results — video metadata, OCR rows, reconstructed lines, report data — are
  pydantic models. This gives validation and clean (de)serialization to the
  JSON/CSV outputs.
- **Type hints everywhere.**

## OCR: pluggable, Tesseract default

OCR is accessed through a **narrow engine interface** (e.g. a `Protocol` /
abstract base with a single `image -> OCR result` method). This is a hard
requirement, not an aspiration.

- **Default implementation: `pytesseract`** (Tesseract).
- **PaddleOCR** is an optional implemented backend. The `paddle-gpu` group
  installs NVIDIA support from the official CUDA 12.9 index. Model downloads
  require network access on first use; cached models are reused locally.
- The rest of the pipeline depends only on the interface, never on `pytesseract`
  directly.

## Video I/O & metadata

- **`ffprobe`** (via the `ffmpeg` install) is the primary source for metadata:
  FPS, duration, resolution, total frames, codec.
- **OpenCV (`opencv-contrib-python`)** is the fallback for FPS / frame count /
  resolution and is the reader for pulling individual frames.

## Image processing

- **OpenCV + NumPy** for grayscale, resize, adaptive/Otsu threshold, sharpen /
  denoise.
- **Laplacian variance** for blur detection (skip blurry scroll frames).
- **`scikit-image` SSIM** (or image diff) to skip near-duplicate frames.
- **Pillow** as needed for image handling to feed the OCR engine.

## Reconstruction & reporting

- **`rapidfuzz`** for fuzzy consolidation of repeated lines (scroll duplicates)
  and for choosing the best of multiple reads.
- **`pandas`** for assembling / writing `ocr_raw.csv`.
- **Markdown** for `relatorio_falhas.md`; **JSON** for `metadata_video.json`.

## Observability & UX

- **`rich`** for logs and progress; **`tqdm`** acceptable for progress bars.
- Clear, actionable error handling for the known failure modes (missing video,
  `ffprobe`/`tesseract` not installed, undetectable FPS, empty OCR, unwritable
  output dir).

## Crop-preview web tool (Phase 10)

- **Backend: FastAPI + uvicorn.** Small local-only server (binds `127.0.0.1`);
  typed request/response models reuse the project's pydantic convention.
  Chosen over Flask for native pydantic integration and over a desktop GUI to
  keep dependencies light.
- **Frontend: a single static HTML page with vanilla JS** served by FastAPI —
  no Node, no build step, no framework. The page shows the before/after frame
  images and a form for the crop values; edits call the backend, which
  re-crops and returns the updated preview.
- Frames are exchanged as **base64-encoded PNG** (or served from a temp dir);
  everything stays offline, consistent with the runtime rule above.
- The tool is a **separate entrypoint** that imports the shared seams from
  `extract_code_from_video.py` (metadata, frame reading, preprocessing, OCR
  engine construction) rather than duplicating them.

## Quality tooling

- **`ruff`** for linting and formatting.
- **`mypy`** for static type-checking (backs the "type hints everywhere" rule).
- These are the automated gates run by the phase skills in place of a "build"
  step; a phase is not done until `ruff`, `mypy`, and a real script run pass.

## Conventions

- Implementation is split into `video_ocr.models`, `video`, `imaging`, `ocr`,
  `pipeline`, `reconstruction`, `reports`, `quality`, and `cli`. The original
  extraction script remains a CLI and compatibility facade.
- Explicit preprocessing profiles: `legacy` (default binary 2x), `native`
  (cropped color), and `bounded` (color with configured scale/side limit).
  Do not change defaults based on speed alone; compare partial-reference CER,
  line numbers and indentation using `evaluate_ocr.py`.
- Unit CI excludes `integration`/`gpu` markers. GPU integration is manually
  dispatched on a self-hosted runner with the local video; quality thresholds
  are regression checks for the reference sample, not source-code guarantees.

- Modular functions with the exact seams named in the README:
  `get_video_metadata()`, `sample_frames()`, `preprocess_frame()`,
  `is_frame_blurry()`, `run_ocr()`, `parse_code_lines()`, `merge_ocr_results()`,
  `detect_missing_lines()`, `write_outputs()`.
- No hidden global state; pass typed models between stages.
