"""Exports retain OCR evidence and never treat an extension as a path."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from extract_code_from_video import app
from video_ocr.models import (
    CropBox,
    EngineName,
    LineRead,
    MergedLine,
    OCRRow,
    OutputExtension,
    VideoMetadata,
)
from video_ocr.reports import (
    prepare_output_tree,
    write_extracted_code,
    write_review_manifest,
)
from video_ocr.video import resolve_extraction_parameters


def line(text: str, uncertain: bool = False) -> MergedLine:
    return MergedLine(
        read=LineRead(
            content=text,
            line_number=10,
            frame_number=210,
            time_seconds=3.5,
            time_formatted="00:00:03.500",
        ),
        uncertain=uncertain,
    )


@pytest.mark.parametrize("extension", list(OutputExtension))
def test_export_preserves_original_bytes(
    tmp_path: Path, extension: OutputExtension
) -> None:
    write_extracted_code(
        [line("  café = 1"), line("broken", True)], tmp_path, extension
    )
    original = (tmp_path / "codigo_extraido.txt").read_bytes()
    assert (tmp_path / f"codigo_extraido.{extension.value}").read_bytes() == original
    assert b"[OCR_UNCERTAIN]" in original


def test_invalid_extension_fails_before_clearing_output(tmp_path: Path) -> None:
    original = tmp_path / "codigo_extraido.txt"
    original.write_text("preserve", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "--video",
            "missing.mov",
            "--output",
            str(tmp_path),
            "--output-extension",
            "../py",
        ],
    )
    assert result.exit_code == 2
    assert original.read_text(encoding="utf-8") == "preserve"


def test_cleanup_removes_only_previously_recorded_export(tmp_path: Path) -> None:
    (tmp_path / "extraction_parameters.json").write_text(
        json.dumps({"output_extension": "md"}), encoding="utf-8"
    )
    (tmp_path / "codigo_extraido.md").write_text("previous", encoding="utf-8")
    (tmp_path / "codigo_extraido.py").write_text("unrelated", encoding="utf-8")
    prepare_output_tree(tmp_path)
    assert not (tmp_path / "codigo_extraido.md").exists()
    assert (tmp_path / "codigo_extraido.py").read_text(encoding="utf-8") == "unrelated"


def test_review_manifest_maps_export_lines_to_frames(tmp_path: Path) -> None:
    info = VideoMetadata(
        fps=60,
        duration_seconds=10,
        width=2160,
        height=3840,
        total_frames=600,
        source="ffprobe",
        codec="hevc",
    )
    parameters = resolve_extraction_parameters(
        engine=EngineName.paddle,
        crop=CropBox(),
        metadata=info,
        start_time="3.5",
        end_time="9",
        step=30,
    )
    parameters.output_extension = OutputExtension.md
    parameters.prepare_review = True
    row = OCRRow(
        text="hello",
        frame_number=210,
        time_seconds=3.5,
        time_formatted="00:00:03.500",
        frame_image_path="frames_usados/frame_210.png",
    )
    write_review_manifest(
        parameters, [row], [line("hello"), line("maybe", True)], tmp_path
    )
    data = json.loads((tmp_path / "review_manifest.json").read_text(encoding="utf-8"))
    assert data["target_file"] == "codigo_extraido.md"
    assert data["status"] == "prepared_not_reviewed"
    assert [item["output_line"] for item in data["lines"]] == [1, 3]
    assert data["frames"][0]["original_image"] == "frames_usados/frame_210_original.png"
    assert data["frames"][0]["review_image"] == "frames_usados/frame_210_review.webp"
    assert data["frames"][0]["review_crop"] == parameters.crop.model_dump()
