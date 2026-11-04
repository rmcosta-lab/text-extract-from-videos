"""Infer EOF only from a repeated numbered tail with visible empty space below."""

from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from statistics import median

from video_ocr.models import LineLimitEvidence, OCRLine, OCRRow


def _tail(row: OCRRow) -> list[OCRLine]:
    """Use original, confident gutter boxes, never repaired or guessed numbers."""
    numbers = sorted(
        (
            line
            for line in row.lines
            if line.text.strip().isascii()
            and line.text.strip().isdecimal()
            and int(line.text.strip()) > 0
            and (line.confidence or 0) >= 90
            and line.left is not None
            and line.top is not None
            and (line.width or 0) > 0
            and (line.height or 0) > 0
        ),
        key=lambda line: line.top or 0,
    )
    if len(numbers) < 5:
        return []
    tail = numbers[-5:]
    if any(int(b.text) != int(a.text) + 1 for a, b in pairwise(tail)):
        return []
    heights = median(line.height or 0 for line in tail)
    rights = [(line.left or 0) + (line.width or 0) for line in tail]
    steps = [(b.top or 0) - (a.top or 0) for a, b in pairwise(tail)]
    pitch = median(steps)
    if (
        max(rights) - min(rights) > heights * 0.5
        or not heights <= pitch <= heights * 2.5
        or any(abs(step - pitch) > pitch * 0.2 for step in steps)
    ):
        return []
    # At least two code boxes beside this sequence distinguish gutter from
    # a column of numeric data. Empty final source lines are legitimate.
    paired = sum(
        any(
            code.left is not None
            and code.left > max(rights) + heights
            and code.top is not None
            and abs(code.top - (line.top or 0)) < heights * 0.6
            and code.text.strip()
            for code in row.lines
        )
        for line in tail
    )
    return tail if paired >= 2 else []


def _visible_blank_tail(row: OCRRow, tail: list[OCRLine]) -> bool:
    """Inspect pixels: absent OCR alone never establishes empty editor space."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if not Path(row.frame_image_path).is_file():
        return False
    image = cv2.imread(row.frame_image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return False
    last = tail[-1]
    pitch = median((b.top or 0) - (a.top or 0) for a, b in pairwise(tail))
    top = int((last.top or 0) + (last.height or 0) + pitch * 0.5)
    bottom = int(top + pitch * 6)
    left = min(line.left or 0 for line in tail)
    if bottom > image.shape[0] or left >= image.shape[1] * 0.25:
        return False
    # Reject any OCR content below the tail, including low-confidence numbers.
    if any(
        line.text.strip() and line.top is not None and line.top >= top
        for line in row.lines
    ):
        return False
    region = image[top:bottom, left:]
    if not region.size:
        return False
    # Background may vary slowly with lighting; a row-local median allows this.
    background = np.median(region, axis=1, keepdims=True)
    foreground = np.abs(region.astype(float) - background) > 30
    # Any text-sized component (even if OCR missed it) invalidates the evidence.
    count, _, stats, _ = cv2.connectedComponentsWithStats(foreground.astype("uint8"))
    min_area = max(4, (last.height or 1) ** 2 * 0.015)
    return not any(stats[i, cv2.CC_STAT_AREA] >= min_area for i in range(1, count))


def infer_line_limit(rows: list[OCRRow]) -> LineLimitEvidence:
    """Require the same EOF in two distinct frames, with no credible higher tail."""
    candidates: dict[int, list[OCRRow]] = defaultdict(list)
    highest_supported = 0
    for row in rows:
        tail = _tail(row)
        if not tail:
            continue
        number = int(tail[-1].text)
        highest_supported = max(highest_supported, number)
        if _visible_blank_tail(row, tail):
            candidates[number].append(row)
    if len(candidates) != 1:
        return LineLimitEvidence(
            reason="conflicting_endings" if candidates else "no_visible_end"
        )
    number, frames = next(iter(candidates.items()))
    unique = {row.frame_number: row for row in frames}
    times = [row.time_seconds for row in unique.values()]
    if highest_supported > number:
        return LineLimitEvidence(reason="higher_numbered_sequence_observed")
    if len(unique) < 2 or max(times) - min(times) < 0.15:
        return LineLimitEvidence(reason="end_not_confirmed_across_frames")
    return LineLimitEvidence(
        value=number,
        source="inferred",
        reason="repeated_tail_with_visible_blank_space",
        frames=sorted(unique),
    )
