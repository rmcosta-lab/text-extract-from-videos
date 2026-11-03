"""Video for local video OCR."""

import json
import math
import subprocess
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import (
    NoReturn,
)

from pydantic import ValidationError

from video_ocr.models import (
    CLOCK_SECONDS_RE,
    FORCED_SAMPLE_FRAMES,
    LOW_FPS_THRESHOLD,
    OCR_UNCERTAIN_CONFIDENCE,
    OCR_UNCERTAIN_CONFIDENCE_PADDLE,
    SAMPLE_STEP_BY_FPS_TIER,
    SECONDS_ONLY_RE,
    TIMESTAMP_EPSILON,
    TIMESTAMP_FORMAT_HELP,
    CandidateFrameWindow,
    CropBox,
    EngineName,
    ExtractionParameters,
    InvalidExtractionParameterError,
    InvalidVideoMetadataError,
    MatLike,
    VideoMetadata,
    _build_video_metadata,
    _format_time,
    _validation_error_summary,
    _warn,
    fail,
    require_cv2,
)


def _invalid_timestamp(option_name: str, value: str) -> NoReturn:
    """Raise one consistent timestamp-format message."""
    raise InvalidExtractionParameterError(
        f"{option_name} has invalid timestamp value {value!r}. Accepted forms: "
        f"{TIMESTAMP_FORMAT_HELP}."
    )


def _parse_timestamp(value: str | None, option_name: str) -> float | None:
    """Parse a CLI timestamp while keeping validation messages actionable."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        _invalid_timestamp(option_name, value)

    if SECONDS_ONLY_RE.fullmatch(text):
        return float(text)
    if ":" not in text:
        _invalid_timestamp(option_name, value)

    parts = text.split(":")
    if len(parts) not in {2, 3}:
        _invalid_timestamp(option_name, value)
    if not all(part.isdigit() for part in parts[:-1]):
        _invalid_timestamp(option_name, value)
    if not CLOCK_SECONDS_RE.fullmatch(parts[-1]):
        _invalid_timestamp(option_name, value)

    seconds = float(parts[-1])
    if seconds >= 60:
        _invalid_timestamp(option_name, value)
    if len(parts) == 2:
        minutes = int(parts[0])
        return minutes * 60 + seconds

    hours = int(parts[0])
    minutes = int(parts[1])
    if minutes >= 60:
        _invalid_timestamp(option_name, value)
    return hours * 3600 + minutes * 60 + seconds


def _parse_rate(value: str | None) -> float | None:
    """Parse an ffprobe rational rate like ``60/1`` into a positive float."""
    if not value:
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def _metadata_from_ffprobe(video: Path) -> VideoMetadata | None:
    """Read metadata via ffprobe; return None (with a warning) if unusable."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream_side_data=rotation:stream_tags=rotate",
        "-of",
        "json",
        str(video),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        _warn(
            "ffprobe is not installed; falling back to OpenCV for metadata. "
            "Install it with [bold]brew install ffmpeg[/bold] (macOS) or your "
            "system package manager for more reliable metadata."
        )
        return None
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or f"exit code {exc.returncode}"
        _warn(f"ffprobe failed ({detail}); falling back to OpenCV.")
        return None

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        _warn("ffprobe returned unparsable JSON; falling back to OpenCV.")
        return None

    streams = payload.get("streams") or []
    if not streams:
        _warn("ffprobe found no video stream; falling back to OpenCV.")
        return None
    stream = streams[0]

    fps = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(
        stream.get("r_frame_rate")
    )
    try:
        width = int(stream.get("width"))
        height = int(stream.get("height"))
        # OpenCV applies the display rotation when decoding. Validate crop
        # against those displayed dimensions, not the encoded raster.
        rotation = stream.get("tags", {}).get("rotate", 0)
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = side_data["rotation"]
                break
        if round(float(rotation)) % 180 == 90:
            width, height = height, width
        duration = float(
            stream.get("duration") or payload.get("format", {}).get("duration") or 0
        )
    except (TypeError, ValueError):
        _warn("ffprobe metadata is incomplete; falling back to OpenCV.")
        return None
    if not fps or duration <= 0:
        _warn("ffprobe metadata is incomplete; falling back to OpenCV.")
        return None

    nb_frames = str(stream.get("nb_frames", ""))
    total_frames = int(nb_frames) if nb_frames.isdigit() else round(duration * fps)
    try:
        return _build_video_metadata(
            fps=fps,
            duration_seconds=round(duration, 3),
            width=width,
            height=height,
            total_frames=total_frames,
            codec=stream.get("codec_name"),
            source="ffprobe",
        )
    except InvalidVideoMetadataError as exc:
        _warn(f"ffprobe metadata is invalid ({exc}); falling back to OpenCV.")
        return None


