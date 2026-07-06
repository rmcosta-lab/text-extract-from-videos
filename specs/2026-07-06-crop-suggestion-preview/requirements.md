# Requirements — Phase 10: Crop suggestion preview (web)

## Objective

Before running a full extraction, automatically suggest crop parameters
(`--crop-left/-top/-right/-bottom`) that isolate the line-number gutter and the
code area of a screen recording, and let the user review and fine-tune those
values in a small local web page. The page shows the reference frame (frame 30)
before and after the crop; edits re-crop on the backend and refresh the
preview. The confirmed values are meant to be copied into the main CLI.

## Scope

### Included

- A **separate entrypoint** (new script) for the crop-preview tool. It imports
  the shared seams from `extract_code_from_video.py` — `get_video_metadata()`,
  `CropBox`, `apply_crop()`, `preprocess_frame()`, `EngineName`,
  `create_ocr_engine()`, and the `OCRResult`/`OCRLine`/`OCRWord` models —
  rather than duplicating any of that logic.
- An **auto-suggestion heuristic** that analyzes **frame 30** of the video:
  run OCR on the reference frame, derive the bounding region of the
  line-number gutter + code text from the OCR geometry, pad it with a small
  margin, and convert it to the main CLI's edge-based crop semantics
  (pixels removed from left/top/right/bottom).
- A **local FastAPI backend** (bound to `127.0.0.1`) with endpoints to:
  - serve the static page;
  - return the reference frame, the suggested `CropBox`, and the cropped
    preview for a video path + engine choice;
  - re-crop frame 30 for user-supplied crop values and return the updated
    preview.
- A **single static HTML page with vanilla JS** (no Node, no build step)
  showing the before/after images, the current crop values in a form, and the
  values formatted as copyable CLI flags. Editing a value triggers a backend
  re-crop and refreshes the "after" image.
- **Engine selection** for the suggestion heuristic: `tesseract` (default) or
  `paddle`, reusing `create_ocr_engine()`.
- Frames exchanged as **base64-encoded PNG** in JSON responses.

### Excluded

- No persistence of chosen crop values (user copies them manually).
- No changes to the main extraction pipeline or its CLI.
- No multi-frame analysis (frame 30 only), no video playback in the page.
- No authentication, no remote access, no packaging/deployment concerns.

## Deliverables / output artifacts

- New script (e.g. `suggest_crop.py`) exposing a `typer` CLI:
  `--video`, `--engine {tesseract,paddle}` (default `tesseract`),
  `--port`/`--host` with safe local defaults.
- Static frontend asset(s) served by the backend (single HTML page).
- API-level tests for the suggest and re-crop endpoints.
- README section documenting the tool and an example command against
  `sample-video/IMG_5430.MOV`.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Reference frame | Frame index 30 (fallback: last frame if video is shorter) | User requirement; early frame past any recording start artifacts |
| Backend | FastAPI + uvicorn, `127.0.0.1` only | Native pydantic integration; matches tech-stack.md |
| Frontend | Single static HTML + vanilla JS | No build step; offline; minimal surface |
| Image transport | Base64 PNG in JSON | Self-contained responses; no temp-file lifecycle |
| Crop semantics | Same edge-based `CropBox` as the main CLI | Values are copy-pasteable into `--crop-*` flags |
| Suggestion heuristic | OCR-geometry bounding box + margin on frame 30 | Reuses existing engines; no new detection dependency |
| Default engine | `tesseract` | User requirement; matches main CLI default |
| Sample video | `sample-video/IMG_5430.MOV` | The roadmap's `img_4430.mov` does not exist; IMG_5430.MOV is the only sample video (confirmed typo) |

## Fidelity & error-handling rules

- The tool **suggests** a crop; it never silently applies it to an extraction.
  The user copies the values explicitly.
- If OCR finds no text on frame 30, return a zero crop (full frame) and say so
  in the page — never fabricate a crop region.
- Suggested crops are validated with `CropBox.validate_against(width, height)`;
  user-supplied values that leave no image area return a clear API error shown
  in the page, not a crash.
- Clear, actionable errors for the known failure modes: missing video file,
  unreadable frame 30, missing `tesseract`/`paddleocr`
  (`OCREngineUnavailableError` with the install hint), port already in use.
- Local only: the server binds `127.0.0.1`; no network calls at runtime.
