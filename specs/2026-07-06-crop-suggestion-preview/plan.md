# Plan — Phase 10: Crop suggestion preview (web)

## 1. Dependencies & skeleton

- Add `fastapi`, `uvicorn`, and `httpx` (test client) to the README install
  step / requirements, keeping them optional-but-documented like other deps.
- Create `suggest_crop.py` with a `typer` CLI: `--video` (required),
  `--engine {tesseract,paddle}` (default `tesseract`), `--host` (default
  `127.0.0.1`), `--port` (default `8000`), `--no-open` to skip launching the
  browser.
- Import the shared seams from `extract_code_from_video.py`:
  `get_video_metadata()`, `CropBox`, `apply_crop()`, `EngineName`,
  `create_ocr_engine()`, `OCREngineUnavailableError`, and the OCR result
  models. Fail with the same clear messages when dependencies are missing.

## 2. Frame access & suggestion heuristic

- `read_reference_frame(video, index=30)`: read frame 30 via OpenCV
  (`cv2.VideoCapture`); if the video has fewer frames, fall back to the last
  available frame and record which index was used.
- `suggest_crop(frame, engine) -> CropBox`: run the chosen OCR engine on the
  (preprocessed) reference frame, collect word/line boxes, take the bounding
  box of the text region that looks like gutter + code (ignore isolated
  outliers far from the main text block), pad with a small margin, and convert
  the box to edge-based crop values clamped to the frame size.
- Empty OCR ⇒ return `CropBox()` (zero crop) plus a flag so the UI can say
  "no text detected, showing full frame".
- Pure functions with pydantic models in/out; no global state.

## 3. FastAPI backend

- App factory `create_app(video: Path, default_engine: EngineName)` so tests
  can build an app around any video.
- `GET /` serves the static HTML page.
- `GET /api/preview?engine=...`: reads frame 30, runs the suggestion, returns
  JSON: video name, frame index used, frame dimensions, suggested `CropBox`,
  original frame and cropped frame as base64 PNG, and the ready-to-copy
  `--crop-*` flag string.
- `POST /api/crop` with body `{left, top, right, bottom}`: validates via
  `CropBox.validate_against()`, re-crops the cached reference frame, returns
  the updated cropped image + flag string; invalid values return a 422/400
  with a human-readable message.
- Cache the decoded reference frame in app state so re-crops don't re-open
  the video.
- `main()` wires typer → uvicorn, opens the browser unless `--no-open`.

## 4. Frontend (single static page)

- One HTML file (inline CSS/JS) served by FastAPI: side-by-side "original"
  and "cropped" images, four numeric inputs for the crop values, engine
  selector (`tesseract`/`paddle`), and the copyable CLI-flags string with a
  copy button.
- On load: call `/api/preview`, populate inputs with the suggested values and
  both images.
- On input change (debounced) or "Apply": call `/api/crop`, swap in the new
  cropped image and flag string; show API error messages inline.

## 5. Tests

- API tests with FastAPI's `TestClient` against `sample-video/IMG_5430.MOV`
  (skip cleanly if the file or tesseract is unavailable):
  - `/api/preview` returns 200, a valid `CropBox`, and non-empty base64
    images.
  - `/api/crop` with valid values returns an image sized to the cropped
    region.
  - `/api/crop` with values that leave no image area returns a clear error.
- Unit test for the heuristic's edge-to-box conversion and the empty-OCR
  zero-crop path (synthetic frames, no video needed).

## 6. Documentation

- README: short section for the crop-preview tool with an example command
  using `sample-video/IMG_5430.MOV`.
- Fix the Phase 10 roadmap exit criterion to reference `IMG_5430.MOV`
  (the listed `img_4430.mov` was a typo — the file does not exist).

## 7. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy` passes.
- Real run: `python suggest_crop.py --video sample-video/IMG_5430.MOV` starts
  the server, the page shows frame 30 before/after with a sensible suggested
  crop (gutter + code isolated), editing a value refreshes the preview, and
  the copied `--crop-*` flags work with the main CLI.
- API tests pass.
