"""Breadcrumb parsing, temporal agreement and safe export names."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from explorer_segments.automatic import TextBox
from explorer_segments.file_identity import clip_filename, identify_clips, parse_header
from split_explorer_video import app, save_clip_index


def box(text: str, x: float = 0, y: float = 0) -> TextBox:
    return TextBox(text=text, score=0.99, x=x, y=y, width=150, height=15)


def test_breadcrumb_example_and_split_boxes() -> None:
    reading = parse_header(
        [box("__init__.py x"), box("spark_ai > core > __init__.py > ...", y=25)]
    )
    assert reading["filename"] == "__init__.py"
    assert reading["visible_path"] == "spark_ai/core/__init__.py"
    assert reading["folders"] == ["spark_ai", "core"]
    assert (
        parse_header([box("spark_ai >"), box("core >", 160), box("__init__.py", 240)])
        == reading
    )


def test_unknown_paths_tabs_and_code_are_not_invented() -> None:
    assert parse_header([box("... > core > main.py")])["visible_path"] is None
    assert parse_header([box("main.py x")])["filename"] == "main.py"
    assert parse_header([box("main.py other.py")])["filename"] is None
    assert parse_header([box("import config.py")])["filename"] is None
    assert (
        parse_header([box("src > main.py"), box("other > utils.py", y=25)])["filename"]
        is None
    )
    assert "/" not in clip_filename(1, {"filename": "../../CON.py"})
    assert "\\" not in clip_filename(1, {"filename": "..\\CON.py"})
    assert clip_filename(2, {"filename": "__init__.py"}) == "clip_002____init__.py.mp4"


@pytest.mark.parametrize(
    "names,expected",
    [
        (["main.py"] * 3, "confirmed"),
        (["main.py", "other.py", "main.py"], "conflicting_readings"),
        (["main.py", "", ""], "unconfirmed"),
    ],
)
def test_temporal_consensus(
    monkeypatch: pytest.MonkeyPatch, names: list[str], expected: str
) -> None:
    class Reader:
        def __init__(self, path: Path) -> None:
            pass

        def read_at(self, seconds: float) -> tuple[int, float, Any]:
            return int(seconds * 10), seconds, np.zeros((1000, 500, 3), dtype=np.uint8)

        def close(self) -> None:
            pass

    class OCR:
        def read(self, image: Any) -> list[TextBox]:
            assert image.shape[0] == 120
            name = names.pop(0)
            return [box(f"src > {name}")] if name else []

    monkeypatch.setattr("explorer_segments.file_identity.VideoReader", Reader)
    clips: list[dict[str, Any]] = [{"start": 1, "end": 5}]
    identify_clips(Path("video.mov"), clips, OCR())
    assert clips[0]["source_file"]["status"] == expected
    assert clips[0]["file"] == (
        "clip_001__main.py.mp4" if expected == "confirmed" else "clip_001.mp4"
    )


def test_export_keeps_identity_and_all_clip_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mov"
    video.write_bytes(b"video")
    report = tmp_path / "segments.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "video": str(video),
                "video_size": video.stat().st_size,
                "video_mtime_ns": video.stat().st_mtime_ns,
                "metadata": {"format": {"duration": 10}},
                "clips": [
                    {
                        "start": 1,
                        "end": 3,
                        "source_file": {
                            "filename": "__init__.py",
                            "visible_path": "spark_ai/core/__init__.py",
                        },
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("split_explorer_video.executable", lambda *args: "ffmpeg")

    def export(*args: Any) -> None:
        args[1].write_bytes(b"clip")

    monkeypatch.setattr("split_explorer_video.export_clip", export)
    out = tmp_path / "clips"
    result = CliRunner().invoke(
        app, ["export", "--report", str(report), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "export.json").read_text())
    assert manifest["video"] == str(video)
    clip = manifest["clips"][0]
    assert clip["source_file"]["visible_path"] == "spark_ai/core/__init__.py"
    assert clip["status"] == "exported"
    assert (out / "clip_001____init__.py.mp4").exists()
    assert json.loads((out / "clips.json").read_text()) == [
        {
            "file": "clip_001____init__.py.mp4",
            "reading": {
                "filename": "__init__.py",
                "visible_path": "spark_ai/core/__init__.py",
                "folders": None,
                "path_status": "unavailable",
            },
        }
    ]


def test_clip_index_excludes_pending_clips_and_raw_ocr(tmp_path: Path) -> None:
    save_clip_index(
        tmp_path,
        [
            {"file": "clip_001.mp4", "status": "exported"},
            {"file": "clip_002.mp4", "status": "planned"},
        ],
    )
    index = json.loads((tmp_path / "clips.json").read_text())
    assert len(index) == 1
    assert set(index[0]) == {"file", "reading"}
    assert index[0]["reading"]["filename"] is None


def test_split_exports_outside_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_explorer_segments import detector, observation  # noqa: PLC0415

    model = detector(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(model.profile.model_dump_json())
    video = tmp_path / "source.mov"
    video.write_bytes(b"video")

    class Reader:
        def __init__(self, path: Path) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("split_explorer_video.VideoReader", Reader)
    monkeypatch.setattr("split_explorer_video.executable", lambda *args: "ffmpeg")
    monkeypatch.setattr(
        "split_explorer_video.probe", lambda *args: {"format": {"duration": 3}}
    )
    monkeypatch.setattr(
        "split_explorer_video.scan",
        lambda *args, **kwargs: [observation(i, "absent") for i in range(25)],
    )

    def export(*args: Any) -> None:
        args[1].write_bytes(b"clip")

    monkeypatch.setattr("split_explorer_video.export_clip", export)
    out = tmp_path / "result" / "analysis"
    result = CliRunner().invoke(
        app,
        [
            "split",
            "--video",
            str(video),
            "--profile",
            str(profile),
            "--output",
            str(out),
            "--no-identify-files",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not list(out.glob("*.mp4"))
    clips = out.parent / "clip"
    assert (clips / "clip_001.mp4").is_file()
    assert json.loads((clips / "clips.json").read_text())[0]["file"] == "clip_001.mp4"
    assert json.loads((out / "segments.json").read_text())["clip_directory"] == str(
        clips.resolve()
    )