def _metadata_from_opencv(video: Path) -> VideoMetadata:
    """Read FPS / frame count / resolution via OpenCV (codec best-effort)."""
    cv2 = require_cv2()
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            fail(f"cannot open video with OpenCV: [cyan]{video}[/cyan]")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
    finally:
        capture.release()

    if fps <= 0:
        fail(
            "FPS could not be detected by ffprobe or OpenCV; the video "
            f"[cyan]{video}[/cyan] may be corrupt or in an unsupported format."
        )
    if total_frames <= 0:
        fail(
            "the video frame count could not be determined by OpenCV for "
            f"[cyan]{video}[/cyan] (some containers do not expose it). Install "
            "ffprobe ([bold]brew install ffmpeg[/bold] on macOS) for reliable "
            "metadata, then re-run."
        )
    codec = None
    if fourcc:
        codec = (
            "".join(chr((fourcc >> shift) & 0xFF) for shift in (0, 8, 16, 24)).strip()
            or None
        )
    try:
        return _build_video_metadata(
            fps=fps,
            duration_seconds=round(total_frames / fps, 3),
            width=width,
            height=height,
            total_frames=total_frames,
            codec=codec,
            source="opencv",
        )
    except InvalidVideoMetadataError as exc:
        fail(
            f"OpenCV returned invalid metadata for [cyan]{video}[/cyan]: {exc}. "
            "The video may be corrupt or in an unsupported format."
        )


def get_video_metadata(video: Path) -> VideoMetadata:
    """Read video metadata: ffprobe as primary source, OpenCV as fallback."""
    metadata = _metadata_from_ffprobe(video)
    if metadata is None:
        metadata = _metadata_from_opencv(video)
    return metadata


def uncertain_confidence_for(engine: EngineName) -> float:
    """Confidence floor for the `[OCR_UNCERTAIN]` marker, calibrated per engine."""
    if engine is EngineName.paddle:
        return OCR_UNCERTAIN_CONFIDENCE_PADDLE
    return OCR_UNCERTAIN_CONFIDENCE


