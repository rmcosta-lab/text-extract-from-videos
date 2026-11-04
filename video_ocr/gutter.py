"""Conservative, frame-local validation of separately detected gutter boxes.

Only interpolate inside a locally consistent sequence. Never extrapolate past
the anchors, renumber by OCR iteration order, or change the recognized code.
"""

from itertools import combinations
from statistics import median
from typing import TypedDict

from video_ocr.models import OCRLine


class GutterDecision(TypedDict):
    frame_number: int
    box_index: int
    original_text: str
    recovered_number: int | None
    reason: str
    anchor_numbers: list[int]


def _number(line: OCRLine) -> int | None:
    text = line.text.strip()
    return int(text) if text.isascii() and text.isdecimal() else None


def _center(line: OCRLine) -> float:
    assert line.top is not None and line.height is not None
    return line.top + line.height / 2


def validate_gutter(
    lines: list[OCRLine],
    frame_number: int,
    audit: list[GutterDecision] | None = None,
) -> tuple[list[OCRLine], set[int]]:
    """Return derived OCR boxes plus rejected numeric boxes; originals stay raw.

    Require a right-aligned column of at least four confident positive numbers.
    For each suspect, four nearby anchors and at least 75% local consensus must
    support the same interpolation. Folded/wrapped/discontinuous regions and
    conflicting models do not justify a repair.
    """
    numeric = [
        i
        for i, line in enumerate(lines)
        if (_number(line) or 0) > 0
        and (line.confidence or 0) >= 90
        and line.left is not None
        and line.width is not None
        and line.top is not None
        and (line.height or 0) > 0
    ]
    if len(numeric) < 4:
        return lines, set()

    # Right edges stay aligned when the number gains a digit (9 -> 10).
    def right(index: int) -> int:
        line = lines[index]
        assert line.left is not None and line.width is not None
        return line.left + line.width

    height = median(lines[i].height or 0 for i in numeric)
    candidates = [
        i
        for i, line in enumerate(lines)
        if line.left is not None
        and line.width is not None
        and line.top is not None
        and (line.height or 0) > 0
        and line.width <= height * 4
        and 0 < len(line.text.strip()) <= 5
        and all(c in "0123456789SsOoIl|B" for c in line.text.strip())
    ]
    derived = list(lines)
    rejected: set[int] = set()
    for index in candidates:
        target = lines[index]
        y = _center(target)
        # Use a local column: perspective can tilt the gutter across the frame.
        column = [i for i in numeric if abs(right(i) - right(index)) <= height * 0.45]
        nearby = sorted(
            (i for i in column if i != index),
            key=lambda i: abs(_center(lines[i]) - y),
        )[:8]
        # Numeric code literals alone are not evidence of an editor gutter.
        if (
            sum(
                1
                for i in nearby
                if any(
                    (code.left or 0) > right(i) + height
                    and code.top is not None
                    and code.height is not None
                    and abs(_center(code) - _center(lines[i])) <= height * 0.5
                    for code in lines
                )
            )
            < 3
        ):
            continue
        predictions: dict[int | None, list[int]] = {}
        for a, b in combinations(nearby, 2):
            na, nb = _number(lines[a]), _number(lines[b])
            assert na is not None and nb is not None
            if not 0 < abs(nb - na) <= 8:
                continue
            pitch = (_center(lines[b]) - _center(lines[a])) / (nb - na)
            if not height * 0.95 <= pitch <= height * 2.5:
                continue
            origin = _center(lines[a]) - pitch * na
            support = [
                i
                for i in nearby
                if abs(_center(lines[i]) - origin - pitch * (_number(lines[i]) or 0))
                <= pitch * 0.18
            ]
            if len(support) < max(4, len(nearby) * 0.75):
                continue
            if (
                not min(_center(lines[i]) for i in support)
                < y
                < max(_center(lines[i]) for i in support)
            ):
                continue
            estimate = (y - origin) / pitch
            number = round(estimate)
            predicted = (
                number if number > 0 and abs(estimate - number) <= 0.18 else None
            )
            predictions[predicted] = sorted(_number(lines[i]) or 0 for i in support)
        original = _number(target)
        if not predictions:
            continue
        recovered = next(iter(predictions)) if len(predictions) == 1 else None
        if recovered == original and recovered is not None:
            continue
        if recovered is not None:
            derived[index] = target.model_copy(update={"text": str(recovered)})
        elif original is not None:
            rejected.add(index)
        if audit is not None:
            audit.append(
                {
                    "frame_number": frame_number,
                    "box_index": index,
                    "original_text": target.text,
                    "recovered_number": recovered,
                    "reason": "local_geometry_consensus"
                    if recovered is not None
                    else "ambiguous_local_geometry",
                    "anchor_numbers": predictions.get(recovered, []),
                }
            )
    return derived, rejected
