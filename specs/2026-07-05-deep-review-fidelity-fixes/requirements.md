# Requirements — Phase 7: Deep-review fidelity fixes

## Objective

Address the fidelity and reliability issues found during deep review while
preserving the locked README contract: extracted code must remain traceable to
OCR evidence, uncertain content must be marked honestly, and failed or empty
runs must still leave inspectable artifacts whenever possible.

This phase improves existing behavior rather than adding a new backend or
expanding the product surface.

## Scope

### Included

1. Preserve code spacing and indentation from OCR. Reconstruction must not
   rebuild code lines by joining OCR words with single spaces when the OCR
   engine provides enough positional or line text information to retain the
   original spacing.
2. Improve line-number reconstruction for real editor captures where gutter
   line numbers and code text may be OCR'd as separate blocks or separate
   lines.
3. Keep the CLI usable for `--help` and dependency guidance even when heavy
   runtime dependencies such as OpenCV are missing.
4. Broaden line-number parsing to common OCR/editor forms such as
   `12:print(...)` and `12|print(...)`, in addition to plain
   whitespace-separated line numbers.
5. Ensure `frames_usados/` contains only frames from the current run, with no
   stale images left over from previous executions.
6. On empty OCR, still write inspectable artifacts such as `ocr_raw.csv`,
   `codigo_extraido.txt`, and `relatorio_falhas.md` before exiting.
7. Add basic Pydantic constraints for metadata invariants: positive FPS,
   positive duration when known, positive dimensions, and positive frame counts
   when known.
8. Clarify the output-writing seam: either make `write_outputs()` responsible
   for the full output tree or rename/split it so its narrower responsibility
   is explicit.

### Excluded

- New OCR engines; PaddleOCR remains future work behind the existing engine
  interface.
- Cloud services, external APIs, or network-dependent validation.
- LLM-based code correction or review.
- Large architectural rewrites outside the existing README seams.
- Changing the output tree contract (`codigo_extraido.txt`,
  `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
  `frames_usados/`).

## Deliverables / output artifacts

- Updated `extract_code_from_video.py` implementing the Phase 7 fixes.
- The same runtime output tree defined by the README:
  `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
  `metadata_video.json`, and `frames_usados/`.
- Empty-OCR runs leave the core output files inspectable before returning a
  non-zero exit code.

## Decisions

| Decision | Choice |
| --- | --- |
| Scope | Include all Phase 7 roadmap items as-is (user confirmed) |
| Implementation approach | Decide from `specs/tech-stack.md`, `specs/mission.md`, and the existing README seams (user confirmed) |
| Runtime model | Keep a single local Python CLI using Typer, Pydantic models, OpenCV/NumPy/Pillow image processing, pytesseract behind the OCR interface, pandas CSV output, rapidfuzz consolidation, and rich logs |
| Fidelity priority | Preserve OCR evidence and spacing where available; never infer missing code content |
| Empty OCR behavior | Produce inspectable artifacts first, then fail clearly with exit code 1 |
| Frames cleanup | Treat `frames_usados/` as run-scoped output; remove or replace stale frame images at the start of a new write |
| Output seam | Prefer the least disruptive change: either expand `write_outputs()` to own all output artifacts or rename narrower helpers so call sites make ownership obvious |
| Validation | Standard checks only (user confirmed): ruff, mypy, and a real script run |

## Fidelity & error-handling rules

Per `mission.md` and the README:

- **Never invent code.** The tool may preserve, consolidate, omit, or mark OCR
  text as uncertain, but it must not synthesize content for unreadable lines.
- **Preserve source-like text.** Indentation, spacing, punctuation, operators,
  underscores, quotes, brackets, and colons are part of the extracted evidence.
- **Prefer uncertainty over fabrication.** Low-confidence or ambiguous lines
  use the existing `[OCR_UNCERTAIN]` marker with frame and timestamp evidence.
- **Report gaps explicitly.** If line numbers reveal a gap, record the missing
  line in `relatorio_falhas.md` instead of stitching neighboring content
  together.
- **Keep failures inspectable.** Missing dependencies, empty OCR, and late
  failures should leave any already-known metadata and raw outputs on disk when
  doing so is possible.
- **Stay offline.** No runtime path or validation step may send data to an
  external API.
