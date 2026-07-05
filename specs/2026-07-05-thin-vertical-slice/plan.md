# Plan — Phase 1: Thin vertical slice (walking skeleton)

## 1. Data models

- `VideoMetadata` pydantic model: fps, duration_seconds, width, height,
  total_frames, codec (optional), source (`ffprobe` | `opencv`),
  sampling_strategy (e.g. `"fixed_step=15"`).
- `OCRResult` pydantic model for one frame's read: text, confidence
  (optional/None when unavailable).
- `OCRRow` pydantic model for one `ocr_raw.csv` row: text, frame_number,
  time_seconds (plus formatted `HH:MM:SS.mmm`), confidence, frame_image_path.

## 2. Metadata — `get_video_metadata()`

- Run `ffprobe -v error -select_streams v:0 -show_entries ... -of json` via
  `subprocess`; parse fps (rational like `60/1`), duration, width, height,
  nb_frames, codec_name.
- If `ffprobe` is missing (`FileNotFoundError`) or fails/returns unusable data,
  log a `rich` warning and fall back to OpenCV (`CAP_PROP_FPS`,
  `CAP_PROP_FRAME_COUNT`, `CAP_PROP_FRAME_WIDTH/HEIGHT`); codec may be absent.
- If neither source yields a usable FPS (> 0), fail clearly.
- Serialize the model to `metadata_video.json`.

## 3. OCR seam — engine interface + pytesseract

- `OCREngine` `Protocol` with a single method:
  `recognize(image) -> OCRResult` (NumPy BGR/gray array in, model out).
- `TesseractEngine` implementing it via `pytesseract.image_to_data`
  (aggregate word text preserving line breaks; mean word confidence).
- Detect missing tesseract binary (`pytesseract.TesseractNotFoundError`) at
  startup and fail with `brew install tesseract` instructions.
- Pipeline code depends only on `OCREngine`, never on `pytesseract` directly.

## 4. Sampling & pipeline wiring — `sample_frames()` / `run_ocr()`

- `sample_frames()`: open the video with `cv2.VideoCapture`, yield
  `(frame_number, time_seconds, image)` every `FIXED_SAMPLE_STEP` frames
  (module constant, e.g. 15); fail clearly if the video opens but decodes
  zero frames.
- `run_ocr()`: for each sampled frame — save it as
  `frames_usados/frame_<n>.png`, call the engine on the whole frame, collect
  an `OCRRow` (empty OCR text is recorded, not treated as an error).
- `rich` progress display over the sampled frames.

## 5. Outputs — `write_outputs()`

- `ocr_raw.csv` via pandas from the `OCRRow` models
  (columns: text, frame, time, confidence, frame_image_path).
- `codigo_extraido.txt`: naive concatenation of each frame's raw text in
  video-time order, separated by blank lines — no merging, no dedup, no
  invented content.
- Keep `metadata_video.json` writing here or in step 2 — single obvious place.
- Wire everything into the existing `typer` `main()` after the Phase 0
  validation block; crop flags remain declared but unused.

## 6. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on one actual video produces `metadata_video.json`,
  `ocr_raw.csv`, `codigo_extraido.txt`, and populated `frames_usados/`
  without crashing (Phase 1 exit criterion).
- Validate every checkbox in `validation.md`.
