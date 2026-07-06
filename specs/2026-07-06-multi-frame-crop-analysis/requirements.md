# Requirements — Phase 11: Multi-frame crop analysis

## Objective

Make the crop suggestion in `suggest_crop.py` representative of the **whole
video**, not just frame 30. Code scrolls and line numbers grow wider
(9 → 10 → 100…), so a single reference frame can suggest a crop that later
cuts digits off the line-number gutter (`--crop-left` too aggressive) or clips
long code lines (`--crop-right` too aggressive). The tool must sample multiple
frames across the video's duration, run the existing crop heuristic on each,
and combine the results into one crop that is safe for every sampled frame.

## Scope

### Included

- **Multi-frame sampling**: pick several frame indices spread evenly across
  the video's duration (metadata via the already-imported
  `get_video_metadata()`), decode them with the existing OpenCV frame-reading
  path, and run the current per-frame heuristic (`suggest_crop`-style OCR +
  gutter/segment analysis) on each sampled frame.
- **Combination rules** for the per-frame results into one `CropBox`:
  - `--crop-left`: never cuts any sampled frame's line-number gutter — take
    the **leftmost** detected gutter/text edge across frames.
  - `--crop-right`: never clips any sampled frame's code text — cut only at
    the noise column (minimap/scrollbar) and only when it is **consistently
    detected** across frames; use the most conservative (leftmost text-safe,
    rightmost-cut) value so no frame's kept text is clipped.
  - `--crop-top` / `--crop-bottom`: same "never cut detected text" rule —
    the combined band covers every sampled frame's detected text band.
- **Honesty rules preserved**: frames with empty OCR contribute nothing to
  the combination; if **no** sampled frame yields text, the suggestion is a
  zero crop with the existing explicit "no text detected" notice. Never a
  fabricated region.
- **Web preview keeps working**: the page shows the combined suggestion and
  which frame indices informed it (and how many yielded text); the existing
  edit/re-crop flow and engine selection are unchanged.
- **Engine selection** unchanged: `tesseract` (default) or `paddle`, applied
  to all sampled frames of one suggestion run.

### Excluded

- No changes to the main extraction pipeline or its CLI.
- No per-frame crop editing in the page (one combined crop, as today).
- No video playback; the before/after preview still shows a single
  representative frame.
- No persistence of chosen values; the user still copies the flags manually.

## Deliverables / output artifacts

- Updated `suggest_crop.py` with multi-frame sampling and combination logic
  (plus a CLI option for the number of sampled frames with a sensible
  default).
- Updated `crop_preview.html` showing which frames informed the suggestion.
- Updated/extended tests in `test_suggest_crop.py` covering the sampling and
  combination rules.
- README note updated if the tool's description mentions "frame 30" only.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Sampling strategy | Evenly spaced frame indices across the full duration, default ~12 frames, first sample at the current `REFERENCE_FRAME_INDEX` | Covers scrolling/gutter growth over the whole video at bounded OCR cost; keeps frame 30 behavior as a degenerate case |
| Sample count | CLI option (e.g. `--sample-count`, default 12, min 1) | Lets slow engines (paddle) use fewer frames; default balances coverage vs. runtime |
| Frame precedence | Gutter-anchored observations outrank cluster-fallback ones; fallback frames inform the crop only when no sampled frame found a gutter | The fallback band sweeps in menu/status chrome (verified on the sample video), which would blow the union up to nearly the full frame; mirrors the per-frame gutter-over-cluster precedence from Phase 10 |
| Combined left edge | Min of per-frame left text/gutter edges (margin applied after combining) | Guarantees the widest observed gutter is never cut |
| Combined right edge | Crop at the noise column only when a majority of text-bearing frames detect one, using a value that clips no frame's kept text; otherwise 0 | Conservative by design — a missed minimap costs nothing, a clipped code line loses content |
| Combined top/bottom | Union (min top, max bottom) of per-frame text bands | Same "never cut detected text" rule vertically |
| Preview frame | Keep showing one representative frame (the existing reference index) for before/after | The page stays simple; the crop values, not the image, carry the multi-frame result |
| Blur handling | Frames whose OCR yields no words are simply skipped | Reuses the empty-OCR path; no new blur-detection dependency in this tool |

## Fidelity & error-handling rules

- The tool still only **suggests**; it never applies a crop to an extraction.
- A sampled frame that fails to decode or yields empty OCR is skipped and
  counted, never guessed at; the page reports how many frames informed the
  suggestion.
- If no sampled frame yields text: zero crop + explicit "no text detected"
  notice (existing behavior, now across all samples).
- Combined crops are still validated with
  `CropBox.validate_against(width, height)`; API error handling for
  user-edited values is unchanged.
- Clear, actionable errors for the known failure modes are preserved
  (missing video, unreadable frames, missing engine, port in use).
- Local only: server stays on `127.0.0.1`; no network calls at runtime.
