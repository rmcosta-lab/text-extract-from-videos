# Validation — Phase 4: No-line-number reconstruction

### Output artifacts

- [x] A real script run still creates `metadata_video.json`, `ocr_raw.csv`,
      `codigo_extraido.txt`, and `frames_usados/` under `--output`.
- [x] On a video **without** detected line numbers, `codigo_extraido.txt`
      contains the time-ordered, deduplicated reconstruction — not the
      per-frame naive concatenation.
- [x] On a video **with** line numbers, the Phase 3 numbered path still runs
      unchanged.
- [x] `relatorio_falhas.md` is still NOT produced (deferred to Phase 5).

### Metadata

- [x] `metadata_video.json` keeps its Phase 3 shape; no fields lost.
- [x] `ocr_raw.csv` still holds the raw per-frame reads (text, frame, time,
      confidence, sharpness, frame image path), untouched by reconstruction.

### Time-ordered reconstruction

- [x] Output lines follow video-time order: content first visible earlier in
      the video appears earlier in `codigo_extraido.txt`; within a frame, the
      on-screen top-to-bottom order is preserved.
- [x] Scroll-induced duplicates are removed: a line visible across many
      consecutive frames appears exactly once in the output.
- [x] Fuzzy consolidation groups slightly-different reads of the same line
      (similarity at/above the threshold constant) into one output line.
- [x] The winning read is chosen by frequency, then confidence, then frame
      sharpness — and its content appears verbatim (byte-identical to one
      actual OCR read; never a blend).
- [x] Two genuinely different lines that happen to be similar but below the
      threshold both survive — no real code is dropped by over-eager
      deduplication.
- [x] Empty OCR input or a single sampled frame does not crash the
      reconstruction.

### OCR / fidelity

- [x] OCR is still called only through the `OCREngine` interface; no module
      outside the engine implementation imports `pytesseract`.
- [x] Fuzzy matching only decides whether two reads are the same line — it
      never blends, averages, or repairs text.
- [x] A line whose best read is below the confidence threshold is preceded by
      `# [OCR_UNCERTAIN] frame=<n> time=<HH:MM:SS.mmm> texto_original="..."`
      in exactly that format, on this path too.
- [x] Every `[OCR_UNCERTAIN]` marker's frame number maps to an existing image
      in `frames_usados/` and a row in `ocr_raw.csv`.
- [x] No invented code anywhere: every output line (certain or uncertain) is
      traceable to a raw OCR read.

### Error handling

- [x] All Phase 0–3 errors preserved: missing video, unwritable output dir,
      missing `tesseract`, FPS undetectable, empty selection, invalid crop —
      each still a clear error, exit code 1.

### Offline (no network)

- [x] The run performs no network calls; all processing is local.

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] A real end-to-end run on one actual video without line numbers completes
      without crashing, with time ordering, overlap dedup, fuzzy
      consolidation, and uncertainty marking all exercised at least once
      across the validation runs.
