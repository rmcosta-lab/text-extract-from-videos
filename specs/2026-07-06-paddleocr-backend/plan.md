# Plan — Phase 9: PaddleOCR backend

## 1. Engine selection surface

- Add an `--engine` typer option to the CLI accepting `tesseract` or `paddle`
  (default `tesseract`), using a small `enum.Enum` (e.g. `EngineName`) so typer
  validates the choice and mypy sees a closed set.
- Add an `engine: str` (or the enum) field to `ExtractionParameters` so the
  chosen engine is recorded in `extraction_parameters.json`; thread the value
  through `resolve_extraction_parameters()`.
- At the single instantiation seam (`engine: OCREngine = TesseractEngine()`),
  select the implementation from the flag via a small factory
  (e.g. `create_ocr_engine(name) -> OCREngine`), keeping
  `OCREngineUnavailableError` handling at the existing call site.

## 2. PaddleOCR engine

- Add `_require_paddleocr()` mirroring `_require_pytesseract()`: lazy import of
  `paddleocr` inside the function, raising `OCREngineUnavailableError` with an
  actionable hint (`python -m pip install paddleocr paddlepaddle`) on
  `ImportError`.
- Add `PaddleOCREngine` implementing `recognize(self, image: MatLike) ->
  OCRResult`:
  - Construct the PaddleOCR reader once in `__init__` (English/latin
    recognition, angle classification off — frames are upright screen
    captures); wrap initialization failures in `OCREngineUnavailableError`.
  - Run recognition on the (possibly preprocessed) frame exactly as received,
    matching how `TesseractEngine` treats its input.

## 3. Result mapping

- Convert each PaddleOCR detection (quad box + text + score) into an `OCRLine`:
  - Geometry: axis-aligned bounding box of the quad → `left`, `top`, `width`,
    `height` (clamped to ≥ 0).
  - Confidence: score normalized to the `0..100` scale used by Tesseract.
  - Words: PaddleOCR is line-oriented; populate `words` with a single `OCRWord`
    spanning the line box carrying the recognized text, so downstream code that
    inspects word evidence still has geometry. Do not fabricate per-word boxes.
- Sort lines top-to-bottom, left-to-right (same key as `TesseractEngine`),
  join their texts with `\n` for `OCRResult.text`, and compute the mean line
  confidence via `_mean_confidence`.
- Empty recognition returns `OCRResult(text="", confidence=None, lines=[])`,
  identical to the Tesseract empty case.

## 4. Outputs & docs

- Ensure `extraction_parameters.json` now contains the engine name for both
  engines' runs.
- README: document the `--engine` flag, the optional `paddleocr` install step,
  and the example command; keep Tesseract as the documented default.

## 5. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run: `python sample-video/run_sample.py` (default engine)
  completes and produces the full `saida/` tree.
- Same run with `--engine paddle` produces the full `saida/` tree; compare
  `codigo_extraido.txt`, `ocr_raw.csv`, and `relatorio_falhas.md` between the
  two runs to confirm PaddleOCR is a drop-in with no pipeline changes.
- `--engine paddle` without `paddleocr` installed fails with the actionable
  `OCREngineUnavailableError` message; `--help` still works.
