# Validation — Phase 3: Line-number-aware reconstruction

### Output artifacts

- [x] A real script run still creates `metadata_video.json`, `ocr_raw.csv`,
      `codigo_extraido.txt`, and `frames_usados/` under `--output`.
- [x] On a video with visible line numbers, `codigo_extraido.txt` contains the
      merged reconstruction ordered by line number — not the per-frame
      concatenation.
- [x] On input without detected line numbers, `codigo_extraido.txt` is the
      Phase 1 naive concatenation (fallback path, no crash).
- [x] `relatorio_falhas.md` is still NOT produced (deferred to Phase 5).

### Metadata

- [x] `metadata_video.json` keeps its Phase 2 shape (adaptive sampling
      strategy included); no fields lost.
- [x] `ocr_raw.csv` still holds the raw per-frame reads (text, frame, time,
      confidence, frame image path), untouched by merging; the added
      sharpness column is populated for every row.

### Line parsing

- [x] `parse_code_lines()` detects a leading line number and separates it
      from the content; the emitted content does not include the number or
      its separator.
- [x] Content indentation is preserved after the number is stripped.
- [x] Lines without a leading number parse with `line_number=None` and full
      text as content (no crash, no invented number).
- [x] The numbers-present heuristic selects the numbered path on a
      line-numbered video and the naive path when numbers are absent; the
      chosen path is logged.

### Merging / reconstruction

- [x] Multiple reads of the same line number collapse to exactly one output
      line; scroll-induced duplicates do not repeat in `codigo_extraido.txt`.
- [x] The winning read is chosen by frequency, then confidence, then frame
      sharpness — and its content appears verbatim (byte-identical to one
      actual OCR read; never a blend).
- [x] Output lines are strictly ordered by ascending line number.
- [x] A gap in numbering (e.g. 32 → 34) stays a gap — no stitched or invented
      line 33 (explicit gap records are Phase 5).

### OCR / fidelity

- [x] OCR is still called only through the `OCREngine` interface; no module
      outside the engine implementation imports `pytesseract`.
- [x] Per-line confidences come from the engine result; the interface remains
      a single `recognize()` method.
- [x] A line whose best read is below the confidence threshold is preceded by
      `# [OCR_UNCERTAIN] frame=<n> time=<HH:MM:SS.mmm> texto_original="..."`
      in exactly that format.
- [x] Every `[OCR_UNCERTAIN]` marker's frame number maps to an existing image
      in `frames_usados/` and a row in `ocr_raw.csv`.
- [x] No invented code anywhere: every output line (certain or uncertain) is
      traceable to a raw OCR read.

### Error handling

- [x] All Phase 0–2 errors preserved: missing video, unwritable output dir,
      missing `tesseract`, FPS undetectable, empty selection, invalid crop —
      each still a clear error, exit code 1.
- [x] Empty OCR text or zero parsed lines does not crash reconstruction; the
      run completes via the fallback path.

### Offline (no network)

- [x] The run performs no network calls; all processing is local.

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] A real end-to-end run on one actual video completes without crashing,
      with parsing, the heuristic, merging, and uncertainty marking all
      exercised at least once across the validation runs.
