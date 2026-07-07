# Validation — Phase 13: Reproducible tooling & pipeline tests

### Tooling

- [x] `pyproject.toml` is committed; `ruff check .`, `ruff format --check .`,
      and bare `mypy` (config-driven files) all pass from a clean checkout.
- [x] The ruleset includes `PL` so the existing `# noqa: PLC0415` markers are
      meaningful, and the config documents every ignore.
- [x] `requirements.txt` no longer lists `tqdm`; `pillow` is annotated.

### Tests

- [x] `pytest` collects and passes both suites (29 existing + 37 new = 66).
- [x] The new suite needs no video/OpenCV/OCR backend (pure models + tmp_path).
- [x] Phase 12 behaviors are covered: per-engine floors, disagreement gate,
      empty-vs-content, leading missing-run collapse, near-duplicate outcome
      semantics via `unextractable_sections`, stale-artifact clearing.

### Technical

- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy` passes (stricter flags: disallow_untyped_defs et al.).
- [x] `pytest` passes (66 tests).