def _candidate_frame_window(
    metadata: VideoMetadata,
    *,
    start_seconds: float,
    end_seconds: float | None,
    step: int,
) -> CandidateFrameWindow:
    """Convert effective segment seconds into original-video frame bounds."""
    start_frame = min(
        metadata.total_frames,
        max(0, math.ceil(start_seconds * metadata.fps - TIMESTAMP_EPSILON)),
    )
    if end_seconds is None:
        end_frame_exclusive = metadata.total_frames
    else:
        last_inclusive = math.floor(end_seconds * metadata.fps + TIMESTAMP_EPSILON)
        end_frame_exclusive = min(metadata.total_frames, max(0, last_inclusive + 1))
    end_frame_exclusive = max(start_frame, end_frame_exclusive)

    frame_span = end_frame_exclusive - start_frame
    if frame_span <= 0:
        return CandidateFrameWindow(start_frame, end_frame_exclusive, 0, None, None)

    step_candidate_count = ((frame_span - 1) // step) + 1
    step_last = start_frame + (step_candidate_count - 1) * step
    forced = {
        frame
        for frame in FORCED_SAMPLE_FRAMES
        if start_frame <= frame < end_frame_exclusive
    }
    extra_forced = {frame for frame in forced if (frame - start_frame) % step != 0}
    expected = step_candidate_count + len(extra_forced)
    first = start_frame if expected else None
    last = max({step_last, *forced}) if expected else None
    return CandidateFrameWindow(start_frame, end_frame_exclusive, expected, first, last)


def resolve_extraction_parameters(
    *,
    engine: EngineName,
    crop: CropBox,
    metadata: VideoMetadata,
    start_time: str | None,
    end_time: str | None,
    step: int,
) -> ExtractionParameters:
    """Validate CLI segment options and persist the effective run settings."""
    requested_start_seconds = _parse_timestamp(start_time, "--start-time")
    requested_end_seconds = _parse_timestamp(end_time, "--end-time")

    start_defaulted = requested_start_seconds is None
    end_defaulted = requested_end_seconds is None
    start_seconds = (
        requested_start_seconds if requested_start_seconds is not None else 0.0
    )
    duration_seconds = (
        metadata.duration_seconds if metadata.duration_seconds > 0 else None
    )
    end_seconds = (
        requested_end_seconds if requested_end_seconds is not None else duration_seconds
    )

    if start_seconds < 0:
        raise InvalidExtractionParameterError(
            f"--start-time must be non-negative; got {start_seconds:g}."
        )
    if requested_end_seconds is not None and requested_end_seconds < 0:
        raise InvalidExtractionParameterError(
            f"--end-time must be non-negative; got {requested_end_seconds:g}."
        )
    if (
        duration_seconds is not None
        and start_seconds > duration_seconds + TIMESTAMP_EPSILON
    ):
        raise InvalidExtractionParameterError(
            f"--start-time ({_format_time(start_seconds)}) is beyond the video "
            f"duration ({_format_time(duration_seconds)})."
        )
    if (
        duration_seconds is not None
        and end_seconds is not None
        and end_seconds > duration_seconds + TIMESTAMP_EPSILON
    ):
        raise InvalidExtractionParameterError(
            f"--end-time ({_format_time(end_seconds)}) is beyond the video "
            f"duration ({_format_time(duration_seconds)})."
        )
    if end_seconds is not None and end_seconds <= start_seconds + TIMESTAMP_EPSILON:
        raise InvalidExtractionParameterError(
            f"--end-time ({_format_time(end_seconds)}) must be greater than "
            f"--start-time ({_format_time(start_seconds)})."
        )

    window = _candidate_frame_window(
        metadata,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        step=step,
    )
    try:
        return ExtractionParameters(
            engine=engine,
            requested_start_time=start_time,
            requested_end_time=end_time,
            requested_start_seconds=requested_start_seconds,
            requested_end_seconds=requested_end_seconds,
            effective_start_seconds=round(start_seconds, 3),
            effective_end_seconds=round(end_seconds, 3)
            if end_seconds is not None
            else None,
            effective_start_time=_format_time(start_seconds),
            effective_end_time=_format_time(end_seconds)
            if end_seconds is not None
            else None,
            start_defaulted=start_defaulted,
            end_defaulted=end_defaulted,
            duration_seconds_available=duration_seconds,
            crop=crop,
            sample_step=step,
            sample_start_frame=window.start_frame,
            sample_end_frame_exclusive=window.end_frame_exclusive,
            expected_candidate_frames=window.expected,
            first_candidate_frame=window.first,
            last_candidate_frame=window.last,
        )
    except ValidationError as exc:
        raise InvalidExtractionParameterError(
            f"invalid extraction parameters: {_validation_error_summary(exc)}"
        ) from exc


def _nearest_fps_tier(fps: float) -> int:
    """Snap a detected FPS to the nearest configured tier (30 / 60 / 120)."""
    return min(SAMPLE_STEP_BY_FPS_TIER, key=lambda tier: abs(tier - fps))


def adaptive_sample_step(fps: float) -> int:
    """Sampling step for the detected FPS — one candidate roughly every 0.5 s.

    Canonical screen-recording rates snap to the 30/60/120 tiers (unchanged).
    Rates below ``LOW_FPS_THRESHOLD`` (lightweight recorders) use ``fps / 2``
    directly: snapping a 10 fps video to the 30 tier would sample only every
    1.5 s and silently skip fast scrolling between candidates.
    """
    if fps < LOW_FPS_THRESHOLD:
        return max(1, round(fps / 2))
    return SAMPLE_STEP_BY_FPS_TIER[_nearest_fps_tier(fps)]


def sample_frames(
    video: Path,
    metadata: VideoMetadata,
    parameters: ExtractionParameters,
) -> Iterator[tuple[int, float, MatLike]]:
    """Yield sampled frames inside the selected segment on the original timeline."""
    cv2 = require_cv2()
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            fail(f"cannot open video for decoding: [cyan]{video}[/cyan]")
        if parameters.expected_candidate_frames == 0:
            return

        frame_number = parameters.sample_start_frame
        if frame_number:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            landed = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
            if landed != frame_number:
                _warn(
                    f"frame seek to {frame_number} landed on {landed} (the "
                    "decoder may only seek to keyframes); reported frame "
                    "numbers and timestamps in the outputs may be approximate."
                )

        decoded_any = False
        while frame_number < parameters.sample_end_frame_exclusive:
            ok, image = capture.read()
            if not ok:
                break
            decoded_any = True
            is_step_candidate = (
                frame_number - parameters.sample_start_frame
            ) % parameters.sample_step == 0
            is_forced_candidate = frame_number in FORCED_SAMPLE_FRAMES
            if is_step_candidate or is_forced_candidate:
                yield frame_number, frame_number / metadata.fps, image
            frame_number += 1
        if not decoded_any:
            fail(
                f"video [cyan]{video}[/cyan] opened but no frames could be decoded "
                "inside the selected segment; it may be corrupt, truncated, or in "
                "an unsupported format."
            )
    finally:
        capture.release()
