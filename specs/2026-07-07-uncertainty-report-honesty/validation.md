# Validation — Phase 12: Uncertainty & report honesty

### Uncertainty gate

- [x] With `--engine paddle` on `sample-video/IMG_5430.MOV`, the run emits
      `[OCR_UNCERTAIN]` markers (> 0) and `relatorio_falhas.md` reports the
      same count under "Trechos com baixa confiança".
- [x] Tesseract behavior for confident, agreeing reads is unchanged (floor
      stays 60; clean lines carry no marker).
- [x] A line whose reads diverge (winner fuzzy-support < 50% over ≥ 3 reads)
      is marked uncertain regardless of confidence.

### Empty reads

- [x] A line number read 4× as bare gutter and 2× with content emits the
      content, not a blank line.
- [x] A line whose reads are all gutter-only still emits a blank line
      (genuinely blank is indistinguishable — no fabrication).

### Report

- [x] Near-duplicate discards no longer appear inside "Trechos impossíveis
      de extrair" spans; blurry and empty-OCR frames still do.
- [x] Numbering starting above 1 renders one collapsed "Linhas 1 a N" range
      entry; the count line stays the true total.
- [x] The numbered path reports how many reads had no detectable line number.

### Output tree

- [x] A run that fails after metadata but before OCR outputs (e.g. invalid
      crop) leaves no stale `codigo_extraido.txt` / `ocr_raw.csv` /
      `relatorio_falhas.md` from a previous run in the output directory.

### suggest_crop

- [x] `--start-time 0` samples from frame 0 (not the reference frame 30).
- [x] No `--start-time` keeps the reference-frame-30 default.

### Offline

- [x] With no `~/.paddlex/official_models`, instantiating the Paddle engine
      prints an actionable warning about the first-run network download.

### Technical

- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy` passes on the touched files.
- [x] `pytest test_suggest_crop.py` passes.
- [x] Real run: `python sample-video/run_sample.py` produces the full
      artifact tree; `saida/` regenerated.
