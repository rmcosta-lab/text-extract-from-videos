"""Number recovery must follow spatial evidence, never OCR iteration order."""

import json
import random
from pathlib import Path

import pytest

from video_ocr.gutter import GutterDecision
from video_ocr.models import (
    CropBox,
    EngineName,
    FailureReport,
    OCRLine,
    OCRRow,
    SelectionStats,
    VideoMetadata,
)
from video_ocr.reconstruction import merge_ocr_results, parse_code_lines
from video_ocr.reports import prepare_output_tree, write_outputs
from video_ocr.video import resolve_extraction_parameters


def row(lines: list[OCRLine], frame: int = 10) -> OCRRow:
    return OCRRow(
        text="\n".join(line.text for line in lines),
        lines=lines,
        frame_number=frame,
        time_seconds=0.083,
        time_formatted="00:00:00.083",
        confidence=99,
        sharpness=100,
        frame_image_path="frame.webp",
    )


def boxes(start: int = 4, stop: int = 14, *, scale: int = 1) -> list[OCRLine]:
    result = []
    for n in range(start, stop):
        # Locally slanted column, as in the filmed monitor in clip 008.
        right = 90 + (n - start)
        width = 25 if n < 10 else 43
        result.extend(
            [
                OCRLine(
                    text=str(n),
                    confidence=99,
                    left=(right - width) * scale,
                    top=(n * 42) * scale,
                    width=width * scale,
                    height=33 * scale,
                ),
                OCRLine(
                    text=f"content_{n}",
                    confidence=99,
                    left=177 * scale,
                    top=(n * 42) * scale,
                    width=500 * scale,
                    height=39 * scale,
                ),
            ]
        )
    return result


@pytest.mark.parametrize("scale", [1, 2, 3])
@pytest.mark.parametrize("shuffle", [False, True])
def test_recovers_s_and_zero_with_clip8_geometry(scale: int, shuffle: bool) -> None:
    lines = boxes(scale=scale)
    lines[8] = lines[8].model_copy(update={"text": "S", "confidence": 88.49})
    lines[10] = lines[10].model_copy(update={"text": "0", "confidence": 61.28})
    if shuffle:
        random.Random(42).shuffle(lines)
    original = row(lines)
    before = original.model_dump()
    audit: list[GutterDecision] = []
    reads = parse_code_lines([original], gutter_audit=audit)
    assert next(r for r in reads if r.content == "content_8").line_number == 8
    assert next(r for r in reads if r.content == "content_9").line_number == 9
    assert {d["recovered_number"] for d in audit} == {8, 9}
    assert all(len(d["anchor_numbers"]) >= 4 for d in audit)
    assert original.model_dump() == before


def test_zero_without_evidence_keeps_text_unnumbered() -> None:
    lines = boxes(9, 10)
    lines[0] = lines[0].model_copy(update={"text": "0"})
    reads = parse_code_lines([row(lines)])
    assert [(r.line_number, r.content) for r in reads] == [(None, "content_9")]


def test_zero_in_combined_box_keeps_text_unnumbered() -> None:
    reads = parse_code_lines([row([OCRLine(text="0: content", confidence=99)])])
    assert [(r.line_number, r.content) for r in reads] == [(None, " content")]


def test_missing_geometry_does_not_guess_s_as_eight() -> None:
    lines = [line.model_copy(update={"top": None}) for line in boxes()]
    lines[8] = lines[8].model_copy(update={"text": "S"})
    audit: list[GutterDecision] = []
    parse_code_lines([row(lines)], gutter_audit=audit)
    assert audit == []


def test_does_not_extrapolate_clipped_first_number() -> None:
    lines = boxes()
    lines[0] = lines[0].model_copy(update={"text": "0"})
    reads = parse_code_lines([row(lines)])
    assert next(r for r in reads if r.content == "content_4").line_number is None


def test_blank_line_and_scroll_offset_do_not_shift_recovery() -> None:
    rows = []
    for start in [4, 104]:
        lines = boxes(start, start + 10)
        lines[9] = lines[9].model_copy(update={"text": ""})
        lines[10] = lines[10].model_copy(update={"text": "0", "confidence": 60})
        rows.append(row(lines, frame=start))
    reads = parse_code_lines(rows)
    for start in [4, 104]:
        assert (
            next(r for r in reads if r.content == f"content_{start + 5}").line_number
            == start + 5
        )
        assert any(r.line_number == start + 4 and r.content == "" for r in reads)


