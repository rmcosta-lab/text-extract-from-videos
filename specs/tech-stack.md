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
- OCR runs locally with cached models. Optional visual review uses the paid
  OpenAI Responses API through the `review` dependency group. Offline recovery,
  report generation and review evaluation do not load the SDK or require a key.

## CLI & data modeling

- **CLI framework: `typer`.** (Not argparse.) Extraction entrypoint
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

## Independent Explorer video segmentation

- `split_explorer_video.py` / `explorer_segments` are separate from OCR/review.
  Basic dependencies are existing OpenCV, NumPy, Pydantic, Typer and local FFmpeg.
  Automatic discovery uses PaddleOCR with explicit cached model paths; no imports
  from the code OCR/review pipelines and no runtime model downloads.
- Normalized template correlation at multiple scales, with separate stable Explorer
  panel and application-anchor regions. Calibration and thresholds live in a
  reusable external profile, not in code tied to a particular movie.
- Coarse sampling with frame-level refinement around transitions; optional
  exhaustive analysis. Ambiguous frames are excluded, with evidence and timestamps.
- H.264 re-encoding preserves accurate temporal cuts; optional NVENC accelerates
  export only. Local AI discovers the panel/tree and generates the visual profile;
  no API or credentials are used. Manual calibration remains optional.
- See [calibration and limitations](../docs/explorer-segmentation.md).

## Quality tooling

- Review workflow: `review_ocr.py`; anchored visual review with strict Pydantic
  schemas. Raw response records are persisted before parsing and application.
- `review_plan`, `review_run`, `review_storage`, and `review_report` separate
  evidence selection, resumable execution, atomic records and line mapping.
- `evaluate_review.py` / `review_quality` evaluate saved reviews against an
  anchored partial visual reference, independently of OCR runtime and API.
- Review images use Pillow WebP quality 90/method 4; existing JPEG evidence is
  accepted. Crops retain original resolution. See
  [review workflow](../docs/review-workflow.md) for limits and compatibility.

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
- Blur recovery: forward search up to 0.25 s on rejected candidates, bounded by
  the next sampling candidate and segment end; cropped sharpness, actual frame
  provenance, and `blur_recovery.json` audit. Disable with `--blur-retry-seconds 0`.
- Paddle OCR extraction and Explorer discovery now pin PP-OCRv6 medium detection
  and recognition with PaddleOCR 3.7.x; existing discovery artifacts remain historical.
- Optional extraction engine `paddle-vl`: direct local GPU PaddleOCR-VL-1.6,
  PaddleOCR 3.7 doc-parser group, raw multiline text without fabricated geometry
  or confidence. See [usage and limits](../docs/paddle-vl.md).
