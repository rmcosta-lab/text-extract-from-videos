"""Fidelity metrics must penalize omissions, wrong numbers and indentation."""

from video_ocr.models import LineRead
from video_ocr.quality import ReferenceLine, score_lines, summarize


def read(text: str, number: int | None = 1) -> LineRead:
    return LineRead(
        content=text,
        line_number=number,
        frame_number=1,
        time_seconds=0,
        time_formatted="00:00:00.000",
    )


def test_text_number_and_indent_are_independent() -> None:
    scores = score_lines(
        [ReferenceLine(number=5, text="  return value")], [read("return value", 6)]
    )
    assert scores[0].exact_text
    assert not scores[0].correct_number
    assert not scores[0].correct_indentation
    assert summarize(scores)["cer"] == 0


def test_missing_text_is_counted_as_deletions() -> None:
    result = summarize(score_lines([ReferenceLine(number=1, text="hello")], []))
    assert result["cer"] == 1
    assert result["matched_lines"] == 0


def test_one_ocr_line_cannot_satisfy_two_references() -> None:
    references = [ReferenceLine(number=n, text="return value") for n in (1, 2)]
    assert (
        summarize(score_lines(references, [read("return value")]))["matched_lines"] == 1
    )


def test_punctuation_errors_are_not_normalized_away() -> None:
    scores = score_lines([ReferenceLine(number=1, text="print(x)")], [read("print(x]")])
    assert scores[0].character_errors == 1
    assert not scores[0].exact_text


def test_excluded_uncertain_reference_does_not_affect_metrics() -> None:
    assert score_lines([ReferenceLine(number=1, text="?", exclude=True)], []) == []
