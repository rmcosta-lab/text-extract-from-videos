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
    OCRLine,
    OCRRow,
    OutputExtension,
    SelectionStats,
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


@pytest.mark.parametrize("extension", list(OutputExtension))
@pytest.mark.parametrize("output_name", ["selection", None])
def test_cli_named_extraction_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extension: OutputExtension,
    output_name: str | None,
) -> None:
    name = output_name or "recording"
    video = tmp_path / "recording.mov"
    video.write_bytes(b"video")
    root = tmp_path / "output"
    metadata = VideoMetadata(
        fps=30,
        duration_seconds=3,
        width=720,
        height=480,
        total_frames=90,
        source="ffprobe",
    )
    monkeypatch.setattr("video_ocr.cli.get_video_metadata", lambda *args: metadata)
    monkeypatch.setattr("video_ocr.cli.create_ocr_engine", lambda *args: object())
    monkeypatch.setattr("video_ocr.cli.sample_frames", lambda *args: iter(()))
    row = OCRRow(
        text="10 x = 1",
        lines=[OCRLine(text="10 x = 1", confidence=99)],
        frame_number=1,
        time_seconds=0.03,
        time_formatted="00:00:00.030",
        frame_image_path="frames_usados/frame_1.png",
    )
    monkeypatch.setattr(
        "video_ocr.cli.run_ocr",
        lambda *args, **kwargs: (
            [row],
            SelectionStats(frames_sampled=1, frames_kept=1),
            [],
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "--video",
            str(video),
            "--output",
            str(root),
            *(["--output-name", output_name] if output_name is not None else []),
            "--output-extension",
            extension.value,
            "--prepare-review",
        ],
    )
    assert result.exit_code == 0, result.output
    out = root / name / "extract"
    assert (out / "codigo_extraido.txt").is_file()
    assert (out / f"codigo_extraido.{extension.value}").read_bytes() == (
        out / "codigo_extraido.txt"
    ).read_bytes()
    assert not (out / f"{name}.txt").exists()
    manifest = json.loads((out / "review_manifest.json").read_text())
    assert manifest["ocr_original"] == "codigo_extraido.txt"
    assert manifest["target_file"] == f"codigo_extraido.{extension.value}"
    assert manifest["parameters"]["output_name"] == name
    assert (out / "frames_usados").is_dir()
    assert not (root / "metadata_video.json").exists()


@pytest.mark.parametrize(
    "name", ["../escape", "a/b", "a\\b", "", "..", "CON", "x:", "relatorio_falhas"]
)
def test_invalid_output_name_does_not_create_output(tmp_path: Path, name: str) -> None:
    video = tmp_path / "video.mov"
    video.touch()
    root = tmp_path / "output"
    result = CliRunner().invoke(
        app, ["--video", str(video), "--output", str(root), "--output-name", name]
    )
    assert result.exit_code != 0
    assert not root.exists()


def test_named_cleanup_is_scoped_to_previous_recorded_outputs(tmp_path: Path) -> None:
    (tmp_path / "extraction_parameters.json").write_text(
        json.dumps(
            {
                "output_name": "selection",
                "output_extension": "py",
            }
        )
    )
    for name in ("selection.txt", "selection.py", "unrelated.py"):
        (tmp_path / name).write_text("old")
    prepare_output_tree(tmp_path)
    assert not (tmp_path / "selection.txt").exists()
    assert not (tmp_path / "selection.py").exists()
    assert (tmp_path / "unrelated.py").exists()
