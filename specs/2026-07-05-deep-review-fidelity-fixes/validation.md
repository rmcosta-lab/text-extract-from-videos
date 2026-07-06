# Validation - Phase 7: Deep-review fidelity fixes

### Output artifacts

- [x] A healthy run still produces the full tree: `codigo_extraido.txt`,
      `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
      `frames_usados/`. Verified with
      `/private/tmp/text_extract_phase7_sample.mp4` ->
      `/private/tmp/text_extract_phase7_out`.
- [x] `frames_usados/` contains only frames from the current run; stale frame
      images from a prior execution are removed or replaced. Verified by
      adding `stale_frame.png`, rerunning, and confirming only `frame_0.png`
      remained.
- [x] Empty-OCR runs still write inspectable `ocr_raw.csv`,
      `codigo_extraido.txt`, and `relatorio_falhas.md` before exiting with code
      1. Verified with `/private/tmp/text_extract_phase7_empty_ocr.mp4`.
- [x] Output-writing ownership is clear: `prepare_output_tree()` owns output
      directory creation and run-scoped frame cleanup; `write_outputs()` writes
      the JSON, CSV, code, and Markdown report artifacts.

### Metadata

- [x] `VideoMetadata` rejects non-positive FPS. Verified with a direct
      Pydantic construction probe.
- [x] `VideoMetadata` rejects non-positive dimensions. Verified with a direct
      Pydantic construction probe.
- [x] `VideoMetadata` rejects non-positive frame counts when frame count is
      known. Verified with a direct Pydantic construction probe.
- [x] `VideoMetadata` rejects non-positive duration when duration is known.
      Verified with a direct Pydantic construction probe.
- [x] `metadata_video.json` remains compatible with the README contract.
      Verified in the healthy sample run with FPS, duration, resolution, total
      frames, codec, source, and sampling strategy fields.

### OCR / fidelity

- [x] Reconstructed code preserves indentation from OCR evidence where
      available. Verified with a positional `OCRWord` fixture that reconstructed
      `    return  value_name[0]`.
- [x] Reconstructed code preserves meaningful intra-line spacing instead of
      joining all OCR words with a single space. Verified with the same fixture
      preserving the double space in `return  value_name[0]`.
- [x] Important code characters remain preserved: parentheses, brackets,
      braces, quotes, colons, periods, commas, operators, and underscores.
      Verified with parser fixtures containing quotes, parentheses, colon,
      brackets, underscores, and operators, and by preserving OCR text verbatim
      after parsing.
- [x] Low-confidence content remains marked with `[OCR_UNCERTAIN]`; uncertain
      or missing content is not fabricated. Verified in the healthy sample run,
      which marked one low-confidence line and did not synthesize missing text.
- [x] Raw OCR evidence remains available in `ocr_raw.csv` with text, frame,
      time, confidence, and frame image path. Verified in the healthy and
      empty-OCR sample outputs.

### Line-number reconstruction

- [x] `parse_code_lines()` handles plain forms such as `12 print(...)`.
      Verified with a direct parser probe.
- [x] `parse_code_lines()` handles colon-separated forms such as
      `12:print(...)`. Verified with a direct parser probe.
- [x] `parse_code_lines()` handles pipe-separated forms such as
      `12|print(...)`. Verified with a direct parser probe.
- [x] Reconstruction handles gutter numbers and code text OCR'd as separate
      blocks or neighboring lines from the same frame. Verified with a
      positional paired-gutter fixture.
- [x] Missing numbered lines continue to be reported in `relatorio_falhas.md`
      with surrounding timestamps when available. Verified by unchanged
      `detect_missing_lines()` behavior and the healthy sample report showing
      zero gaps without fabricating lines.

### Error handling

- [x] `python extract_code_from_video.py --help` works even if OpenCV or other
      heavy runtime dependencies are unavailable. Verified by blocking `cv2`
      imports with an import hook and rendering `--help`.
- [x] Missing OpenCV during actual video processing exits with a clear,
      actionable dependency message. Verified by blocking `cv2` imports during
      a real sample run.
- [x] Missing `ffprobe` still warns and falls back to OpenCV when possible.
      Verified with a temporary `PATH` containing `tesseract` but no `ffprobe`.
- [x] Missing `tesseract` exits with a clear install hint. Verified with a
      temporary `PATH` that excludes the Tesseract binary.
- [x] Empty OCR has a distinct error message from "all frames discarded" and
      points the user to inspectable artifacts. Verified with separate
      empty-OCR and all-discarded sample videos.
- [x] Output directory permission failures still exit with code 1 and name the
      affected path. Verified with a temporary unwritable output directory.

### Offline (no network)

- [x] No implementation path performs a network call. Verified by inspection
      and an `rg` scan for network-related modules and URL patterns across
      `extract_code_from_video.py`, `README.md`, and `specs/`.
- [x] Validation can be run fully offline with local tools and local sample
      videos. Verified with generated local videos under `/private/tmp`.

### Technical

- [x] `ruff check .` passes. Verified with `.venv/bin/ruff check .`.
- [x] `ruff format --check .` passes. Verified with
      `.venv/bin/ruff format --check .`.
- [x] `mypy extract_code_from_video.py` passes. Verified with
      `.venv/bin/mypy extract_code_from_video.py`.
- [x] Real script run on a sample video completes without crashing and
      produces the full output tree. Verified with
      `.venv/bin/python extract_code_from_video.py --video ... --output ...`
      using `/private/tmp/text_extract_phase7_sample.mp4`.
