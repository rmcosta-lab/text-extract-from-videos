# Requirements — Phase 3: Line-number-aware reconstruction

## Objective

Turn the naive frame-text concatenation into a real reconstruction for videos
whose editor shows line numbers: parse the leading line number off each OCR'd
line, consolidate the multiple reads of the same line collected across frames,
pick the best read by confidence / sharpness / frequency, order the result by
line number, and flag low-confidence lines with `[OCR_UNCERTAIN]` markers.
Raw artifacts (`ocr_raw.csv`, `frames_usados/`, `metadata_video.json`) stay
untouched — this phase changes how `codigo_extraido.txt` is built.

## Scope

### Included

- `parse_code_lines()`: split each OCR frame text into lines, detect a leading
  line number, and separate it from the content. Produces typed per-line reads
  carrying line number (when detected), content, and provenance (frame, time,
  confidence, sharpness).
- Per-line confidence: the OCR engine result is extended to expose per-line
  reads (text + confidence), so merging is not limited to one frame-level
  confidence value. The engine interface stays a single `image -> OCR result`
  method.
- Frame sharpness (Laplacian variance, already computed for the blur gate) is
  recorded per accepted frame so the merge can use it as a quality signal.
- Line-numbers-present detection: a simple heuristic over all parsed reads
  decides whether the video shows line numbers; the numbered reconstruction
  runs only when it does.
- `merge_ocr_results()`: group reads by detected line number; choose the best
  version of each line by frequency of identical content, then confidence,
  then frame sharpness; order the final code by line number.
- `[OCR_UNCERTAIN]` markers: when the best read of a line is below the
  confidence threshold, the output line is preceded by
  `# [OCR_UNCERTAIN] frame=1234 time=00:01:23.400 texto_original="..."`.
  **Never invent code** — uncertain content is marked, not fixed or guessed.
- `codigo_extraido.txt` becomes the merged, line-number-ordered reconstruction
  when numbers are detected; without detected numbers, the Phase 1 naive
  concatenation is kept (time-ordered reconstruction is Phase 4).

### Excluded (later phases)

- No-line-number reconstruction: time ordering, scroll dedup, `rapidfuzz`
  fuzzy consolidation (Phase 4).
- `detect_missing_lines()`, gap records, and `relatorio_falhas.md` (Phase 5)
  — numbering gaps simply remain gaps in this phase's output.
- Full named-error-case polish and `rich` logging overhaul (Phase 6).
- PaddleOCR backend (future).

## Deliverables / output artifacts

Same tree as Phase 2 — no new files, one changed file:

```
saida/
├── codigo_extraido.txt    # merged, ordered by line number when numbers detected
├── ocr_raw.csv            # unchanged: raw per-frame reads preserved
├── metadata_video.json    # unchanged
└── frames_usados/         # unchanged
```

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | All Phase 3 roadmap items as-is (user choice) |
| Approach | Claude decides per tech-stack/mission (user choice) |
| Per-line data | `OCRResult` gains per-line reads (text + confidence); interface stays one `recognize()` method |
| Line-number parsing | Regex on each line for a leading integer (with optional separator); number stripped from content |
| Numbers-present heuristic | Numbered reconstruction only when a clear majority of non-empty reads carry a plausible, mostly increasing leading number |
| Best-read selection | Frequency of identical content first, then confidence, then frame sharpness |
| Uncertainty threshold | Module-level confidence-threshold constant; best read below it → `[OCR_UNCERTAIN]` marker line |
| Marker format | `# [OCR_UNCERTAIN] frame=<n> time=<HH:MM:SS.mmm> texto_original="..."` exactly as in `mission.md` |
| No numbers detected | Keep Phase 1 naive concatenation (Phase 4 owns that path) |
| Raw CSV | Unchanged — raw reads stay inspectable and traceable |
| Validation | Standard checks only: `ruff`, `mypy`, real script run (user choice) |

## Fidelity & error-handling rules

- **Never invent code.** Consolidating multiple reads of the *same* line is
  allowed and encouraged; synthesizing content no frame produced is not. The
  merged output for a line is always one of its actual OCR reads, verbatim.
- A blank or an `[OCR_UNCERTAIN]` marker is always preferable to a fabricated
  line; low-confidence lines are marked with their frame and timestamp so any
  result traces back to `frames_usados/` and `ocr_raw.csv`.
- Numbering gaps are not stitched over: missing lines are simply absent from
  the output (explicit gap records arrive with Phase 5's report).
- Deterministic: given the same OCR rows, merging produces the same output —
  ties are broken by fixed, ordered criteria.
- Local only: no network calls at runtime.
- All Phase 0–2 error cases preserved (missing video, unwritable output,
  missing `tesseract`, undetectable FPS, empty selection, invalid crop).
- Empty or number-free OCR never crashes the reconstruction — it falls back to
  the naive path rather than failing or emitting fabricated structure.
