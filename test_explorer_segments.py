"""Independent local detector, transition boundaries and export contracts."""

import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from explorer_segments.detection import Observation, Profile, Region, TemplateDetector
from explorer_segments.media import VideoReader, export_clip
from explorer_segments.timeline import scan, summarize
from split_explorer_video import app


def synthetic_frame(present: bool) -> Any:
    image = np.zeros((480, 720, 3), dtype=np.uint8)
    cv2.putText(
        image,
        "Toolbar []",
        (365, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1,
    )
    if present:
        cv2.putText(
            image,
            "Explorer",
            (35, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (240, 240, 240),
            1,
        )
    else:
        cv2.putText(
            image,
            "file.py",
            (35, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (240, 240, 240),
            1,
        )
    return image


def detector(tmp_path: Path) -> TemplateDetector:
    cv2.imwrite(str(tmp_path / "yes.png"), synthetic_frame(True))
    cv2.imwrite(str(tmp_path / "no.png"), synthetic_frame(False))
    profile = Profile(
        reference_present="yes.png",
        reference_absent="no.png",
        panel_region=Region(x=0.04, y=0.15, width=0.2, height=0.06),
        anchor_region=Region(x=0.5, y=0.055, width=0.3, height=0.055),
    )
    return TemplateDetector(profile, tmp_path)


def test_detector_resolution_and_unknown_screen(tmp_path: Path) -> None:
    model = detector(tmp_path)
    for state in (True, False):
        image = cv2.resize(synthetic_frame(state), (1440, 960))
        assert model.classify_image(image)[0] == ("present" if state else "absent")
    assert (
        model.classify_image(np.zeros((480, 720, 3), dtype=np.uint8))[0] == "uncertain"
    )
    assert (
        model.classify_image(np.zeros((720, 480, 3), dtype=np.uint8))[0] == "uncertain"
    )


def test_rejects_flat_reference_region(tmp_path: Path) -> None:
    model = detector(tmp_path)
    profile = model.profile.model_copy(
        update={"panel_region": Region(x=0.5, y=0.5, width=0.2, height=0.1)}
    )
    with pytest.raises(ValueError, match="lacks visual detail"):
        TemplateDetector(profile, tmp_path)


def test_panel_area_survives_small_title_occlusion(tmp_path: Path) -> None:
    positive = synthetic_frame(True)
    rng = np.random.default_rng(7)
    positive[72:216, 29:173] = rng.integers(0, 240, (144, 144, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "yes.png"), positive)
    cv2.imwrite(str(tmp_path / "no.png"), synthetic_frame(False))
    profile = Profile(
        reference_present="yes.png",
        reference_absent="no.png",
        panel_region=Region(x=0.04, y=0.15, width=0.2, height=0.3),
        anchor_region=Region(x=0.5, y=0.055, width=0.3, height=0.055),
        present_threshold=0.8,
        absent_threshold=0.25,
    )
    model = TemplateDetector(profile, tmp_path)
    covered = positive.copy()
    covered[75:85, 35:100] = 0
    assert model.classify_image(covered)[0] == "present"
    assert model.classify_image(synthetic_frame(False))[0] == "absent"


def observation(index: int, state: str) -> Observation:
    return Observation.model_validate(
        dict(
            frame=index,
            seconds=index / 10,
            state=state,
            panel_score=1 if state == "present" else 0,
            anchor_score=1,
        )
    )


def test_uncertainty_is_excluded_and_events_have_first_confirmed_frame() -> None:
    states = ["present"] * 4 + ["uncertain"] * 2 + ["absent"] * 25 + ["present"] * 4
    result = summarize(
        [observation(i, state) for i, state in enumerate(states)],
        min_duration=0.5,
        max_clip_seconds=1,
    )
    assert result["transitions"][0]["event"] == "hidden"
    assert result["transitions"][0]["first_confirmed_frame"] == 6
    assert result["transitions"][0]["last_previous_frame"] == 3
    assert result["transitions"][1]["event"] == "shown"
    assert result["clips"][0]["start"] == 0.6
    assert all(c["end"] <= 3.0 and c["duration"] <= 1 for c in result["clips"])
    assert result["uncertain_ranges"] == [{"start": 0.4, "end": 0.5}]


def test_short_false_absence_does_not_generate_clip_or_event() -> None:
    states = ["present"] * 4 + ["absent"] + ["present"] * 4
    result = summarize([observation(i, state) for i, state in enumerate(states)])
    assert result["clips"] == []
    assert result["transitions"] == []


def test_same_absent_state_is_not_merged_across_unknown() -> None:
    states = ["absent"] * 15 + ["uncertain"] * 5 + ["absent"] * 15
    result = summarize(
        [observation(i, state) for i, state in enumerate(states)], max_clip_seconds=0
    )
    assert len(result["clips"]) == 2
    assert result["clips"][0]["end"] < result["clips"][1]["start"]


def test_frame_refinement_on_small_local_video(tmp_path: Path) -> None:
    model = detector(tmp_path)
    video = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter.fourcc(*"MJPG"), 10, (720, 480)
    )
    assert writer.isOpened()
    for index in range(40):
        writer.write(synthetic_frame(index < 7 or index >= 28))
    writer.release()
    reader = VideoReader(video)
    try:
        observations = scan(reader, model, 4, scan_fps=2)
        result = summarize(observations)
        assert result["transitions"][0]["first_confirmed_frame"] == 7
        assert result["transitions"][1]["first_confirmed_frame"] == 28
        all_frames = scan(reader, model, 4, scan_fps=0)
        assert len(all_frames) == 40
        assert summarize(all_frames)["clips"][0]["start"] == pytest.approx(0.7)
    finally:
        reader.close()


def test_export_reencodes_and_preserves_only_first_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"encoded")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = tmp_path / "clip.mp4"
    export_clip(tmp_path / "source.mov", output, 1.23, 2.34, "ffmpeg")
    assert output.read_bytes() == b"encoded"
    assert "libx264" in commands[0] and "copy" not in commands[0]
    assert "0:a:0?" in commands[0]
    assert commands[0][commands[0].index("-t") + 1] == "1.110000000"
    with pytest.raises(ValueError, match="exists"):
        export_clip(tmp_path / "source.mov", output, 1, 2, "ffmpeg")


def test_cli_help_does_not_depend_on_ocr_or_openai() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "calibrate" in result.output and "split" in result.output


def test_continuous_intervals_include_unknown_until_confirmed_reappearance() -> None:
    states = (
        ["present"] * 4
        + ["absent"] * 15
        + ["uncertain"] * 5
        + ["absent"] * 15
        + ["present"] * 4
    )
    result = summarize(
        [observation(i, s) for i, s in enumerate(states)],
        interval_mode="continuous",
        max_clip_seconds=0,
    )
    assert len(result["clips"]) == 1
    assert result["clips"][0]["start"] == 0.4
    assert result["clips"][0]["end"] == 3.9
    assert len(result["transitions"]) == 2
    assert result["uncertain_ranges"]


def test_continuous_open_interval_keeps_tail_and_optional_splitting() -> None:
    states = ["uncertain"] * 4 + ["absent"] * 15 + ["uncertain"] * 10
    obs = [observation(i, s) for i, s in enumerate(states)]
    result = summarize(obs, interval_mode="continuous", max_clip_seconds=0)
    assert result["clips"][0]["start"] == 0.4
    assert result["clips"][0]["end"] == 2.8
    assert (
        len(
            summarize(
                obs, interval_mode="continuous", max_clip_seconds=1, min_duration=0.1
            )["clips"]
        )
        == 3
    )
    assert (
        summarize(
            [observation(i, "uncertain") for i in range(20)], interval_mode="continuous"
        )["clips"]
        == []
    )
