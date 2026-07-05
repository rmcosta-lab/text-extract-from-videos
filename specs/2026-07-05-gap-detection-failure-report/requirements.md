# Requirements — Phase 5: Gap detection & failure report

## Objective

Make the tool's honesty visible: detect missing lines in the numbered
reconstruction (`detect_missing_lines()`) and generate `relatorio_falhas.md`,
the failure report mandated by the README — video summary, detected FPS,
frames analyzed and discarded, lines extracted, missing lines, low-confidence
passages, unextractable sections, and capture recommendations. This completes
the output tree defined in the README; nothing about sampling, preprocessing,
OCR, or reconstruction changes.

## Scope

### Included

- `detect_missing_lines()`: on the numbered path, flag every gap in the merged
  line numbering (e.g. line 32 followed by line 34 → line 33 missing). Each
  missing line is recorded with the timestamps of the surrounding extracted
  lines, phrased per the README:
  `Linha 45 possivelmente ausente entre os tempos 00:01:10.200 e 00:01:12.800.`
- `relatorio_falhas.md` written to the output directory on every run,
  containing all README-mandated sections:
  - video summary (path, resolution, duration, total frames, codec, source);
  - detected FPS and the sampling strategy used;
  - frames analyzed (sampled) and frames kept for OCR;
  - frames discarded for low sharpness (and, separately, near-duplicates);
  - number of lines extracted;
  - missing lines (numbered path; the unnumbered path states that gap
    detection needs line numbers);
  - low-confidence passages (the `[OCR_UNCERTAIN]` lines, with frame and
    timestamp);
  - unextractable sections (time spans whose sampled frames yielded no usable
    text — discarded or empty OCR);
  - capture recommendations (higher resolution, slower scroll, larger editor
    font, high-contrast theme), per the README.
- Wiring: `main()` already tracks `SelectionStats`; pass it (plus metadata,
  merged lines, and missing-line records) into output writing so the report is
  produced alongside the existing artifacts.

### Excluded (later phases)

- Full named-error-case polish and `rich` logging overhaul (Phase 6).
- README "short logic explanation + example command" section (Phase 6).
- PaddleOCR backend, vision-language models, LLM review (future).
- No change to sampling, preprocessing, blur/SSIM gating, OCR, or either
  reconstruction path.

## Deliverables / output artifacts

The output tree becomes complete per the README — one new file:

```
saida/
├── codigo_extraido.txt    # unchanged
├── relatorio_falhas.md    # NEW: the failure report
├── ocr_raw.csv            # unchanged
├── metadata_video.json    # unchanged
└── frames_usados/         # unchanged
```

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | All Phase 5 roadmap items as-is (user choice) |
| Approach | Claude decides per tech-stack/mission (user choice) |
| Gap detection input | The numbered-path `MergedLine` list, ordered by line number |
| Gap record | Pydantic model with the missing line number and the timestamps of the nearest extracted lines before and after the gap |
| Unnumbered path | `detect_missing_lines()` returns no gaps; the report says gap detection requires visible line numbers — it never guesses |
| Unextractable sections | Time spans where sampled frames produced no usable reads (discarded as blurry/duplicate or OCR came back empty), reported with start/end timestamps |
| Low-confidence passages | Exactly the merged lines flagged `uncertain`, listed with frame, timestamp, and original text |
| Report format | Markdown with one `##` section per README item; counts always present (zero is stated, not omitted) |
| Report data | Aggregated in a pydantic report model built from `VideoMetadata`, `SelectionStats`, merged lines, and gap records — no recomputation from disk |
| Recommendations | Static README list, always included; stat-conditioned notes (e.g. many blurry frames → slow the scroll) may be added on top |
| Language | Report body in Portuguese, matching `relatorio_falhas.md`, the marker format, and the README's example phrasing |
| Validation | Standard checks only: `ruff`, `mypy`, real script run (user choice) |

## Fidelity & error-handling rules

- **Never invent code.** A gap is *reported*, never stitched over: missing
  line numbers are listed in the report and remain absent from
  `codigo_extraido.txt`.
- Honest reporting: every discarded frame, missing line, and low-confidence
  passage is surfaced in `relatorio_falhas.md` — counts of zero are stated
  explicitly, not hidden.
- Every reported item is traceable: missing lines carry surrounding
  timestamps; low-confidence passages carry frame and timestamp mapping back
  to `frames_usados/` and `ocr_raw.csv`.
- Missing-line phrasing follows the README example verbatim in shape:
  `Linha N possivelmente ausente entre os tempos <before> e <after>.` — a gap
  at the start or end of the numbering, where one side has no neighbor, says
  so rather than fabricating a timestamp.
- Deterministic: the same run data always produces the same report.
- Local only: no network calls at runtime.
- All Phase 0–4 error cases preserved (missing video, unwritable output,
  missing `tesseract`, undetectable FPS, empty selection, invalid crop).
- Empty OCR or zero merged lines never crashes report generation — the report
  is still written, stating that nothing could be extracted.
