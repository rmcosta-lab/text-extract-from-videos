# Requirements — Phase 9: PaddleOCR backend

## Objective

Add PaddleOCR as a second OCR engine behind the existing `OCREngine` seam,
proving the seam is real: the new backend must be addable by writing one new
implementation of the interface, with no changes to the pipeline that consumes
it. The engine is selected with a new `--engine` CLI flag (default
`tesseract`), recorded in the extraction-parameters JSON, and proven on the
sample video with a full artifact tree from both engines.

The implementation must preserve the project's fidelity-first rule: never
invent code, prefer uncertainty markers or report entries over guessed content,
and keep every output traceable to frames and timestamps.

## Scope

### Included

- A `PaddleOCREngine` class implementing `OCREngine.recognize(image) ->
  OCRResult`, mirroring the Tesseract path:
  - Lazy import of `paddleocr` inside the engine only — the module must stay
    importable (and `--help` usable) when `paddleocr` is not installed.
  - Raise `OCREngineUnavailableError` with a clear, actionable install hint
    when `paddleocr` (or its runtime) is missing or fails to initialize.
- Map PaddleOCR's per-line boxes and recognition scores into `OCRResult` /
  `OCRLine` / `OCRWord`, preserving geometry (left/top/width/height) so the
  existing spacing reconstruction and gutter/code line-number pairing logic
  keep working unchanged.
- Low recognition scores flow through the existing confidence fields so the
  current `[OCR_UNCERTAIN]` marking applies as today. **Never invent code.**
- An `--engine {tesseract,paddle}` CLI flag, default `tesseract`, that selects
  the engine at the single existing instantiation seam; the rest of the
  pipeline continues to depend only on `OCREngine`.
- Record the chosen engine in `extraction_parameters.json`.
- Keep all existing required outputs: `codigo_extraido.txt`,
  `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
  `extraction_parameters.json`, and `frames_usados/`.

### Excluded

- No changes to sampling, preprocessing, reconstruction, merging, gap
  detection, or reporting logic — PaddleOCR must be a drop-in behind the seam.
- No network calls at runtime beyond what PaddleOCR itself does for one-time
  local model download at install/first-use; extraction runs stay local.
- No engine auto-selection, benchmarking framework, or per-engine tuning flags.
- No LLM-based reconstruction or correction.
- No change to the core rule that unreadable or uncertain code must be marked
  rather than fabricated.

## Deliverables / Output Artifacts

- Updated `extract_code_from_video.py` with `PaddleOCREngine` and the
  `--engine` flag.
- `extraction_parameters.json` includes the engine used for the run.
- Evidence of the dual-engine sample run: the default-engine run and the
  `--engine paddle` run each produce the full `saida/` artifact tree, with a
  comparison confirming PaddleOCR is a drop-in with no pipeline changes.

## Decisions

| Decision | Choice | Source |
| --- | --- | --- |
| Scope | Include all Phase 9 roadmap items as-is. | User answer |
| Implementation approach | Decide based on `specs/tech-stack.md` and `specs/mission.md`, mirroring the existing Tesseract engine patterns. | User answer |
| Validation | Standard checks are enough: `ruff`, `mypy`, and a real script run. | User answer |
| Engine seam | Single `OCREngine` Protocol with `recognize(image) -> OCRResult`; pipeline never imports OCR libraries directly. | `specs/tech-stack.md` |
| Default engine | `tesseract` remains the default; `paddle` is opt-in. | `specs/roadmap.md` |
| Dependency handling | `paddleocr` is optional: lazy import + `OCREngineUnavailableError` with install hint, matching the pytesseract path. | Existing code pattern |
| Structured data | Pydantic models (`OCRResult`, `OCRLine`, `OCRWord`, `ExtractionParameters`) carry all engine output and run settings. | `specs/tech-stack.md` |
| Fidelity rule | Preserve uncertainty, gaps, and raw OCR evidence; never invent code. | `specs/mission.md`, `README.md` |

## Fidelity & Error-Handling Rules

- Switching engines must not change any pipeline behavior other than the OCR
  reads themselves; all downstream marking, merging, and reporting rules apply
  identically to both engines.
- PaddleOCR scores map into the existing confidence fields on a comparable
  scale so `[OCR_UNCERTAIN]` thresholds behave sensibly; if Paddle reports
  scores in `0..1`, normalize them to the `0..100` scale Tesseract uses.
- If PaddleOCR provides only line-level geometry (no word boxes), the engine
  must still populate `OCRLine` geometry and text faithfully — it must not
  fabricate word boxes; spacing falls back to what the recognized line text
  contains.
- When `paddleocr` is missing, `--engine paddle` fails with a clear
  `OCREngineUnavailableError` message including the install command;
  `--engine tesseract` and `--help` are unaffected.
- Empty OCR from the Paddle engine follows the existing empty-OCR path:
  inspectable artifacts are still written before exiting.
- Missing video, undetectable FPS, unwritable output directory, and other
  named error cases behave exactly as before regardless of engine.
