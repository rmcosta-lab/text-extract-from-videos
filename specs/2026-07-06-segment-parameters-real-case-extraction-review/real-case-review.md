# Real-case extraction review

Reviewed existing local run artifacts in `saida/frames_usados/` and
`saida/ocr_raw.csv` from `sample-video/IMG_5430.MOV`.

## Frames inspected

- `frame_30.png`: clear editor gutter/code layout. OCR can emit number-only
  gutter lines followed by the matching code text.
- `frame_225.png`: same gutter/code split around a function definition and
  parameter block.

## Finding

The existing geometry-based pairing for gutter-only numbers and adjacent code
text is appropriate for these frames and should be preserved.

The review also found fidelity noise in real OCR rows: isolated impossible line
numbers such as `2352` and `8408` can be introduced by OCR glitches. Allowing
those values into numbered reconstruction creates false missing-line ranges
that swamp the report.

## Adjustment

Added frame-local line-number outlier filtering. A detected line number is kept
when it has nearby numbered evidence in the same frame. If it is isolated far
from every other detected number in that frame, the OCR text and frame/time
provenance are preserved, but the line-number label is dropped. No replacement
number is inferred.
