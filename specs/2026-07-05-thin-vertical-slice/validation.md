# Validation — Phase 1: Thin vertical slice (walking skeleton)

### Output artifacts

- [x] A real script run creates `metadata_video.json`, `ocr_raw.csv`,
      `codigo_extraido.txt`, and `frames_usados/` under `--output`.
      (Verified: end-to-end run on a 180-frame test video produced all four.)
- [x] `frames_usados/` contains exactly the frames referenced by
      `ocr_raw.csv` (one image per sampled frame).
      (Verified: 12 CSV rows ↔ 12 PNGs, filenames match exactly.)
- [x] `ocr_raw.csv` has columns: text, frame, time, confidence,
      frame_image_path — one row per sampled frame.
      (Verified with pandas: exactly those five columns, 12 rows.)
- [x] `codigo_extraido.txt` is the raw OCR text concatenated in video-time
      order (no merging, no dedup).
      (Verified: file content equals the CSV `text` column joined by blank
      lines in frame order.)
- [x] `relatorio_falhas.md` is NOT produced (deferred to Phase 5).
      (Verified: absent from the output tree.)

### Metadata

- [x] `metadata_video.json` records FPS, duration, resolution, total frames,
      codec (when available), metadata source, and the sampling strategy used.
      (Verified: fps=30, duration=6.0s, 1280x720, 180 frames, codec=mpeg4,
      source=ffprobe, sampling_strategy="fixed_step=15".)
- [x] With `ffprobe` installed, metadata comes from `ffprobe`.
      (Verified: `"source": "ffprobe"` in the normal run.)
- [x] With `ffprobe` unavailable, OpenCV fallback fills FPS / frame count /
      resolution and a warning is logged.
      (Verified: run with ffprobe stripped from PATH logged the warning and
      produced `"source": "opencv"` with correct fps/resolution/frames.)

### OCR / fidelity

- [x] The pipeline calls OCR only through the `OCREngine` interface; no
      module outside the engine implementation imports `pytesseract`.
      (Verified: `pytesseract` is referenced only inside `TesseractEngine`;
      the pipeline is typed against the `OCREngine` Protocol.)
- [x] OCR runs on the whole, unprocessed frame.
      (Verified: `run_ocr()` passes the decoded frame directly to
      `engine.recognize()` — no preprocessing, no crop.)
- [x] No invented content: every character in `codigo_extraido.txt` traces to
      an `ocr_raw.csv` row and its saved frame image.
      (Verified: txt is byte-equal to the naive concatenation of CSV rows,
      and every row references an existing frame image.)
- [x] An empty OCR read is recorded as a row with empty text, not an error.
      (Verified: run on a blank white video → exit 0, 3 rows with empty text.)

### Error handling

- [x] Missing video file → clear error, exit code 1 (Phase 0 behavior kept).
      (Verified: "Error: video not found", exit 1.)
- [x] Unwritable output directory → clear error, exit code 1 (Phase 0 kept).
      (Verified against a read-only parent dir: clear error, exit 1.)
- [x] `tesseract` not installed → clear error with install instructions.
      (Verified with tesseract stripped from PATH: error suggests
      `brew install tesseract`, exit 1.)
- [x] FPS undetectable by both `ffprobe` and OpenCV → clear error.
      (Verified by exercising `_metadata_from_opencv` with a capture
      reporting fps=0: clear error, exit 1.)
- [x] Video opens but decodes zero frames → clear error.
      (Verified by exercising `sample_frames` with a capture that decodes
      nothing: clear error, exit 1. A fully unreadable file also fails
      clearly at open time.)

### Offline (no network)

- [x] The run performs no network calls; all processing is local.
      (Verified: only local subprocess (`ffprobe`), OpenCV decode, and local
      tesseract; no network-capable imports in the module.)

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] A real end-to-end run on one actual video completes without crashing
      (Phase 1 exit criterion).
      (Verified: 12 frames sampled and OCR'd from a 6s/30fps video, exit 0.)
