# Validation — Phase 11: Multi-frame crop analysis

### Sampling

- [ ] Frame indices are spread evenly across the video's duration (first at
      `REFERENCE_FRAME_INDEX`, last near the end), deduplicated, and clamped
      for short videos.
- [ ] `--sample-count` is exposed on the CLI with a sensible default and
      `min=1`; count 1 reproduces single-frame behavior.
- [ ] A frame that fails to decode is skipped and recorded; the run only
      fails if no sampled frame decodes.

### Combination / crop quality

- [ ] Combined `--crop-left` uses the leftmost detected gutter/text edge
      across sampled frames — no sampled frame's line numbers are cut.
- [ ] Combined `--crop-right` cuts only at a consistently detected noise
      column and never clips any sampled frame's kept code text; without a
      consistent noise column it stays 0.
- [ ] Combined top/bottom cover every sampled frame's detected text band.
- [ ] Against `sample-video/IMG_5430.MOV`: every line number fully visible on
      the left and no code line clipped on the right across the sampled
      frames (spot-check late frames with wider numbers / longer lines).

### OCR / fidelity

- [ ] Empty-OCR frames contribute nothing to the combination.
- [ ] If no sampled frame yields text: zero crop, `text_detected=false`, and
      the explicit "no text detected" notice in the page.
- [ ] The suggestion never invents a region; combined values pass
      `CropBox.validate_against(width, height)`.

### Web preview

- [ ] The page shows the combined suggestion plus which frames informed it
      (indices analyzed, how many with text).
- [ ] The existing edit/re-crop flow and engine selection
      (`tesseract`/`paddle`) still work unchanged.

### Error handling

- [ ] Missing video file, missing engine (`OCREngineUnavailableError` with
      install hint), invalid user crop values, and port-in-use keep their
      existing clear errors.

### Offline (no network)

- [ ] Server still binds `127.0.0.1` by default; the page loads no external
      resources.

### Technical

- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `mypy` passes on the touched files.
- [ ] Real script run: `python suggest_crop.py --video
      sample-video/IMG_5430.MOV` serves the page end-to-end with the
      multi-frame suggestion.
- [ ] `pytest test_suggest_crop.py` passes (existing + new sampling and
      combination tests).
