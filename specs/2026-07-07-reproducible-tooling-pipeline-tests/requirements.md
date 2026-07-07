# Requirements — Phase 13: Reproducible tooling & pipeline tests

## Objective

Make the quality gates reproducible from the repository and give the
fidelity-critical reconstruction logic a regression net. The deep review found
that no ruff/mypy configuration was committed (the `# noqa: PLC0415` markers
imply a non-default ruleset, so "ruff and mypy pass" meant different things on
different machines) and that the main pipeline — the code where silent
corruption would happen — had zero tests, while `test_suggest_crop.py` proved
the pure-function testing pattern works.

## Scope

### Included

- **`pyproject.toml`** (tool config only — the project stays two script
  entrypoints, not an installable package):
  - ruff: `target-version = "py313"`, ruleset `E,W,F,I,UP,B,SIM,PL,RUF`
    (PL justifies the existing `noqa: PLC0415` lazy imports), with the
    conventional ignores (`PLR2004`, `PLR091x`) and `allowed-confusables`
    for the `×` in dimension strings.
  - mypy: `python_version = 3.13`, `disallow_untyped_defs`,
    `disallow_incomplete_defs`, `check_untyped_defs`, `no_implicit_optional`,
    `warn_redundant_casts`, with `files` covering both entrypoints and tests.
  - pytest: `testpaths`/`addopts`.
- Fix the small violations the pinned ruleset surfaces (long lines,
  `itertools.pairwise`, `StrEnum`, import order) — no behavior changes.
- **`test_extract_code_from_video.py`**: pure-function tests (no video, no
  OpenCV, no OCR backend) for `_parse_timestamp`, `_format_time`,
  `_candidate_frame_window`, `parse_code_lines` (plain/separator/gutter-pair
  forms, outlier demotion), `has_line_numbers`, `merge_ocr_results` /
  `_best_read` (frequency, tie-breaks, per-engine floors, disagreement gate,
  empty-vs-content rules from Phase 12), `reconstruct_by_time` (overlap
  dedup, fuzzy variants, no-overlap append), `detect_missing_lines`,
  `_missing_line_entries` (leading-run collapse), `unextractable_sections`,
  `_reconstruct_words` (indentation/gap preservation), plus `tmp_path` tests
  for `write_extracted_code` marker placement and `prepare_output_tree`
  stale-artifact clearing.
- **`requirements.txt` cleanup**: drop unused `tqdm`; annotate `pillow` as a
  pytesseract dependency.

### Excluded

- No CI workflow (can be a later phase if desired).
- No packaging (`[project]` table / build backend).
- No refactoring beyond what the pinned ruleset requires (Phase 14 owns the
  quality refactors).
