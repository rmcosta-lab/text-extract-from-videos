# Validation — Phase 8: Segment parameters & real-case extraction review

### Output artifacts

- [x] `codigo_extraido.txt` is produced (`/tmp/text-extract-phase8-full` and
      `/tmp/text-extract-phase8-segment` real runs).
- [x] `relatorio_falhas.md` is produced (`/tmp/text-extract-phase8-full` and
      `/tmp/text-extract-phase8-segment` real runs).
- [x] `ocr_raw.csv` is produced (`/tmp/text-extract-phase8-full` and
      `/tmp/text-extract-phase8-segment` real runs).
- [x] `metadata_video.json` is produced (`/tmp/text-extract-phase8-full` and
      `/tmp/text-extract-phase8-segment` real runs).
- [x] `frames_usados/` contains only frames from the current run
      (`prepare_output_tree()` clears stale frames; segment run contains only
      `frame_30.png` through `frame_105.png` candidates).
- [x] The extraction-parameters JSON artifact is produced in the output
      directory as `extraction_parameters.json`.

### Metadata

- [x] Existing video metadata remains accurate: FPS, duration, resolution, total
      frames, codec when available, and sampling strategy
      (`metadata_video.json` reports 3840x2160, 29.9986 fps, 35.267s,
      1058 frames, `hevc`, and segment-aware sampling strategy).
- [x] The extraction-parameters artifact records requested start/end values
      (`requested_start_time`, `requested_end_time`, and parsed seconds).
- [x] The extraction-parameters artifact records effective resolved start/end
      values (`effective_start_seconds`, `effective_end_seconds`, and formatted
      timestamps).
- [x] The extraction-parameters artifact records crop settings used for the run
      (`crop.left/top/right/bottom`).
- [x] Segment timestamps remain tied to the original video timeline (bounded
      run `00:00:01` to `00:00:04` sampled original frames 30, 45, 60, 75, 90,
      and 105).

### OCR / fidelity

- [x] Segment-bounded runs process only frames inside the effective interval
      (bounded run saved only frames 30, 45, 60, 75, 90, and 105).
- [x] Adaptive sampling by FPS still applies inside the selected segment
      (`adaptive_fps=30,step=15` and six candidates for the 1s-4s interval).
- [x] Reconstruction still preserves indentation and code-significant
      characters when OCR provides them (word-geometry reconstruction path
      remains in place and real runs produced code output).
- [x] Low-confidence or unreadable lines are marked with `[OCR_UNCERTAIN]`
      instead of guessed (full run marked 96 uncertain lines; segment run
      marked 25).
- [x] Real-case frames where a line is followed by code text are reviewed for
      extraction quality (`real-case-review.md`, including `frame_30.png` and
      `frame_225.png`).
- [x] Any parsing or grouping change from the real-case review improves
      fidelity without fabricating code (frame-local outlier filtering drops
      isolated impossible line-number labels instead of inventing replacements;
      full run missing-line report reduced from the previous 7667 false gaps to
      288).

### Error handling

- [x] Invalid timestamp input fails with a clear message (`--start-time abc`).
- [x] Negative start time fails with a clear message (`--start-time -1`).
- [x] End time less than or equal to start time fails with a clear message
      (`--start-time 00:00:05 --end-time 00:00:04`).
- [x] Segment bounds beyond detected duration fail or are reported according to
      the chosen validation behavior (`--end-time 00:01:00` fails against
      00:00:35.267 duration).
- [x] Missing `ffprobe`, missing `tesseract`, undetectable FPS, missing video,
      empty OCR, and unwritable output directory handling remain clear
      (simulated missing `ffprobe` fallback, missing `tesseract`, missing video,
      empty OCR with a generated sharp non-text video, unwritable output dir;
      undetectable FPS branch remains an explicit unchanged `_fail()` path).

### Offline (no network)

- [x] The run performs all extraction locally (real runs use local ffprobe,
      OpenCV, Tesseract, and local files).
- [x] No external API or network dependency is introduced (source inspection;
      no network code or dependency added).

### Technical

- [x] `ruff` passes (`.venv/bin/ruff check extract_code_from_video.py` and
      `.venv/bin/ruff format --check extract_code_from_video.py`).
- [x] `mypy` passes (`.venv/bin/mypy extract_code_from_video.py`).
- [x] A real script run passes (`sample-video/IMG_5430.MOV` to
      `/tmp/text-extract-phase8-full`).
- [x] A real or representative script run with segment parameters passes
      (`sample-video/IMG_5430.MOV --start-time 00:00:01 --end-time 00:00:04`
      to `/tmp/text-extract-phase8-segment`).
