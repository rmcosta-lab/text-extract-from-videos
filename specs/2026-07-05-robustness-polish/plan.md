# Plan — Phase 6: Robustness & polish

## 1. Error-case audit

- Walk each named error case against the current code and record its status:
  - video missing / not a file — handled in `main()`;
  - `ffprobe` missing / failing / unparsable — handled with OpenCV fallback
    warnings in `_metadata_from_ffprobe()`;
  - `tesseract` missing — handled via `OCREngineUnavailableError` in
    `PytesseractEngine.__init__`;
  - undetectable FPS — handled in `_metadata_from_opencv()`;
  - output directory not creatable / not writable — handled in `main()`;
  - all sampled frames discarded — handled after `run_ocr()`;
  - **empty OCR** (rows exist but no reads/text) — currently unhandled.
- Review every `_fail()` / `_warn()` message for clarity and actionability;
  add install hints (`brew install ffmpeg`, `brew install tesseract`) where a
  tool is missing.

## 2. Empty-OCR handling

- After `parse_code_lines()` in `main()`, detect the case where OCR produced
  rows but no usable reads (no recognized text in any frame).
- Fail with a clear message that distinguishes it from the existing
  "every frame discarded" case and suggests remedies (crop region, editor
  font size, video resolution) — after `metadata_video.json` and
  `frames_usados/` are already on disk so the run stays inspectable.

## 3. Rich logging & progress coverage

- Confirm each pipeline stage emits either progress (`rich.progress.track`,
  already used for OCR) or a concise completion line on the shared `console`:
  - metadata: source used (ffprobe vs OpenCV) and key values;
  - sampling: step chosen and expected sample count;
  - OCR: existing progress bar + kept/discarded summary;
  - reconstruction: existing path-taken summary;
  - outputs: final line listing the artifacts written and their location.
- Fill any gaps; keep the existing message style (`[green]Stage:[/green] …`,
  `[bold yellow]Warning:[/bold yellow]`, `[bold red]Error:[/bold red]`).

## 4. README additions

- Add a short "how it works" section: metadata → adaptive sampling →
  preprocessing & frame selection → OCR → reconstruction (numbered vs
  time-based) → gap detection → outputs, in a few sentences.
- Add an example command block:
  `python extract_code_from_video.py --video caminho/do/video.mp4 --output saida/`
  including a crop-flag example.
- Do not alter the locked behavioral spec portions of the README.

## 5. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on a sample video produces the full output tree without
  crashing.
- Exercise error paths manually: nonexistent video, unwritable output dir
  (`chmod 555`), and at least one simulated missing-tool case (e.g. PATH
  without `ffprobe`), confirming exit code 1 and a clear message each time.
