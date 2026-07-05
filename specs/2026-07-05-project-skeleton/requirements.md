# Requirements — Phase 0: Project skeleton

## Objective

Stand up a runnable project skeleton: a Python virtualenv with all locked
dependencies installed, and an `extract_code_from_video.py` entrypoint with a
`typer` CLI that validates its inputs and creates the full output directory
tree. No video processing happens yet — this phase only proves the tool can be
invoked, fails clearly on bad input, and lays down the output structure every
later phase writes into.

## Scope

### Included

- `.venv` virtualenv with the dependency set from `README.md` installed
  (`opencv-python`, `numpy`, `pillow`, `pandas`, `tqdm`, `rich`, `rapidfuzz`,
  `scikit-image`, `pytesseract`, `typer`, `pydantic`), plus `ruff` and `mypy`
  as quality tooling.
- `extract_code_from_video.py` with a `typer` CLI exposing:
  - `--video` (required): path to the input video.
  - `--output` (required): path to the output directory.
  - `--crop-left`, `--crop-top`, `--crop-right`, `--crop-bottom` (optional):
    declared now, unused until Phase 2.
- Creation of the output directory tree defined in the README:
  `codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
  `metadata_video.json` are not yet produced — only the directory and the
  `frames_usados/` subdirectory are created in this phase.
- Clear, actionable failures:
  - video path does not exist or is not a file;
  - output directory cannot be created or is not writable.

### Excluded

- Any video reading, metadata extraction, frame sampling, OCR, reconstruction,
  or report generation (Phases 1+).
- Crop flag behavior (Phase 2 wires them into preprocessing).
- Handling of `ffprobe`/`tesseract` absence (Phase 1 introduces those calls;
  Phase 6 polishes all error cases).

## Deliverables / output artifacts

- `.venv/` (git-ignored) with all dependencies installed.
- `extract_code_from_video.py` — runnable CLI entrypoint.
- On a successful run: `<output>/` and `<output>/frames_usados/` exist.
- `.gitignore` covering at least `.venv/` and `__pycache__/`.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| CLI framework | `typer` | Locked in `tech-stack.md`; argparse rejected. |
| Scope of roadmap bullets | All three included as-is | User confirmed no adjustments. |
| Implementation approach | Claude decides per `tech-stack.md` / `mission.md` | User delegated. |
| Output artifacts this phase | Directory tree only (`<output>/`, `frames_usados/`) | File artifacts arrive with the pipeline in Phase 1. |
| Quality gates | `ruff`, `mypy`, real script run | Standard checks; user added none. |

## Fidelity & error-handling rules

Per `mission.md` and the README's error cases, as they apply to this phase:

- **Never invent output.** The skeleton produces no extracted-code content;
  it must not create placeholder `codigo_extraido.txt` or report files that
  could be mistaken for results.
- **Missing video** → exit with a non-zero status and a clear message naming
  the path that was not found.
- **Unwritable output directory** → exit with a non-zero status and a clear
  message naming the directory and the permission problem.
- **Local only.** No network calls; everything runs offline.
- Errors are reported via `rich`-styled messages, not raw tracebacks.
