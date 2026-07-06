# Validation — Phase 10: Crop suggestion preview (web)

### Output artifacts

- [x] `suggest_crop.py` exists as a separate entrypoint with a `typer` CLI
      (`--video`, `--engine`, `--host`, `--port`; plus `--open/--no-open`).
- [x] The static HTML page (`crop_preview.html`) is served by the backend; no
      Node/build step is required anywhere (single file, inline CSS/JS).
- [x] The page displays the suggested crop values and a ready-to-copy
      `--crop-left/-top/-right/-bottom` flag string (verified via `GET /` and
      the `cli_flags` field of both API responses).

### Reuse (no duplicated logic)

- [x] The tool imports `get_video_metadata()`, `CropBox`, `EngineName`,
      `create_ocr_engine()`, `preprocess_frame()`, `LINE_NUMBER_WORD_RE`, and
      the OCR result models from `extract_code_from_video.py`.
- [x] No metadata, preprocessing, or engine-construction logic is
      re-implemented in the new script (crop slicing uses the same edge
      semantics; validation reuses `CropBox.validate_against`).

### Crop suggestion / preview behavior

- [x] Frame 30 is used as the reference frame (`REFERENCE_FRAME_INDEX`),
      falling back to the last frame for shorter videos.
- [x] The backend returns the reference frame before and after the crop
      (base64 PNG, sizes verified against frame/crop dimensions in tests).
- [ ] Manual: the page shows both images side by side in a real browser.
- [x] Editing crop values re-crops on the backend (`POST /api/crop` verified
      live and in tests; the page calls it on input with debounce).
- [ ] Manual: editing a value in the browser visibly refreshes the preview.
- [x] The engine is selectable (`tesseract`/`paddle`) and defaults to
      `tesseract`; `?engine=paddle` without paddleocr returns the install
      hint as a clear 400, unknown engines are rejected with 422.

### Crop quality on sample video

- [x] Running against `sample-video/IMG_5430.MOV`, the auto-suggested crop
      (`--crop-left 145 --crop-top 232 --crop-right 2228 --crop-bottom 138`)
      isolates the line-number gutter + code area: menu/tab bars, status bar,
      activity-bar icons, and minimap are all excluded (confirmed by
      inspecting the returned before/after PNGs). The heuristic anchors on
      the detected gutter column and trims low-confidence right segments.
- [x] The suggested values, copied into the main CLI, produce a valid run
      (`extract_code_from_video.py` with the flags above completed with
      exit 0 on a 1–3 s segment; crop passes `validate_against`).

### API-level tests

- [x] `TestClient` tests cover `/api/preview` (200, valid `CropBox`,
      non-empty base64 PNGs whose headers match the expected dimensions).
- [x] Tests cover `/api/crop` with valid values (image matches the cropped
      dimensions and the flags string round-trips).
- [x] Tests cover `/api/crop` with degenerate values (422 with a
      human-readable message, no crash) and negative values (422).
- [x] Unit tests cover the heuristic with a fake engine: gutter-anchored
      crop, band exclusion of status-bar rows, low-confidence right-segment
      trimming, no-gutter cluster fallback, and the empty-OCR zero-crop path.

### Error handling

- [x] Missing video file fails before the server starts:
      `Error: video file not found: ...`, exit code 1.
- [x] Missing `paddleocr` surfaces the install hint (rich markup stripped)
      as an API 400; missing `tesseract` raises `OCREngineUnavailableError`
      at startup, caught and reported via `_fail` (tests skip cleanly).
- [x] Crop values that leave no image area return a human-readable 422
      shown in the page's notice area.
- [x] Empty OCR on frame 30 yields a zero crop with `text_detected=false`;
      the page shows an explicit "no text detected" notice — never a
      fabricated region (unit-tested).

### Offline (no network)

- [x] The server binds `127.0.0.1` by default (uvicorn host default in the
      CLI).
- [x] The page loads no external resources (inline CSS/JS only, images as
      base64 data URIs).

### Technical

- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy extract_code_from_video.py suggest_crop.py test_suggest_crop.py`
      passes.
- [x] Real script run: `python suggest_crop.py --video
      sample-video/IMG_5430.MOV` served the page end-to-end (`GET /`,
      `/api/preview`, `/api/crop` exercised over HTTP against the live
      server).
- [x] `pytest test_suggest_crop.py`: 11 passed.
