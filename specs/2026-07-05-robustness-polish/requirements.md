# Requirements — Phase 6: Robustness & polish

## Objective

Make the tool resilient and pleasant to run: every named error case from the
README exits with a clear, actionable message; `rich` logging/progress covers
the whole pipeline; and the README gains a short logic explanation plus an
example command. No new extraction behavior — this phase hardens and documents
what already exists.

## Scope

### Included

1. **Error handling for all named cases** (README "Tratar erros comuns"):
   - missing / non-file video path;
   - `ffprobe` not installed (fall back to OpenCV with a warning);
   - `tesseract` not installed;
   - video with undetectable FPS;
   - **empty OCR** — frames were sampled and OCR ran, but no text was
     recognized in any frame (distinct from "all frames discarded", which is
     already handled);
   - output directory without write permission.
   Each case must exit with code 1 and a message that states what went wrong
   and what the user can do about it. An audit of the existing handlers is in
   scope: messages reviewed for clarity/actionability, and every case
   exercised.
2. **`rich` logging/progress throughout**: every long-running stage (metadata,
   frame sampling + OCR, reconstruction, output writing) reports progress or a
   completion line via the existing `Console` instances; warnings and errors
   keep the current `[bold yellow]`/`[bold red]` style.
3. **README additions**: a short explanation of the pipeline logic and an
   example run command (the README already lists deliverable 2 "Exemplo de
   comando de execução" and 3 "Explicação curta da lógica").

### Excluded

- New OCR backends (PaddleOCR remains future work).
- Changes to sampling, preprocessing, reconstruction, or report logic.
- Automated test suite (validation remains ruff / mypy / real script run).
- Any network-dependent behavior.

## Deliverables / output artifacts

- Updated `extract_code_from_video.py` (error handling + logging only).
- Updated `README.md` with the logic explanation and example command.
- No change to the output tree contract (`codigo_extraido.txt`,
  `relatorio_falhas.md`, `ocr_raw.csv`, `metadata_video.json`,
  `frames_usados/`).

## Decisions

| Decision | Choice |
| --- | --- |
| Scope | All three roadmap items as-is (user confirmed) |
| Error exit mechanism | Keep the existing `_fail()` → `typer.Exit(code=1)` pattern; no new exception hierarchy beyond `OCREngineUnavailableError` |
| Logging | Keep module-level `rich.Console` (stdout) + stderr console; extend coverage rather than introduce `logging`/`tqdm` |
| Empty-OCR semantics | OCR rows exist but no usable text/reads → fail with a clear message **after** still writing `metadata_video.json` and `frames_usados/` where possible, so the run is inspectable |
| README language | Keep the README's existing mixed style; new sections written to match the surrounding document |
| Validation | Standard checks only (user confirmed): ruff, mypy, real script run |

## Fidelity & error-handling rules

Per `mission.md` and the README error cases:

- **Never invent code.** Robustness work must not change extraction output for
  a healthy run.
- **Honest reporting.** Error paths must not silently swallow information: a
  failed run says exactly which stage failed and why; a degraded run (e.g.
  ffprobe missing) warns and states the fallback used.
- Error messages are **actionable**: name the missing tool and how to install
  it (`brew install ffmpeg` / `brew install tesseract`), the unwritable path,
  or the video property that could not be read.
- All failures exit with a non-zero code; partial artifacts already written
  are left on disk for inspection, never deleted.
- Everything runs offline; no error path may attempt a network call.
