"""Real decoding recovery and pipeline provenance, without OCR runtimes."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from video_ocr.blur_retry import BlurRetry
from video_ocr.models import CropBox, ExtractionParameters, OCRResult
from video_ocr.pipeline import run_ocr


def parameters(end: int = 30) -> ExtractionParameters:
    return ExtractionParameters(
        effective_start_seconds=0,
        effective_start_time="00:00:00.000",
        start_defaulted=True,
        end_defaulted=True,
        crop=CropBox(),
        sample_step=10,
        sample_start_frame=0,
        sample_end_frame_exclusive=end,
        expected_candidate_frames=3,
    )


@pytest.mark.parametrize("clear", [True, False])
def test_retry_selects_sharp_neighbor_and_respects_boundaries(
    tmp_path: Path, clear: bool
) -> None:
    video = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter.fourcc(*"MJPG"), 10, (64, 64))
    assert writer.isOpened()
    sharp = np.random.default_rng(1).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    for i in range(30):
        writer.write(sharp if clear and i == 3 else np.zeros_like(sharp))
    writer.release()
    retry = BlurRetry(video, 10, parameters(), CropBox(), 0.25)
    try:
        # Frame 1 is a forced candidate: frame 0 must not consume it.
        assert retry(0) is None
        selected = retry(1)
        assert (selected[0] if selected else None) == (3 if clear else None)
        assert [x["frame"] for x in retry.records[-1]["checked"]] == [2, 3]
        retry.parameters = parameters(end=3)
        assert retry(1) is None  # Cannot read sharp frame outside segment.
    finally:
        retry.close()


def test_pipeline_uses_replacement_identity_and_preserves_failed_original(
    tmp_path: Path,
) -> None:
    class Engine:
        def recognize(self, image: Any) -> OCRResult:
            return OCRResult(text="1 x = 2")

    sharp = np.random.default_rng(2).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    rows, stats, outcomes = run_ocr(
        [(10, 1.0, np.zeros_like(sharp))],
        Engine(),
        tmp_path,
        1,
        CropBox(),
        blur_retry=lambda frame: (12, 1.2, sharp),
    )
    assert rows[0].frame_number == 12 and rows[0].time_seconds == 1.2
    assert (tmp_path / "frame_12.png").exists()
    assert not (tmp_path / "frame_10.png").exists()
    assert stats.frames_kept == 1 and stats.frames_recovered_blurry == 1
    assert [(o.frame_number, o.usable) for o in outcomes] == [(10, False), (12, True)]
