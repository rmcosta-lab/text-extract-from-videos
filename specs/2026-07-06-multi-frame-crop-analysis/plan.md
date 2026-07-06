# Plan — Phase 11: Multi-frame crop analysis

## 1. Frame sampling

- Add `sample_frame_indices(total_frames, count)` returning evenly spaced
  indices across the video (first sample at `REFERENCE_FRAME_INDEX`, last
  near the final frame; deduplicated and clamped for short videos).
- Generalize the frame-decoding path so one `cv2.VideoCapture` session reads
  all sampled frames (seek per index), instead of reopening the video per
  frame; a frame that fails to decode is skipped and recorded, not fatal
  unless **no** frame decodes.
- Add a `--sample-count` CLI option (default 12, `min=1`) wired through
  `create_app()`.

## 2. Per-frame analysis (refactor, no behavior change)

- Extract the existing single-frame heuristic into a helper that returns a
  per-frame **observation** instead of a final crop: text detected?, left
  text/gutter edge, gutter found?, text band top/bottom, noise-column left
  edge (or `None`), median line height — all in original-frame pixels.
- Keep `_word_boxes`, `_gutter_column`, `_main_text_cluster`, and
  `_keep_confident_segments` as-is; they operate per frame.

## 3. Combination logic

- `combine_observations(observations, frame_width, frame_height) ->
  CropSuggestion`:
  - Drop empty-OCR observations; if none remain → `CropBox()` with
    `text_detected=False`.
  - Gutter-anchored observations outrank cluster-fallback ones: when at least
    one frame has a detected gutter, only anchored frames inform the crop
    (the fallback band can sweep in menu/status chrome and would blow up the
    union); fallback frames are used only when no frame found a gutter.
  - Left: `min` of per-frame left edges, minus the margin (margin from the
    median line height across kept frames), clamped at 0.
  - Top/bottom: `min` of tops / `max` of bottoms across frames, margin
    applied, clamped.
  - Right: if a **majority** of kept observations detected a noise column,
    crop at the largest noise-column left edge (the most conservative cut),
    additionally clamped so it never clips any frame's kept-text right edge;
    otherwise 0.
- Extend `CropSuggestion` (or add a wrapper model) with the sampled frame
  indices, how many yielded text, and how many were skipped.

## 4. Backend & page wiring

- `create_app()` decodes the sampled frames once, keeps the existing
  representative frame (current reference index) for the before/after
  images, and caches per-engine **combined** suggestions.
- `GET /api/preview` response gains the sampling info (indices analyzed,
  frames with text); everything else (crop, flags, images) is unchanged in
  shape.
- `crop_preview.html`: show a small line under the suggestion, e.g.
  "analyzed N frames (M with text): indices …"; no other UI changes.

## 5. Tests

- Unit tests for `sample_frame_indices` (even spacing, short videos, count 1,
  dedup).
- Unit tests for `combine_observations` with fake observations: widest gutter
  wins on the left; growing line numbers (9 → 100) widen the kept gutter;
  noise column majority rule (present in most frames → cropped at the safest
  edge; present in a minority → right stays 0); right cut never clips any
  frame's text; vertical union; empty-OCR frames ignored; all-empty → zero
  crop with `text_detected=False`.
- Keep existing API tests passing; extend the preview test to assert the new
  sampling fields.

## 6. Documentation

- Update the module docstring and README section: the suggestion now analyzes
  multiple frames across the video, not just frame 30.

## 7. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy` passes on the touched files.
- Real run: `python suggest_crop.py --video sample-video/IMG_5430.MOV` — the
  page shows the combined suggestion with the analyzed-frames info; the crop
  keeps every line number fully visible on the left and no code line clipped
  on the right across the sampled frames (inspect the cropped previews of the
  sampled frames / spot-check late frames).
- `pytest test_suggest_crop.py` passes.
