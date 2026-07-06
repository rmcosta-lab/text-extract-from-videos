# Validation — Phase 9: PaddleOCR backend

### Output artifacts

- [ ] Default-engine run (`python sample-video/run_sample.py`) produces the full
      output tree: `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
      `metadata_video.json`, `extraction_parameters.json`, `frames_usados/`.
- [ ] `--engine paddle` run produces the same full output tree.
- [ ] Comparing the two runs shows PaddleOCR is a drop-in: differences are
      confined to OCR read content/confidence, not artifact structure.

### Metadata

- [ ] `extraction_parameters.json` records the chosen engine for the run
      (`tesseract` on the default run, `paddle` on the paddle run).
- [ ] All other extraction parameters (segment, crop, sampling) are unchanged
      by the engine choice.

### OCR / fidelity

- [ ] `PaddleOCREngine` maps per-line boxes into `OCRLine` geometry
      (left/top/width/height) and scores into confidence on the same `0..100`
      scale as Tesseract.
- [ ] No fabricated content: no per-word boxes are invented beyond the
      line-spanning word, and no text appears that the engine did not read.
- [ ] Low-confidence Paddle reads receive `[OCR_UNCERTAIN]` markers through the
      existing pipeline logic, unchanged.
- [ ] Line-number parsing and spacing reconstruction work on Paddle output
      without pipeline changes.

### Error handling

- [ ] With `paddleocr` not installed, `--engine paddle` fails with an
      `OCREngineUnavailableError` message that includes the install command.
- [ ] With `paddleocr` not installed, `--engine tesseract` (and the default)
      run normally and `--help` works.
- [ ] Empty OCR on the paddle engine still writes inspectable artifacts
      (`ocr_raw.csv`, `codigo_extraido.txt`, `relatorio_falhas.md`) before
      exiting.

### Offline (no network)

- [ ] Extraction runs make no network calls; any PaddleOCR model files are
      resolved locally at runtime.

### Technical

- [ ] `ruff check .` passes.
- [ ] `ruff format --check .` passes.
- [ ] `mypy extract_code_from_video.py` passes.
- [ ] Real script run on the sample video completes without crashing on both
      engines.
