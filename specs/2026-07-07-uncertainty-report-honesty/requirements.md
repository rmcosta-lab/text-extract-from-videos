# Requirements — Phase 12: Uncertainty & report honesty

## Objective

Make the honesty mechanism trustworthy in practice. The July 2026 deep review
of `main` found a real PaddleOCR run whose `codigo_extraido.txt` contained
visibly garbled lines (`et n ee`, `inp.jurosgzaptalizados`) with **zero**
`[OCR_UNCERTAIN]` markers, while `relatorio_falhas.md` claimed "Trechos com
baixa confiança: 0". The single Tesseract-calibrated confidence cutoff (60)
never fires for Paddle, whose scores saturate at 95+ even for garbage
(minimum row confidence in the evidence run: 95.58).

## Scope

### Included

- **Per-engine uncertainty floor**: keep 60 for Tesseract; add a Paddle floor
  (95) that catches genuinely weak Paddle reads. The floor is selected at the
  single engine seam in `main()` and threaded into merging.
- **Engine-independent disagreement gate**: a merged line is flagged
  `[OCR_UNCERTAIN]` when fewer than half of its reads fuzzy-match the winning
  content (with at least 3 reads) — saturated-confidence garbage diverges
  across frames, so disagreement catches what confidence cannot.
- **Empty reads never outvote content**: a gutter-only read (`content=""`)
  is evidence the content was unreadable in that frame, not that the line is
  blank. `_best_read()` picks the winner among non-empty reads when any
  exist; an empty winner contested by content becomes impossible, and a
  weakly-supported non-empty winner is caught by the disagreement gate.
- **Near-duplicate discards are "covered", not "unextractable"**: their
  content was captured from the accepted neighbor frame, so they no longer
  open or extend spans in "Trechos impossíveis de extrair".
- **Run-scoped output tree**: `prepare_output_tree()` removes all five
  run artifacts (`codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
  `metadata_video.json`, `extraction_parameters.json`) up front, so a mid-run
  failure can never leave stale outputs mixed with fresh metadata.
- **Report polish**:
  - Collapse a leading run of never-shown line numbers (numbering starting
    above 1) into a single range entry instead of one entry per number.
  - Report how many reads were excluded from the numbered reconstruction for
    having no detectable line number (raw text remains in `ocr_raw.csv`).
- **Offline honesty for Paddle**: warn actionably when no cached PaddleOCR
  models are found (a first run would download them from the network).
- **`suggest_crop.py` sampling fix**: an explicit `--start-time 0` is
  respected exactly (`start_frame` becomes `int | None`; the falsy-int `or`
  is removed).

### Excluded

- No changes to OCR engines' recognition logic or preprocessing.
- No blending/repair of reads — fidelity rules unchanged.
- No new CLI options.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Paddle floor | 95.0 | Paddle scores saturate ≥95 even for garbage; the floor catches only genuinely weak reads, the disagreement gate handles saturated garbage |
| Disagreement gate | winner fuzzy-support share < 0.5 over ≥ 3 reads | Reuses `_same_line()`; tolerant of near-identical OCR variants, engine-independent |
| Empty-read rule | winner chosen among non-empty reads when any exist | "Number seen, content unreadable" must not assert a blank line |
| Near-duplicates | counted as covered (usable) in frame outcomes | Their content is by definition already captured from the accepted neighbor |
| Paddle models missing | warning, not failure | The cache-dir heuristic can be wrong; blocking a valid setup is worse than warning |
| Leading missing lines | collapsed at rendering, model unchanged | The count stays honest; only the listing is condensed |
