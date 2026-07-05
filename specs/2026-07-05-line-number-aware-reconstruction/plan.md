# Plan — Phase 3: Line-number-aware reconstruction

## 1. Data models & per-line OCR data

- Extend `OCRResult` with per-line reads: a list of `OCRLine` entries
  (`text`, `confidence | None`), keeping the aggregate `text` / `confidence`
  fields for the raw CSV. `TesseractEngine.recognize()` builds them from
  `pytesseract.image_to_data` (group words by line, average word confidences);
  the `OCREngine` protocol keeps its single `recognize()` method.
- Record frame sharpness: reuse the Laplacian variance already computed for
  the blur gate, thread it through `run_ocr()`, and store it on `OCRRow`
  (new `sharpness` field; extra CSV column is acceptable — raw stays raw).
- New pydantic models for reconstruction:
  - `LineRead`: one read of one on-screen line — `line_number: int | None`,
    `content: str`, `frame_number`, `time_seconds`, `time_formatted`,
    `confidence: float | None`, `sharpness: float`.
  - `MergedLine`: the chosen best read for a line number — the winning
    `LineRead` plus an `uncertain: bool` flag.

## 2. Line parsing — `parse_code_lines()`

- Signature: `(rows: list[OCRRow]) -> list[LineRead]` (rows carry their
  per-line engine reads or are re-split from text lines).
- Leading-number regex: optional indentation, an integer (bounded digits),
  optional `:`, `.`, `|` separator, then at least one space before content —
  applied per line. Match → strip number + separator, keep the content's own
  indentation; no match → `line_number=None`, full text as content.
- Blank contents are kept out; the line number itself is never treated as code.
- Module-level constants for the regex and digit bounds, named and grouped.

## 3. Numbers-present heuristic

- `has_line_numbers(reads: list[LineRead]) -> bool`: true when the share of
  non-empty reads with a detected number clears a threshold constant
  (e.g. ≥ 60%) and the numbers are mostly increasing within each frame
  (guards against code that merely starts with integers).
- Decision logged via `rich` so a run states which reconstruction path ran.

## 4. Merging — `merge_ocr_results()`

- Signature: `(reads: list[LineRead]) -> list[MergedLine]`; considers only
  reads with a detected line number.
- Group reads by `line_number`. Per group, pick the winner by:
  1. frequency — most common exact content (whitespace-normalized for
     counting, original text preserved for output);
  2. confidence — highest average/first among the tied contents;
  3. sharpness — sharpest source frame as the final tiebreaker.
- The winner's content is emitted **verbatim** — never a blend of reads.
- Mark `uncertain=True` when the winning read's confidence is below the
  `OCR_UNCERTAIN` threshold constant (or missing entirely).
- Return merged lines sorted by line number; gaps are left as gaps
  (`detect_missing_lines()` is Phase 5).

## 5. Output wiring — `write_outputs()` and `main()`

- `write_outputs()` gains the reconstruction: when `has_line_numbers()` is
  true, `codigo_extraido.txt` is the merged lines in line-number order, each
  uncertain line preceded by
  `# [OCR_UNCERTAIN] frame=<n> time=<HH:MM:SS.mmm> texto_original="..."`;
  otherwise the Phase 1 naive concatenation is written unchanged.
- `metadata_video.json` and `ocr_raw.csv` keep their existing shape (plus the
  raw `sharpness` column); `frames_usados/` untouched.
- `main()` wires `parse_code_lines()` → `has_line_numbers()` →
  `merge_ocr_results()` between `run_ocr()` and `write_outputs()`, with a
  `rich` summary line (lines reconstructed, uncertain count, path taken).

## 6. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on one actual video with visible line numbers:
  `codigo_extraido.txt` ordered by line number, duplicates from scrolling
  collapsed to one line each, uncertain lines carrying the exact marker
  format, and every marker traceable to a frame in `frames_usados/`.
- A run on input without line numbers (or with none detected) still produces
  the naive concatenation without crashing.
- Validate every checkbox in `validation.md`.
