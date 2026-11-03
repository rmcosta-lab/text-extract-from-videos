"""Local video access and exact-time re-encoding, independent of OCR pipelines."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import cv2


def executable(name: str, override: Path | None = None) -> str:
    found = str(override) if override else shutil.which(name)
    if not found:
        raise ValueError(f"{name} not found; install it or pass --{name}")
    # Resolve Windows WinGet links before subprocess invocation.
    return str(Path(found).resolve())


def probe(video: Path, ffprobe: str) -> dict[str, Any]:
    if not video.is_file():
        raise ValueError(f"Video not found: {video}")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    metadata = json.loads(completed.stdout)
    streams = [s for s in metadata["streams"] if s["codec_type"] == "video"]
    if not streams:
        raise ValueError("No video stream found")
    return metadata


class VideoReader:
    def __init__(self, path: Path) -> None:
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise ValueError(f"Cannot open video: {path}")
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.fps <= 0 or self.count <= 0:
            self.capture.release()
            raise ValueError("Invalid video FPS/frame count")

    def read_at(self, seconds: float) -> tuple[int, float, Any]:
        self.capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        return self.read()

    def read_frame(self, index: int) -> tuple[int, float, Any]:
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        observed = self.read()
        if observed[0] != index:
            raise ValueError("Decoder seek did not reach the requested frame")
        return observed

    def read(self) -> tuple[int, float, Any]:
        ok, frame = self.capture.read()
        if not ok:
            raise ValueError("Could not decode requested video frame")
        index = round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        seconds = max(0.0, float(self.capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000)
        return index, seconds, frame

    def close(self) -> None:
        self.capture.release()


def export_clip(
    video: Path,
    destination: Path,
    start: float,
    end: float,
    ffmpeg: str,
    encoder: str = "libx264",
) -> None:
    if end <= start or destination.exists():
        raise ValueError("Invalid clip interval or output already exists")
    temporary = destination.with_name(destination.stem + ".partial.mp4")
    if temporary.exists():
        raise ValueError(f"Partial output exists: {temporary}")
    if encoder not in {"libx264", "h264_nvenc"}:
        raise ValueError("Unsupported encoder")
    encoding = (
        ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
        if encoder == "libx264"
        else ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18", "-b:v", "0"]
    )
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-ss",
                f"{start:.9f}",
                "-i",
                str(video),
                "-t",
                f"{end - start:.9f}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                *encoding,
                "-pix_fmt",
                "yuv420p",
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-fps_mode",
                "vfr",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
