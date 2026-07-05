# Validation — Phase 0: Project skeleton

### Output artifacts

- [x] Running with a valid `--video` and a new `--output` creates the output
      directory and the `frames_usados/` subdirectory.
- [x] No placeholder result files (`codigo_extraido.txt`,
      `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`) are created
      in this phase.
- [x] Re-running against an existing output directory succeeds (idempotent
      tree creation).

### Metadata

- [x] Not applicable this phase — no `metadata_video.json` is produced yet
      (arrives in Phase 1).

### OCR / fidelity

- [x] No OCR runs and no extracted-code content is fabricated; the CLI states
      that the pipeline is not implemented yet.

### Error handling

- [x] Nonexistent `--video` path → clear error message naming the path,
      exit code 1, no output tree created.
- [x] `--video` pointing at a directory → clear error, exit code 1.
- [x] Unwritable `--output` (e.g. under a read-only directory) → clear error
      naming the directory, exit code 1.
- [x] Errors are `rich`-styled messages, not raw tracebacks.

### Offline (no network)

- [x] The script makes no network calls at runtime.

### Technical

- [x] `.venv` exists and contains all README dependencies plus `ruff` and
      `mypy`.
- [x] `ruff check .` passes.
- [x] `ruff format --check .` passes.
- [x] `mypy extract_code_from_video.py` passes.
- [x] Real script run: `python extract_code_from_video.py --video <real file>
      --output saida/` exits 0 and creates the tree.
- [x] `--help` shows `--video`, `--output`, and all four `--crop-*` flags.
