# Validation — Phase 5: Gap detection & failure report

### Output artifacts

- [x] A real script run creates the complete README tree under `--output`:
      `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
      `metadata_video.json`, and `frames_usados/`.
- [x] `relatorio_falhas.md` is written on every run, including runs where
      nothing is missing or uncertain (zero counts stated, not omitted).
- [x] `codigo_extraido.txt`, `ocr_raw.csv`, `metadata_video.json`, and
      `frames_usados/` keep their Phase 4 shape — no fields or behavior lost.

### Report content

- [x] The report contains every README-mandated section: video summary,
      detected FPS, frames analyzed, frames discarded for low sharpness,
      lines extracted, missing lines, low-confidence passages, unextractable
      sections, and capture recommendations.
- [x] Frame counts in the report are consistent with the run (sampled =
      kept + discarded blurry + discarded duplicate) and with what `main()`
      printed.
- [x] Capture recommendations include the README list: higher resolution,
      slower scroll, larger editor font, high-contrast theme.
- [x] The report body is in Portuguese, matching the artifact name and the
      README's example phrasing.

### Gap detection

- [x] On a numbered video with a numbering gap, each missing line is reported
      as `Linha N possivelmente ausente entre os tempos <before> e <after>.`
      with the timestamps of the surrounding extracted lines.
- [x] Missing lines are reported, never stitched over: the absent number has
      no fabricated content in `codigo_extraido.txt`.
- [x] A gap at the start or end of the numbering (no neighbor on one side) is
      reported without inventing a timestamp for the missing side.
- [x] On a video without line numbers, `detect_missing_lines()` returns no
      gaps and the report states that gap detection requires visible line
      numbers — it never guesses.
- [x] Empty or single-line merged input does not crash gap detection.

### OCR / fidelity

- [x] Low-confidence passages in the report are exactly the merged lines
      flagged `uncertain`, each with frame and timestamp traceable to
      `frames_usados/` and `ocr_raw.csv`.
- [x] Unextractable sections come only from observed frame outcomes
      (discarded or empty OCR) with start/end timestamps — no inferred
      content.
- [x] No invented code anywhere: the report surfaces failures; it adds
      nothing to the extracted code.
- [x] OCR is still called only through the `OCREngine` interface; no module
      outside the engine implementation imports `pytesseract`.

### Error handling

- [x] All Phase 0–4 errors preserved: missing video, unwritable output dir,
      missing `tesseract`, FPS undetectable, empty selection, invalid crop —
      each still a clear error, exit code 1.
- [x] A run with empty OCR / zero merged lines still writes a report stating
      that nothing could be extracted, without crashing.

### Offline (no network)

- [x] The run performs no network calls; all processing is local.

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] A real end-to-end run on one actual video completes without crashing
      and produces a report whose numbers match the run's console summary.
