"""Temporal motion, cursor tolerance, boundaries and actual frame provenance."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from test_blur_retry import parameters
from video_ocr.models import CropBox, OCRResult
from video_ocr.pipeline import run_ocr
from video_ocr.stability import StableFrameSelector, stable_pair


@pytest.mark.parametrize("mode", ["settle", "scroll", "cut", "static", "short"])
def test_temporal_selection(tmp_path: Path, mode: str) -> None:
    rng = np.random.default_rng(8)
    stable = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
    video = tmp_path / "motion.avi"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter.fourcc(*"MJPG"), 30, (128, 128)
    )
    assert writer.isOpened()
    for i in range(18):
        if mode == "scroll" or (mode in ("settle", "cut") and i < 5):
            image = np.roll(stable, i * 5, axis=0)
        else:
            image = stable.copy()
        writer.write(image)
    writer.release()
    p = parameters(end=3 if mode == "short" else 18)
    selector = StableFrameSelector(video, 30, p, CropBox(), 0.5)
    try:
        selected = selector(0)
        if mode in ("scroll", "short"):
            assert selected is None
        else:
            assert selected is not None
            assert selected[0] >= (5 if mode in ("settle", "cut") else 0)
            assert selected[1] == selected[0] / 30
            assert (
                selector.records[-1]["stable_end_frame"] < p.sample_end_frame_exclusive
            )
    finally:
        selector.close()


def test_cursor_tolerance_but_not_broad_scroll() -> None:
    original = np.random.default_rng(2).integers(0, 255, (200, 200), dtype=np.uint8)
    cursor = original.copy()
    cursor[10:20, 10:12] = 255
    assert stable_pair(original, cursor)
    assert not stable_pair(original, np.roll(original, 3, axis=0))


def test_pipeline_skips_consumed_candidates_and_keeps_actual_provenance(
    tmp_path: Path,
) -> None:
    sharp = np.random.default_rng(3).integers(0, 255, (64, 64, 3), dtype=np.uint8)

    class Engine:
        def recognize(self, image: Any) -> OCRResult:
            return OCRResult(text="1 x = 2")

    rows, stats, outcomes = run_ocr(
        [(0, 0, sharp), (1, 0.1, sharp), (10, 1, sharp)],
        Engine(),
        tmp_path,
        3,
        CropBox(),
        stability_selector=lambda i: (3, 0.3, sharp) if i == 0 else None,
    )
    assert [r.frame_number for r in rows] == [3]
    assert stats.frames_kept == 1
    assert stats.frames_replaced_stability == 1
    assert stats.frames_skipped_after_replacement == 1
    assert stats.frames_discarded_unstable == 1
    assert [o.frame_number for o in outcomes] == [0, 1, 3, 10]
