"""EOF needs visible evidence, repetition, and freedom from contradictions."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from video_ocr import cli
from video_ocr.line_limit import infer_line_limit
from video_ocr.models import OCRLine, OCRRow, SelectionStats, VideoMetadata, app


def frame(
    tmp_path: Path,
    number: int,
    *,
    end: int = 100,
    cropped: bool = False,
    unread_text: bool = False,
) -> OCRRow:
    image = np.full((150 if cropped else 320, 400), 255, dtype=np.uint8)
    lines = []
    for i in range(5):
        y = 20 + i * 20
        lines.extend(
            [
                OCRLine(
                    text=str(end - 4 + i),
                    confidence=99,
                    left=10,
                    top=y,
                    width=25,
                    height=15,
                ),
                OCRLine(
                    text="return value",
                    confidence=99,
                    left=60,
                    top=y,
                    width=120,
                    height=15,
                ),
            ]
        )
        cv2.putText(
            image,
            str(end - 4 + i),
            (10, y + 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0,),
            1,
        )
    if unread_text:
        cv2.putText(
            image, "MISSED BY OCR", (10, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,), 1
        )
    path = tmp_path / f"frame_{number}.png"
    assert cv2.imwrite(str(path), image)
    return OCRRow(
        text="tail",
        lines=lines,
        frame_number=number,
        time_seconds=number / 10,
        time_formatted="00:00:01.000",
        frame_image_path=str(path),
    )


def test_repeated_visible_end(tmp_path: Path) -> None:
    result = infer_line_limit([frame(tmp_path, 1), frame(tmp_path, 4)])
    assert result.value == 100
    assert result.source == "inferred"
    assert result.frames == [1, 4]


@pytest.mark.parametrize(
    "kind",
    [
        "single",
        "duplicate",
        "cropped",
        "unread",
        "missing_image",
        "no_geometry",
        "conflicting",
    ],
)
def test_inconclusive_evidence_leaves_limit_unknown(tmp_path: Path, kind: str) -> None:
    a = frame(tmp_path, 1, cropped=kind == "cropped", unread_text=kind == "unread")
    b = frame(
        tmp_path,
        4,
        end=101 if kind == "conflicting" else 100,
        cropped=kind == "cropped",
        unread_text=kind == "unread",
    )
    rows = [a, b]
    if kind == "single":
        rows = [a]
    elif kind == "duplicate":
        rows = [a, a]
    elif kind == "missing_image":
        rows = [
            r.model_copy(update={"frame_image_path": str(tmp_path / "absent")})
            for r in rows
        ]
    elif kind == "no_geometry":
        rows = [
            r.model_copy(
                update={
                    "lines": [line.model_copy(update={"top": None}) for line in r.lines]
                }
            )
            for r in rows
        ]
    assert infer_line_limit(rows).value is None
    assert infer_line_limit(rows).source == "unknown"


def test_higher_sequence_blocks_lower_end_even_when_cropped(tmp_path: Path) -> None:
    rows = [
        frame(tmp_path, 1),
        frame(tmp_path, 4),
        frame(tmp_path, 7, end=200, cropped=True),
    ]
    result = infer_line_limit(rows)
    assert result.value is None
    assert result.reason == "higher_numbered_sequence_observed"


@pytest.mark.parametrize("manual", [False, True])
def test_cli_persists_and_applies_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manual: bool
) -> None:
    rows = [frame(tmp_path, 1), frame(tmp_path, 4)]
    # A remote false read must be retained in the audit, not expand gaps.
    rows.append(
        OCRRow(
            text="782: noise",
            lines=[OCRLine(text="782: noise")],
            frame_number=8,
            time_seconds=0.8,
            time_formatted="00:00:00.800",
            frame_image_path="absent",
        )
    )
    video = tmp_path / "clip.mp4"
    video.touch()
    monkeypatch.setattr(
        cli,
        "get_video_metadata",
        lambda *a: VideoMetadata(
            fps=30,
            duration_seconds=1,
            width=400,
            height=320,
            total_frames=30,
            source="ffprobe",
        ),
    )
    monkeypatch.setattr(cli, "create_ocr_engine", lambda *a: object())
    monkeypatch.setattr(cli, "sample_frames", lambda *a: iter(()))
    monkeypatch.setattr(
        cli, "run_ocr", lambda *a, **kw: (rows, SelectionStats(frames_sampled=3), [])
    )
    args = [
        "--video",
        str(video),
        "--output",
        str(tmp_path / "out"),
        "--prepare-review",
    ]
    if manual:
        args += ["--max-line-number", "99"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    out = tmp_path / "out/clip/extract"
    manifest = json.loads((out / "review_manifest.json").read_text(encoding="utf-8"))
    bound = 99 if manual else 100
    assert manifest["parameters"]["max_line_number"] == bound
    assert manifest["parameters"]["line_limit"]["source"] == (
        "manual" if manual else "inferred"
    )
    assert max(line["line_number"] for line in manifest["lines"]) == bound
    audit = json.loads((out / "line_number_audit.json").read_text(encoding="utf-8"))
    assert any(s["read"]["line_number"] == 782 for s in audit["rejected_reads"])
