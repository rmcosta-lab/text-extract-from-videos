"""Partial-reference OCR scoring, independent of video and OCR runtimes."""

from pydantic import BaseModel, Field
from rapidfuzz.distance import Levenshtein

from video_ocr.models import CropBox, LineRead


class ReferenceLine(BaseModel):
    number: int
    text: str
    exclude: bool = False
    reason: str | None = None


class ReferenceSample(BaseModel):
    frame_index: int = Field(ge=0)
    lines: list[ReferenceLine]


class ReferenceSet(BaseModel):
    video: str
    start_time: str
    end_time: str
    crop: CropBox
    method: str
    samples: list[ReferenceSample]


class LineScore(BaseModel):
    expected_number: int
    expected: str
    actual_number: int | None = None
    actual: str | None = None
    character_errors: int
    reference_characters: int
    word_errors: int
    reference_words: int
    exact_text: bool = False
    correct_number: bool = False
    correct_indentation: bool = False


def score_lines(
    reference: list[ReferenceLine], reads: list[LineRead]
) -> list[LineScore]:
    """Match selected lines one-to-one by text, independently of line numbers.

    Greedy highest-similarity matching (threshold 0.5), with deterministic ties.
    Missing lines count as deletions. Leading spaces are scored separately;
    internal whitespace, punctuation and accents remain significant in CER.
    Non-reference OCR lines are excluded because the reference is partial.
    """
    expected = [line for line in reference if not line.exclude]
    pairs = sorted(
        (
            (
                -Levenshtein.normalized_similarity(
                    ref.text.lstrip(), read.content.lstrip()
                ),
                i,
                j,
            )
            for i, ref in enumerate(expected)
            for j, read in enumerate(reads)
        )
    )
    matches: dict[int, int] = {}
    used: set[int] = set()
    for negative_score, i, j in pairs:
        if negative_score > -0.5:
            break
        if i not in matches and j not in used:
            matches[i] = j
            used.add(j)
    scores = []
    for i, ref in enumerate(expected):
        read = reads[matches[i]] if i in matches else None
        actual = read.content if read else ""
        content = ref.text.lstrip()
        candidate = actual.lstrip()
        scores.append(
            LineScore(
                expected_number=ref.number,
                expected=ref.text,
                actual_number=read.line_number if read else None,
                actual=actual if read else None,
                character_errors=Levenshtein.distance(content, candidate),
                reference_characters=len(content),
                word_errors=Levenshtein.distance(content.split(), candidate.split()),
                reference_words=len(content.split()),
                exact_text=read is not None and content == candidate,
                correct_number=read is not None and read.line_number == ref.number,
                correct_indentation=read is not None
                and (len(ref.text) - len(content) == len(actual) - len(candidate)),
            )
        )
    return scores


def summarize(scores: list[LineScore]) -> dict[str, float | int]:
    return {
        "reference_lines": len(scores),
        "matched_lines": sum(s.actual is not None for s in scores),
        "exact_text_lines": sum(s.exact_text for s in scores),
        "correct_numbers": sum(s.correct_number for s in scores),
        "correct_indentation": sum(s.correct_indentation for s in scores),
        "cer": sum(s.character_errors for s in scores)
        / max(1, sum(s.reference_characters for s in scores)),
        "wer": sum(s.word_errors for s in scores)
        / max(1, sum(s.reference_words for s in scores)),
    }
