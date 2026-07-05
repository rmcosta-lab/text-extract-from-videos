# Requirements — Phase 2: Frame preprocessing & selection

## Objective

Improve OCR input quality and cut wasted work: preprocess each candidate frame
before OCR, skip blurry scroll frames and near-duplicate frames, adapt the
sampling step to the detected FPS, and wire the declared `--crop-*` flags into
the pipeline. The output artifacts stay the same as Phase 1 — this phase changes
*which* frames are OCR'd and *what image* the engine sees, not the output tree.

## Scope

### Included

- `preprocess_frame()`: crop (when requested) → grayscale → resize (upscale to
  improve OCR) → adaptive/Otsu threshold → sharpen/denoise when needed. OCR
  receives the preprocessed image instead of the raw frame.
- `is_frame_blurry()`: Laplacian variance sharpness score against a threshold;
  blurry frames are skipped (not OCR'd, not saved to `frames_usados/`) and
  counted for the future failure report.
- Near-duplicate skipping: SSIM (`scikit-image`) between the current candidate
  and the last *accepted* frame; frames above the similarity threshold are
  skipped and counted.
- Adaptive `sample_step` chosen from the detected FPS (30 / 60 / 120 tiers);
  the strategy string recorded in `metadata_video.json` reflects it
  (e.g. `"adaptive_fps=60,step=30"`).
- `--crop-left/-top/-right/-bottom` flags applied as the first preprocessing
  step; no crop flags → whole frame (Phase 1 behavior).
- Frames saved to `frames_usados/` are the images actually given to OCR
  (post-preprocessing), keeping every CSV row traceable to what the engine saw.

### Excluded (later phases)

- `parse_code_lines()`, `merge_ocr_results()`, `[OCR_UNCERTAIN]` markers
  (Phase 3), time-based reconstruction and fuzzy dedup of *text* (Phase 4).
- `detect_missing_lines()` and `relatorio_falhas.md` (Phase 5) — skip counts
  are tracked internally but the report file is not yet emitted.
- Full named-error-case polish and `rich` logging overhaul (Phase 6).
- PaddleOCR backend (future).

## Deliverables / output artifacts

Same tree as Phase 1 — no new files:

```
saida/
├── codigo_extraido.txt    # naive concatenation, now over selected frames only
├── ocr_raw.csv            # one row per frame actually OCR'd
├── metadata_video.json    # sampling strategy now reflects the adaptive step
└── frames_usados/         # preprocessed images actually fed to OCR
```

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | All Phase 2 roadmap items as-is (user choice) |
| Approach | Claude decides per tech-stack/mission (user choice) |
| Preprocessing order | crop → grayscale → resize → threshold → sharpen/denoise |
| Blur detection | Laplacian variance on the grayscale image, module-level threshold constant |
| Duplicate detection | `skimage.metrics.structural_similarity` vs. last accepted frame, threshold constant |
| Selection order | blur check first (cheap), then SSIM (needs a comparison frame) |
| Adaptive step | FPS tiers: ≈30 → small step, ≈60 → medium, ≈120 → large; recorded in metadata |
| Crop | Applied inside `preprocess_frame()`; validated against frame bounds |
| Saved frames | Post-preprocessing images (what OCR actually saw) |
| Validation | Standard checks only: `ruff`, `mypy`, real script run (user choice) |

## Fidelity & error-handling rules

- **Never invent code.** Preprocessing transforms pixels; it never adds,
  reorders, or synthesizes text. Skipping a frame drops a *read*, never a line
  of reconstructed output — reconstruction fidelity is Phase 3+'s job.
- Deterministic and inspectable: every `ocr_raw.csv` row still references the
  exact image OCR consumed (now preprocessed) in `frames_usados/`.
- Honest accounting: frames skipped for blur or similarity are counted and
  logged, ready to surface in `relatorio_falhas.md` (Phase 5).
- Local only: no network calls at runtime.
- Clear, actionable errors for the failure modes reachable in this phase:
  - all Phase 0/1 errors preserved (missing video, unwritable output,
    missing `tesseract`, undetectable FPS, zero decoded frames);
  - crop values that leave no image area (negative, or left+right ≥ width,
    top+bottom ≥ height) → fail clearly before processing;
  - every sampled frame skipped as blurry/duplicate → fail clearly (nothing
    to OCR) rather than writing empty artifacts silently.
