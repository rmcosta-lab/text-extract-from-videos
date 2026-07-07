# Plan — Phase 13: Reproducible tooling & pipeline tests

1. Pin the gates in `pyproject.toml`: ruff (`py313`, `E,W,F,I,UP,B,SIM,PL,RUF`
   + documented ignores + `allowed-confusables = ["×"]`), mypy
   (`disallow_untyped_defs` et al., `files` covering entrypoints and tests),
   pytest (`testpaths`, `addopts`).
2. Fix what the pinned ruleset surfaces, without behavior changes:
   `itertools.pairwise` for successive-pair `zip`s, `EngineName` → `StrEnum`
   (all usages are identity comparisons/defaults — verified), import order,
   four long lines rewrapped, one test `str.split` with `maxsplit`.
3. Add `test_extract_code_from_video.py`: pure-model tests for the
   reconstruction pipeline (timestamps, sampling window, line parsing,
   line-number detection, merging/uncertainty incl. the Phase 12 gates,
   time-ordered dedup, gap detection, report entry collapse, spacing
   reconstruction) plus `tmp_path` tests for marker placement and
   stale-artifact clearing.
4. Clean `requirements.txt` (drop `tqdm`, annotate `pillow`).
5. Gates: `ruff check .`, `ruff format --check .`, `mypy`, `pytest` (66),
   plus `--help` smoke and `EngineName` round-trip on the paddle venv.
