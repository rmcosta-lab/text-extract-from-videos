"""False gutter clusters must not manufacture missing source lines."""

from video_ocr.models import LineRead, SuspectLineNumber
from video_ocr.reconstruction import (
    _filter_frame_line_number_outliers,
    detect_missing_lines,
    merge_ocr_results,
)


def reads(numbers: list[int]) -> list[LineRead]:
    return [
        LineRead(
            line_number=n,
            content=f"code_{n}",
            frame_number=1,
            time_seconds=0,
            time_formatted="00:00:00.000",
        )
        for n in numbers
    ]


def test_remote_cluster_cannot_create_false_gaps() -> None:
    evidence = reads([*range(200, 220), 710, 716, 727])
    suspects: list[SuspectLineNumber] = []
    result = _filter_frame_line_number_outliers(evidence, suspects=suspects)
    assert [s.read.line_number for s in suspects] == [710, 716, 727]
    assert all(r.line_number is None for r in result[-3:])
    assert result[-1].content == "code_727"
    assert evidence[-1].line_number == 727
    assert (
        max(m.line_number for m in detect_missing_lines(merge_ocr_results(result)))
        < 220
    )


def test_known_maximum_rejects_even_single_read() -> None:
    suspects: list[SuspectLineNumber] = []
    result = _filter_frame_line_number_outliers(
        reads([782]), max_line_number=548, suspects=suspects
    )
    assert result[0].line_number is None
    assert suspects[0].reason == "above_known_maximum"
    assert detect_missing_lines(merge_ocr_results(result)) == []


def test_genuine_gap_and_later_frame_sequence_survive() -> None:
    early = _filter_frame_line_number_outliers(reads([1, 2, 4, 5]))
    later = _filter_frame_line_number_outliers(reads([710, 711, 712, 713]))
    assert [r.line_number for r in later] == [710, 711, 712, 713]
    assert [m.line_number for m in detect_missing_lines(merge_ocr_results(early))] == [
        3
    ]


def test_balanced_folded_regions_remain_inconclusive() -> None:
    evidence = reads([10, 11, 12, 13, 200, 201, 202, 203])
    assert _filter_frame_line_number_outliers(evidence) == evidence
