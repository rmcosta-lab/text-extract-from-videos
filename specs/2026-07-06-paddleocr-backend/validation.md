# Validation — Phase 9: PaddleOCR backend

### Output artifacts

- [x] Default-engine run (`python sample-video/run_sample.py`) produces the full
      output tree: `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
      `metadata_video.json`, `extraction_parameters.json`, `frames_usados/`.
      (Verified: run completed clean — 39/53 frames kept, 732 lines merged.)
- [x] `--engine paddle` run produces the same full output tree.
      (Verified: same sample arguments via the Python 3.13 paddle venv —
      39/53 frames kept, 953 lines merged, 12 missing, 0 uncertain.)
- [x] Comparing the two runs shows PaddleOCR is a drop-in: differences are
      confined to OCR read content/confidence, not artifact structure.
      (Verified: `diff` of artifact listings identical; `metadata_video.json`
      byte-identical; `extraction_parameters.json` differs only in `engine`.)

### Metadata

- [x] `extraction_parameters.json` records the chosen engine for the run
      (`tesseract` on the default run, `paddle` on the paddle run).
      (Verified in both output trees.)
- [x] All other extraction parameters (segment, crop, sampling) are unchanged
      by the engine choice. (Verified: parameters diff shows only the
      `engine` line.)

### OCR / fidelity

- [x] `PaddleOCREngine` maps per-line boxes into `OCRLine` geometry
      (left/top/width/height) and scores into confidence on the same `0..100`
      scale as Tesseract. (Verified: paddle `ocr_raw.csv` confidences range
      95.58–99.6, mean 98.7.)
- [x] No fabricated content: no per-word boxes are invented beyond the
      line-spanning word, and no text appears that the engine did not read.
      (By construction: each detection becomes one `OCRLine` with a single
      line-spanning `OCRWord` carrying the recognized text verbatim.)
- [x] Low-confidence Paddle reads receive `[OCR_UNCERTAIN]` markers through the
      existing pipeline logic, unchanged. (Same shared threshold path; on the
      sample video no paddle read fell below 60, so 0 markers — Tesseract run
      exercised the marker path with 14.)
- [x] Line-number parsing and spacing reconstruction work on Paddle output
      without pipeline changes. (Verified: paddle run reports "line numbers
      detected — merged by line number"; indentation preserved in
      `codigo_extraido.txt`.)

### Error handling

- [x] With `paddleocr` unavailable, `--engine paddle` fails with an
      `OCREngineUnavailableError` message that includes the install command.
      (Verified live with `paddlepaddle` missing: "PaddleOCR failed to
      initialize (...) Ensure paddlepaddle is installed (python -m pip install
      paddleocr paddlepaddle)...".)
- [x] With `paddleocr` not installed, `--engine tesseract` (and the default)
      run normally and `--help` works. (Verified: default run and `--help`
      unaffected.)
- [x] Empty OCR on the paddle engine still writes inspectable artifacts
      (`ocr_raw.csv`, `codigo_extraido.txt`, `relatorio_falhas.md`) before
      exiting. (Engine returns the same empty `OCRResult` shape as Tesseract;
      the empty-OCR path downstream of the seam is engine-agnostic and
      unchanged.)

### Offline (no network)

- [x] Extraction runs make no network calls; PaddleOCR model files are cached
      locally (`~/.paddlex/official_models/`) after the one-time install-time
      download, and the engine sets `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` so
      cached-model runs skip PaddleX's model-hoster connectivity probe.
      (Verified: probe message present before the fix, absent after.)

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] Real script run on the sample video completes without crashing on both
      engines.

### Environment note

`paddlepaddle` publishes no Python 3.14 wheels (max cp313) as of 2026-07-06.
The project venv is Python 3.14, so the paddle engine was validated with a
secondary `.venv-paddle` built on Homebrew Python 3.13 carrying the full
dependency stack; `sample-video/run_sample.py` prefers that venv when present.
The constraint is documented in the README.
