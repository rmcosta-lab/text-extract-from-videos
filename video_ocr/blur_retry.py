"""Bounded forward search for a sharper replacement, with actual provenance."""

import math
from pathlib import Path
from typing import Any

from video_ocr.imaging import _cropped_grayscale, frame_sharpness, is_frame_blurry
from video_ocr.models import (
    FORCED_SAMPLE_FRAMES,
    CropBox,
    ExtractionParameters,
    MatLike,
    require_cv2,
)


class BlurRetry:
    def __init__(
        self,
        video: Path,
        fps: float,
        parameters: ExtractionParameters,
        crop: CropBox,
        window_seconds: float,
    ) -> None:
        self.video = video
        self.fps = fps
        self.parameters = parameters
        self.crop = crop
        self.window_seconds = window_seconds
        self.capture: Any = None
        self.records: list[dict[str, Any]] = []

    def __call__(self, original: int) -> tuple[int, float, MatLike] | None:
        p = self.parameters
        next_regular = (
            p.sample_start_frame
            + ((original - p.sample_start_frame) // p.sample_step + 1) * p.sample_step
        )
        stop = min(
            p.sample_end_frame_exclusive,
            next_regular,
            original + math.floor(self.window_seconds * self.fps) + 1,
            *(f for f in FORCED_SAMPLE_FRAMES if f > original),
        )
        record: dict[str, Any] = {
            "original_frame": original,
            "original_seconds": original / self.fps,
            "checked": [],
            "replacement_frame": None,
        }
        self.records.append(record)
        if stop <= original + 1:
            record["reason"] = "no_neighbor_before_next_candidate_or_segment_end"
            return None
        cv2 = require_cv2()
        if self.capture is None:
            self.capture = cv2.VideoCapture(str(self.video))
        if not self.capture.isOpened():
            raise ValueError("Cannot open video for blur recovery")
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, original + 1)
        if round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) != original + 1:
            record["reason"] = "inexact_seek"
            return None
        best: tuple[int, float, MatLike] | None = None
        best_score = -1.0
        for index in range(original + 1, stop):
            ok, image = self.capture.read()
            if not ok:
                break
            score = frame_sharpness(_cropped_grayscale(image, self.crop))
            record["checked"].append({"frame": index, "sharpness": score})
            if not is_frame_blurry(score) and score > best_score:
                best = index, index / self.fps, image
                best_score = score
        record["reason"] = "recovered" if best else "no_sharp_neighbor"
        if best:
            record.update(
                replacement_frame=best[0],
                replacement_seconds=best[1],
                replacement_sharpness=best_score,
            )
        return best

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