def test_numeric_code_without_gutter_is_not_repaired() -> None:
    lines = boxes()[::2]
    lines[5] = lines[5].model_copy(update={"text": "S"})
    audit: list[GutterDecision] = []
    parse_code_lines([row(lines)], gutter_audit=audit)
    assert audit == []


def test_folded_region_does_not_invent_a_number() -> None:
    lines = boxes()
    for i in range(10, len(lines), 2):
        lines[i] = lines[i].model_copy(update={"text": str(100 + i)})
    lines[8] = lines[8].model_copy(update={"text": "S"})
    audit: list[GutterDecision] = []
    parse_code_lines([row(lines)], gutter_audit=audit)
    assert not any(d["original_text"] == "S" and d["recovered_number"] for d in audit)


def test_corrected_number_does_not_merge_with_unrelated_zero() -> None:
    lines = boxes()
    lines[10] = lines[10].model_copy(update={"text": "0", "confidence": 60})
    unrelated = boxes(99, 100)
    unrelated[0] = unrelated[0].model_copy(update={"text": "0"})
    merged = merge_ocr_results(parse_code_lines([row(lines), row(unrelated, 392)]))
    assert (
        next(m for m in merged if m.read.line_number == 9).read.content == "content_9"
    )
    assert not any(m.read.line_number == 0 for m in merged)


def test_inconsistent_vertical_position_stays_unnumbered() -> None:
    lines = boxes()
    for index in [10, 11]:
        lines[index] = lines[index].model_copy(update={"top": 9 * 42 + 21})
    audit: list[GutterDecision] = []
    reads = parse_code_lines([row(lines)], gutter_audit=audit)
    assert next(r for r in reads if r.content == "content_9").line_number is None
    assert any(d["reason"] == "ambiguous_local_geometry" for d in audit)


def test_outputs_persist_audit_and_preserve_raw_evidence(tmp_path: Path) -> None:
    info = VideoMetadata(
        fps=30,
        duration_seconds=1,
        width=1080,
        height=1920,
        total_frames=30,
        source="ffprobe",
    )
    parameters = resolve_extraction_parameters(
        engine=EngineName.paddle,
        crop=CropBox(),
        metadata=info,
        start_time=None,
        end_time=None,
        step=1,
    )
    parameters.prepare_review = True
    lines = boxes()
    lines[10] = lines[10].model_copy(update={"text": "0", "confidence": 60})
    original = row(lines)
    merged = merge_ocr_results(parse_code_lines([original]))
    report = FailureReport(
        video_path="clip.mp4",
        metadata=info,
        stats=SelectionStats(frames_sampled=1),
        lines_extracted=len(merged),
        line_numbers_detected=True,
    )
    write_outputs(info, parameters, [original], merged, report, tmp_path)
    audit_file = tmp_path / "line_number_audit.json"
    decisions = json.loads(audit_file.read_text(encoding="utf-8"))["decisions"]
    assert any(
        d["original_text"] == "0" and d["recovered_number"] == 9 for d in decisions
    )
    manifest = json.loads(
        (tmp_path / "review_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["frames"][0]["ocr"]["lines"][10]["text"] == "0"
    assert "line_number_audit.json" in (tmp_path / "relatorio_falhas.md").read_text(
        encoding="utf-8"
    )
    prepare_output_tree(tmp_path)
    assert not audit_file.exists()


def test_saved_clip008_line9_survives_reconstruction() -> None:
    fixture = Path(__file__).parent / "fixtures/clip008_gutter_frame10.json"
    original = OCRRow.model_validate(json.loads(fixture.read_text(encoding="utf-8")))
    merged = merge_ocr_results(parse_code_lines([original]))
    ninth = next(m for m in merged if m.read.line_number == 9)
    assert "**Sem retrocompat**" in ninth.read.content
    assert len([m for m in merged if "**Sem retrocompat**" in m.read.content]) == 1
    assert not any(m.read.line_number == 0 for m in merged)
