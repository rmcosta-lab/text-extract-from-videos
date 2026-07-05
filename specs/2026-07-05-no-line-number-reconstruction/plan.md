# Plan — Phase 4: No-line-number reconstruction

## 1. Constants & similarity helper

- Add a module-level `FUZZY_MATCH_THRESHOLD` constant (rapidfuzz ratio, 0–100)
  next to the existing threshold constants, with a short comment on its role.
- Add a small helper that compares two line contents with
  `rapidfuzz.fuzz.ratio` on whitespace-normalized text (same normalization
  already used for frequency counting in `merge_ocr_results()`); original text
  is never modified — normalization is for comparison only.

## 2. Grouping repeats — fuzzy consolidation

- Reuse `LineRead` and `MergedLine` as-is; no new pydantic models unless a
  small internal group type helps readability.
- Group logic: reads judged to be the same on-screen line (fuzzy similarity at
  or above the threshold) form one group; the group's winner is picked with
  the same ordered criteria as Phase 3 — frequency of identical content,
  then confidence, then frame sharpness — and emitted **verbatim**.
- Mark `uncertain=True` when the winner's confidence is below the existing
  `OCR_UNCERTAIN_CONFIDENCE` constant (or missing), same as the numbered path.

## 3. Time-ordered reconstruction — `reconstruct_by_time()`

- New function `reconstruct_by_time(reads: list[LineRead]) -> list[MergedLine]`
  alongside `merge_ocr_results()` (which keeps owning the numbered path).
- Process frames in ascending `time_seconds` / `frame_number`; within a frame,
  keep the on-screen top-to-bottom line order.
- For each new frame, align its lines against the tail of the accumulated
  reconstruction: find the best contiguous overlap where consecutive lines
  fuzzy-match; overlapping lines join the existing groups (feeding the
  best-read selection), lines after the overlap are appended as new.
- No overlap found → append all of the frame's lines (scroll jumped or
  content changed); near-threshold ambiguity keeps both reads rather than
  dropping one.
- Empty input or a single frame passes through trivially in time order.

## 4. Output wiring — `write_outputs()` and `main()`

- `write_outputs()`: when `has_line_numbers()` is false, `codigo_extraido.txt`
  is now the `reconstruct_by_time()` result — uncertain lines preceded by
  `# [OCR_UNCERTAIN] frame=<n> time=<HH:MM:SS.mmm> texto_original="..."` —
  replacing the Phase 1 naive concatenation. The numbered branch is untouched.
- `main()` wires the unnumbered branch through `reconstruct_by_time()`; the
  existing `rich` summary states which path ran plus lines reconstructed and
  uncertain count for this path too.
- `metadata_video.json`, `ocr_raw.csv`, and `frames_usados/` keep their exact
  Phase 3 shape.

## 5. Verification

- `ruff check .` and `ruff format --check .` pass.
- `mypy extract_code_from_video.py` passes.
- Real script run on one actual video **without** line numbers:
  `codigo_extraido.txt` in video-time order, scroll duplicates collapsed to
  one line each, uncertain lines carrying the exact marker format, every
  marker traceable to a frame in `frames_usados/`.
- A run on a line-numbered video still takes the Phase 3 numbered path,
  byte-identical behavior.
- Validate every checkbox in `validation.md`.
