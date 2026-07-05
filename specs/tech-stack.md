# Tech Stack

Locked technology decisions for the project. The dependency list and install
steps in [`README.md`](../README.md) are the source of truth; this document
records the *choices among alternatives* and the *conventions* that bind future
work.

## Language & runtime

- **Python 3** in a local virtualenv (`.venv`).
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

- **Default (and only current) implementation: `pytesseract`** (Tesseract).
- **PaddleOCR** is a documented *future* backend that must be addable by writing
  one new implementation of the interface — no changes to the pipeline that
  calls it.
- The rest of the pipeline depends only on the interface, never on `pytesseract`
  directly.

## Video I/O & metadata

- **`ffprobe`** (via the `ffmpeg` install) is the primary source for metadata:
  FPS, duration, resolution, total frames, codec.
- **OpenCV (`opencv-python`)** is the fallback for FPS / frame count /
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

## Conventions

- Modular functions with the exact seams named in the README:
  `get_video_metadata()`, `sample_frames()`, `preprocess_frame()`,
  `is_frame_blurry()`, `run_ocr()`, `parse_code_lines()`, `merge_ocr_results()`,
  `detect_missing_lines()`, `write_outputs()`.
- No hidden global state; pass typed models between stages.
