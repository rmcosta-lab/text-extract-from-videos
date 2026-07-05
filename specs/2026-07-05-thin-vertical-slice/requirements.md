# Requirements — Phase 1: Thin vertical slice (walking skeleton)

## Objective

Prove the whole pipeline runs end to end on one real video:
metadata → frame sampling → OCR → raw dump. Every artifact of the final output
tree that can exist at this stage is produced; quality work (preprocessing,
blur/duplicate skipping, reconstruction, failure report) is explicitly deferred.

## Scope

### Included

- `get_video_metadata()`: `ffprobe` as primary source (FPS, duration,
  resolution, total frames, codec), OpenCV as fallback for FPS / frame count /
  resolution; result written to `metadata_video.json` including the sampling
  strategy used.
- `sample_frames()`: read frames with OpenCV at a **fixed** sample step
  (adaptive-by-FPS arrives in Phase 2).
- OCR engine interface: a narrow `Protocol`/ABC with a single
  *image → OCR result* method, plus the `pytesseract` implementation. The
  pipeline calls only the interface.
- `run_ocr()` on the **whole frame** (no preprocessing, no crop wiring).
- `ocr_raw.csv` with columns: extracted text, frame number, video time,
  confidence, path of the frame image used.
- Naive `codigo_extraido.txt`: concatenation of raw OCR text in video-time
  order (no merging or dedup).
- Frames actually OCR'd saved to `frames_usados/`.
- Phase 0 behavior preserved: input validation, output-tree creation, clear
  errors.

### Excluded (later phases)

- `preprocess_frame()`, `is_frame_blurry()`, SSIM/duplicate skipping (Phase 2).
- Adaptive `sample_step` by detected FPS (Phase 2).
- `--crop-*` flags wired into processing (Phase 2; flags stay declared).
- `parse_code_lines()`, `merge_ocr_results()`, `[OCR_UNCERTAIN]` markers
  (Phase 3), time-based reconstruction (Phase 4).
- `detect_missing_lines()` and `relatorio_falhas.md` (Phase 5).
- PaddleOCR backend (future).

## Deliverables / output artifacts

```
saida/
├── codigo_extraido.txt    # naive concatenation of raw OCR text
├── ocr_raw.csv            # text, frame, time, confidence, frame image path
├── metadata_video.json    # FPS, duration, resolution, total frames, codec, sampling strategy
└── frames_usados/         # frames actually used for OCR
```

(`relatorio_falhas.md` is intentionally absent until Phase 5.)

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | All Phase 1 roadmap items as-is (user choice) |
| Metadata source | `ffprobe` primary, OpenCV fallback |
| Sampling | Fixed step constant; strategy name recorded in metadata JSON |
| OCR seam | `Protocol` with one `image → OCRResult` method; `pytesseract` is the only implementation |
| OCR input | Whole frame, unprocessed |
| Data models | `pydantic` models for metadata and OCR rows (per tech stack) |
| CSV writing | `pandas` |
| Logging | `rich` console output and progress |
| Validation | Standard checks only: `ruff`, `mypy`, real script run (user choice) |

## Fidelity & error-handling rules

- **Never invent code.** Phase 1 emits raw OCR output only; no synthesis,
  completion, or gap-stitching of any kind.
- Deterministic and inspectable: every `ocr_raw.csv` row references the exact
  frame image in `frames_usados/` and its timestamp.
- Local only: no network calls at runtime.
- Clear, actionable errors for the failure modes reachable in this phase:
  - video file missing or not a file (Phase 0 behavior);
  - output directory not creatable/writable (Phase 0 behavior);
  - `ffprobe` not installed → warn and fall back to OpenCV;
  - `tesseract` not installed → fail with install instructions;
  - FPS undetectable by both `ffprobe` and OpenCV → fail clearly;
  - video unreadable / zero frames decoded → fail clearly.
- Empty OCR on a frame is not an error: record the row (empty text) and
  continue.
