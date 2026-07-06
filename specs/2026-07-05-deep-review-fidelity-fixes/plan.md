# Plan — Phase 7: Deep-review fidelity fixes

## 1. Dependency boundaries and CLI startup

- Audit top-level imports for heavy runtime dependencies (`cv2`, `numpy`,
  `PIL`, `pytesseract`, `skimage`) that can break `--help` before Typer runs.
- Move heavy imports behind the functions/classes that need them, or introduce
  small import helpers that raise actionable dependency errors only when the
  relevant pipeline stage executes.
- Keep type hints intact by using `TYPE_CHECKING`, lightweight aliases, or
  local imports rather than broad `Any` fallbacks.
- Verify missing OpenCV does not prevent `python extract_code_from_video.py
  --help` from rendering.

## 2. Metadata constraints

- Add Pydantic validation for `VideoMetadata` invariants:
  positive FPS, positive width/height, positive frame count when known, and
  positive duration when known.
- Keep the existing ffprobe-primary / OpenCV-fallback flow, but make invalid
  metadata fail with the same clear, actionable error style as other known
  cases.
- Ensure `metadata_video.json` serialization still matches the README output
  contract.

## 3. OCR text fidelity

- Inspect the current `pytesseract` result shape and identify where spacing is
  lost during OCR row creation or reconstruction.
- Preserve OCR line text and indentation when available instead of rebuilding
  code with single-space word joins.
- When word-level OCR data is the only source, reconstruct spacing from
  bounding-box positions conservatively; do not invent tokens to fill visual
  gaps.
- Keep `ocr_raw.csv` useful for inspection by retaining the text, frame,
  timestamp, confidence, and frame image path fields required by the README.

## 4. Line-number parsing and gutter/code pairing

- Broaden `parse_code_lines()` so it recognizes line-number forms including
  `12 print(...)`, `12:print(...)`, `12|print(...)`, and common OCR spacing
  variants.
- Handle captures where the gutter number and the code text appear in separate
  OCR blocks or adjacent OCR lines from the same frame.
- Preserve the code text exactly after the detected gutter separator, including
  leading indentation after the gutter.
- Keep low-confidence and ambiguous parses explicit; do not force a line number
  when the evidence is weak.

## 5. Run-scoped outputs

- Ensure the output directory tree is created with clear permissions handling.
- Clear stale frame images from `frames_usados/` at the beginning of output
  preparation or before saving current-run frames.
- Make empty-OCR runs write inspectable `ocr_raw.csv`, `codigo_extraido.txt`,
  and `relatorio_falhas.md` before returning exit code 1.
- Revisit `write_outputs()` ownership: either make it write the full output
  tree or rename/split helpers so metadata, frames, CSV, code, and report
  responsibilities are unambiguous.

## 6. Error handling and reporting polish

- Keep error messages actionable for missing dependencies, invalid metadata,
  empty OCR, unwritable output directories, and unavailable external tools.
- Confirm partial artifacts are preserved for inspection on late failures.
- Ensure `relatorio_falhas.md` accurately reports empty OCR, missing lines,
  low-confidence passages, discarded frames, and capture recommendations.

## 7. Verification

- `ruff check .` passes.
- `ruff format --check .` passes.
- `mypy extract_code_from_video.py` passes.
- A real script run on a sample video produces the full output tree without
  crashing.
- Manually exercise the Phase 7-specific cases:
  `--help` with OpenCV unavailable, empty OCR artifact writing, stale
  `frames_usados/` cleanup, line-number separator parsing, and preservation of
  indentation/spacing in reconstructed code.
