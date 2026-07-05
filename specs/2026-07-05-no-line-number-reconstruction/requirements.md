# Requirements — Phase 4: No-line-number reconstruction

## Objective

Replace the Phase 1 naive concatenation fallback with a real reconstruction for
videos whose editor does **not** show line numbers: order the reads by video
time, detect the overlap between consecutive frames caused by scrolling, drop
the scroll-induced duplicates, and consolidate repeated reads of the same
on-screen line with `rapidfuzz` fuzzy matching — picking the best read by the
same frequency / confidence / sharpness criteria as Phase 3. Raw artifacts
(`ocr_raw.csv`, `frames_usados/`, `metadata_video.json`) stay untouched — this
phase changes how `codigo_extraido.txt` is built when line numbers are absent.

## Scope

### Included

- Time-ordered reconstruction: reads are processed frame by frame in ascending
  video time; within a frame, lines keep their top-to-bottom on-screen order.
- Scroll-overlap detection: for each new frame, align its leading lines against
  the tail of the code reconstructed so far using `rapidfuzz` similarity; the
  overlapping region is consolidated, only the genuinely new lines are
  appended.
- Fuzzy consolidation of repeats: reads of the same on-screen line across
  frames (similarity above a threshold constant) collapse to one output line;
  the winner is chosen by frequency of identical content, then confidence,
  then frame sharpness — same criteria as the numbered path.
- `[OCR_UNCERTAIN]` markers on this path too: when the winning read of a line
  is below the confidence threshold, it is preceded by
  `# [OCR_UNCERTAIN] frame=1234 time=00:01:23.400 texto_original="..."`.
  **Never invent code** — uncertain content is marked, not fixed or guessed.
- Path selection: `has_line_numbers()` keeps deciding; when false (or when no
  reads carry a number), the new time-ordered reconstruction runs instead of
  the naive concatenation. The numbered path from Phase 3 is unchanged.

### Excluded (later phases)

- `detect_missing_lines()`, gap records, and `relatorio_falhas.md` (Phase 5).
- Full named-error-case polish and `rich` logging overhaul (Phase 6).
- PaddleOCR backend (future).
- No change to sampling, preprocessing, blur/SSIM gating, or the numbered
  reconstruction path.

## Deliverables / output artifacts

Same tree as Phase 3 — no new files, one changed file:

```
saida/
├── codigo_extraido.txt    # time-ordered, dedup'd reconstruction when no numbers
├── ocr_raw.csv            # unchanged: raw per-frame reads preserved
├── metadata_video.json    # unchanged
└── frames_usados/         # unchanged
```

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | All Phase 4 roadmap items as-is (user choice) |
| Approach | Claude decides per tech-stack/mission (user choice) |
| Ordering | Frames in ascending video time; lines within a frame in on-screen order |
| Overlap detection | Fuzzy alignment of the new frame's lines against the tail of the accumulated reconstruction (`rapidfuzz` ratio, whitespace-normalized for comparison) |
| Similarity threshold | Module-level constant (rapidfuzz ratio 0–100); at/above → same line, below → new line |
| Best-read selection | Same as Phase 3: frequency of identical content, then confidence, then frame sharpness |
| Winner content | Emitted verbatim — always one actual OCR read, never a blend of reads |
| Uncertainty | Same `OCR_UNCERTAIN` confidence threshold and marker format as Phase 3 |
| Naive concatenation | Removed as a reachable path — the unnumbered path now always reconstructs by time |
| Raw CSV | Unchanged — raw reads stay inspectable and traceable |
| Validation | Standard checks only: `ruff`, `mypy`, real script run (user choice) |

## Fidelity & error-handling rules

- **Never invent code.** Consolidating multiple reads of the *same* on-screen
  line is allowed and encouraged; synthesizing content no frame produced is
  not. Every output line is one of its actual OCR reads, verbatim.
- Fuzzy matching is used only to decide that two reads are the same line —
  never to blend, average, or repair their text.
- A blank or an `[OCR_UNCERTAIN]` marker is always preferable to a fabricated
  line; markers carry frame and timestamp so any result traces back to
  `frames_usados/` and `ocr_raw.csv`.
- When overlap is ambiguous (similarity near the threshold), prefer keeping
  both reads (a duplicate) over dropping a line: losing real code is worse
  than a repeated line.
- Deterministic: given the same OCR rows, reconstruction produces the same
  output — ties are broken by fixed, ordered criteria.
- Local only: no network calls at runtime.
- All Phase 0–3 error cases preserved (missing video, unwritable output,
  missing `tesseract`, undetectable FPS, empty selection, invalid crop).
- Empty OCR or a single frame never crashes the reconstruction — zero or one
  frame of reads simply passes through in time order.
