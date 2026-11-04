"""Local temporal selection: reject motion, retain a confirmed stable image."""

import math
from pathlib import Path
from typing import Any

import numpy as np

from video_ocr.imaging import _cropped_grayscale, frame_sharpness, is_frame_blurry
from video_ocr.models import CropBox, ExtractionParameters, MatLike, require_cv2


def thumbnail(gray: MatLike) -> MatLike:
    cv2 = require_cv2()
    height, width = gray.shape[:2]
    scale = min(1.0, 640 / width)
    return cv2.resize(gray, (round(width * scale), max(8, round(height * scale))))


def stable_pair(first: MatLike, second: MatLike) -> bool:
    """Ignore small localized cursor changes, but not broad text movement."""
    difference = np.abs(first.astype(np.float32) - second.astype(np.float32))
    return bool(np.mean(difference > 20) <= 0.02)


class StableFrameSelector:
    def __init__(
        self,
        video: Path,
        fps: float,
        parameters: ExtractionParameters,
        crop: CropBox,
        window_seconds: float = 0.5,
    ) -> None:
        self.video, self.fps, self.parameters = video, fps, parameters
        self.crop, self.window_seconds = crop, window_seconds
        self.capture: Any = None
        self.records: list[dict[str, Any]] = []

    def __call__(self, original: int) -> tuple[int, float, MatLike] | None:
        stop = min(
            self.parameters.sample_end_frame_exclusive,
            original + math.floor(self.window_seconds * self.fps) + 1,
        )
        cv2 = require_cv2()
        if self.capture is None:
            self.capture = cv2.VideoCapture(str(self.video))
        if not self.capture.isOpened():
            raise ValueError("Cannot open video for temporal stability selection")
        record: dict[str, Any] = {
            "original_frame": original,
            "original_seconds": original / self.fps,
            "checked": [],
            "selected_frame": None,
            "reason": "no_stable_sequence",
            "minimum_stable_seconds": 0.1,
            "pixel_difference_threshold": 20,
            "maximum_changed_fraction": 0.02,
        }
        self.records.append(record)
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, original)
        if round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) != original:
            record["reason"] = "inexact_seek"
            return None
        anchor: MatLike | None = None
        previous: MatLike | None = None
        run_start = original
        best: tuple[int, float, MatLike] | None = None
        best_score = -1.0
        for index in range(original, stop):
            ok, image = self.capture.read()
            if not ok:
                record["reason"] = "decode_ended_before_confirmation"
                break
            if round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) != index + 1:
                record["reason"] = "inexact_decode"
                return None
            gray = _cropped_grayscale(image, self.crop)
            small = thumbnail(gray)
            sharpness = frame_sharpness(gray)
            stable = (
                anchor is not None
                and previous is not None
                and stable_pair(anchor, small)
                and stable_pair(previous, small)
            )
            if not stable or is_frame_blurry(sharpness):
                anchor = None if is_frame_blurry(sharpness) else small
                run_start = index
                best, best_score = None, -1.0
            previous = small
            record["checked"].append(
                {"frame": index, "sharpness": sharpness, "stable_with_run": stable}
            )
            if not is_frame_blurry(sharpness) and sharpness > best_score:
                best, best_score = (index, index / self.fps, image), sharpness
            if best is not None and index - run_start >= max(
                2, math.ceil(0.1 * self.fps)
            ):
                record.update(
                    reason="stable_sequence",
                    selected_frame=best[0],
                    selected_seconds=best[1],
                    selected_sharpness=best_score,
                    stable_start_frame=run_start,
                    stable_end_frame=index,
                )
                return best
        return None

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
