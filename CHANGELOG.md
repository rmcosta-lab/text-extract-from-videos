# Changelog

## 2026-07-05

- Complete Phase 1 — thin vertical slice: end-to-end pipeline from video metadata (`ffprobe` with OpenCV fallback → `metadata_video.json`), fixed-step frame sampling, and whole-frame OCR via a `pytesseract` engine behind an OCR interface, to raw artifacts (`ocr_raw.csv`, naive `codigo_extraido.txt`, `frames_usados/`); add phase spec (`specs/2026-07-05-thin-vertical-slice/`).
- Complete Phase 0 — project skeleton: `typer` CLI (`extract_code_from_video.py`) with `--video`/`--output` and declared crop flags, output directory tree creation, and clear errors for missing video or unwritable output; add `.gitignore` and phase spec (`specs/2026-07-05-project-skeleton/`).
- Align phase/review skills with the Python CLI OCR project scope.
- Initialize project with README, mission, roadmap, and tech stack specifications; add changelog and deep review skills.
- Initial commit.
