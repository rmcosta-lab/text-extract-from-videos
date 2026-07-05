# Validation — Phase 6: Robustness & polish

### Output artifacts

- [x] A healthy run still produces the full tree: `codigo_extraido.txt`,
      `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
      `frames_usados/`. (Verified on a synthetic scrolling-code video.)
- [x] Extraction output for a healthy run is unchanged from Phase 5 (this
      phase adds no extraction behavior). (Phase 5 script from git HEAD run on
      the same video; `codigo_extraido.txt`, `relatorio_falhas.md`, and
      `ocr_raw.csv` byte-identical apart from the output-dir path column.)

### Metadata

- [x] `metadata_video.json` is written before any late-pipeline failure
      (e.g. empty OCR), so failed runs remain inspectable. (`write_metadata()`
      now runs right after the sampling strategy is chosen; confirmed present
      on disk after an empty-OCR failure.)

### OCR / fidelity

- [x] No error-handling path fabricates or alters extracted code. (Changes are
      confined to `_warn`/`_fail` messages, an early metadata write, console
      lines, and a fail-fast on empty reads; healthy-run diff is empty.)
- [x] `[OCR_UNCERTAIN]` markers and missing-line records behave exactly as
      before. (Same diff.)

### Error handling

- [x] Nonexistent video path → exit 1, message names the path.
- [x] Video path that is a directory / not a file → exit 1, clear message.
      (Tested with `specs/` as `--video`.)
- [x] `ffprobe` missing → warning + OpenCV fallback; run continues.
      (Tested with a PATH exposing tesseract but not ffprobe; warning now
      includes the `brew install ffmpeg` hint; run completed, exit 0.)
- [x] `tesseract` missing → exit 1, message includes install hint.
      (Tested with PATH=/usr/bin:/bin.)
- [x] Undetectable FPS → exit 1, message explains the video may be corrupt or
      unsupported. (Exercised via a harness patching ffprobe away and
      `CAP_PROP_FPS` to 0.)
- [x] Empty OCR (frames processed, no text recognized) → exit 1, message
      distinct from the "all frames discarded" case, with capture
      recommendations. (Tested with a random-noise video: 6 frames kept and
      OCR'd, no text; message points at `frames_usados/` and
      `metadata_video.json`.)
- [x] Output directory without write permission → exit 1, message names the
      directory. (Tested with a chmod 555 directory.)
- [x] All failures use exit code 1; partial artifacts are left on disk.
      (Every test above echoed exit=1; noise-video run left
      `metadata_video.json` + 6 frame images on disk.)

### Rich logging / progress

- [x] Every stage (metadata, sampling, OCR, reconstruction, outputs) emits a
      `rich` progress bar or completion line. (Video / Sampling with expected
      candidate count / OCR progress bar / Selection / Reconstruction /
      Report / Done listing all five artifacts.)
- [x] Warnings go to stderr in the existing `[bold yellow]` style; errors in
      `[bold red]`. (Unchanged `_warn`/`_fail` helpers on the stderr console.)

### README

- [x] README contains a short pipeline-logic explanation. ("Explicação curta
      da lógica" section, 7 numbered steps.)
- [x] README contains a runnable example command (including a crop example).
      ("Exemplo de comando de execução" section.)
- [x] Locked spec sections of the README are unchanged. (New sections appended
      after the "Entregáveis" list; no existing line modified.)

### Offline (no network)

- [x] No error path or logging addition performs any network call. (Only
      subprocess use remains the local `ffprobe`; no network libraries
      imported.)

### Technical

- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] Real script run on a sample video completes without crashing.
      (Synthetic 30 fps scrolling-code video → full output tree, exit 0.)
