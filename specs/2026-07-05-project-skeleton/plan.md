# Plan — Phase 0: Project skeleton

## 1. Environment

- Create `.venv` with `python3 -m venv .venv`.
- Upgrade `pip`, then install the README dependency set: `opencv-python`,
  `numpy`, `pillow`, `pandas`, `tqdm`, `rich`, `rapidfuzz`, `scikit-image`,
  `pytesseract`, `typer`, `pydantic`.
- Install `ruff` and `mypy` into the same venv as quality tooling.
- Add `.gitignore` covering `.venv/`, `__pycache__/`, and `.mypy_cache/` /
  `.ruff_cache/`.

## 2. CLI entrypoint

- Create `extract_code_from_video.py` with a `typer` app and a single command.
- Options, all type-hinted:
  - `--video: Path` (required) — input video path.
  - `--output: Path` (required) — output directory.
  - `--crop-left / --crop-top / --crop-right / --crop-bottom: int | None`
    (optional, default `None`) — declared for Phase 2, unused for now.
- Use a `rich` console for all user-facing messages.

## 3. Input validation & output tree

- Validate `--video` exists and is a file; on failure print a clear
  `rich`-styled error naming the path and exit with code 1.
- Create the output directory and `frames_usados/` subdirectory
  (`mkdir(parents=True, exist_ok=True)`).
- Catch `PermissionError` / `OSError` on creation, and verify writability
  (e.g. `os.access` or a probe write); on failure print a clear error naming
  the directory and exit with code 1.
- On success, print a short confirmation of the created tree and note that
  the pipeline is not implemented yet (Phase 1).

## 4. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script runs:
  - missing video → clear error, exit code 1;
  - valid video path + fresh output dir → tree created, exit code 0;
  - unwritable output dir → clear error, exit code 1.
