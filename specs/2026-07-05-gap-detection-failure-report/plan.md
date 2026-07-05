# Plan — Phase 5: Gap detection & failure report

## 1. Data models

- Add a `MissingLine` pydantic model: the missing `line_number`, plus the
  timestamps (formatted and in seconds) and frame numbers of the nearest
  extracted lines before and after the gap; either side optional when the gap
  touches the start or end of the numbering.
- Add a `FailureReport` pydantic model aggregating everything the report
  renders: video metadata, sampling strategy, `SelectionStats` counts, lines
  extracted, the `MissingLine` list, the uncertain `MergedLine` list, and the
  unextractable time spans. Built in memory from run data — no recomputation
  from disk.

## 2. Gap detection — `detect_missing_lines()`

- New function
  `detect_missing_lines(merged: list[MergedLine]) -> list[MissingLine]`
  alongside `merge_ocr_results()`.
- Walk the numbered merged lines in line-number order; every jump greater
  than 1 yields one `MissingLine` per absent number, carrying the surrounding
  lines' timestamps.
- Reads without line numbers (the unnumbered path) produce an empty result —
  gap detection never guesses where numbering is absent.
- Empty or single-line input returns an empty list without crashing.

## 3. Unextractable sections

- While tracking selection in `main()` (or a small helper over the per-frame
  outcomes), record time spans where consecutive sampled frames yielded no
  usable text — discarded as blurry/duplicate or OCR returned empty — as
  (start, end) formatted timestamps.
- Keep it simple and honest: a span is reported as unextractable only from
  observed frame outcomes, never inferred content.

## 4. Report generation & output wiring

- New function `write_failure_report(report: FailureReport, output: Path)`
  (or an extension of `write_outputs()`) rendering `relatorio_falhas.md` in
  Portuguese with one `##` section per README item: resumo do vídeo, FPS
  detectado, frames analisados, frames descartados por baixa nitidez (and
  near-duplicates), linhas extraídas, linhas faltantes, trechos com baixa
  confiança, trechos impossíveis de extrair, recomendações de captura.
- Missing lines rendered per the README phrasing:
  `Linha 45 possivelmente ausente entre os tempos 00:01:10.200 e 00:01:12.800.`
- Zero counts stated explicitly ("Nenhuma linha faltante detectada."), never
  omitted; the unnumbered path states that gap detection requires visible
  line numbers.
- Recommendations: the README's static list (higher resolution, slower
  scroll, larger font, high-contrast theme), plus stat-conditioned notes
  (e.g. high blurry-discard share → reinforce slower scrolling).
- `main()`: build the `FailureReport` from `metadata`, `SelectionStats`,
  merged lines, and `detect_missing_lines()`; write it with the other
  artifacts; the `rich` summary mentions the report path and the missing /
  uncertain counts.

## 5. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on one actual video: `relatorio_falhas.md` is produced with
  every README section present; on a numbered video with a gap, the missing
  line appears with surrounding timestamps and is absent from
  `codigo_extraido.txt`.
- All previous artifacts unchanged in shape; previous error cases intact.
- Validate every checkbox in `validation.md`.
