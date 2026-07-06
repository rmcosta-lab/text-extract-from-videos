"""Extract the source code shown in a screen-recording video via local OCR.

Phase 8: metadata (ffprobe with OpenCV fallback) → segment/crop parameter
resolution → FPS-adaptive frame sampling inside the effective interval →
preprocessing (crop → grayscale → upscale → Otsu threshold → denoise) → blur
and near-duplicate skipping → OCR on the preprocessed frames → reconstruction
(line-number merge when the editor shows numbers; otherwise video-time order
with scroll overlap deduplicated via rapidfuzz — best read by frequency /
confidence / sharpness, `[OCR_UNCERTAIN]` markers on low-confidence lines) →
gap detection on the numbered path (`detect_missing_lines()`) → outputs
(`metadata_video.json`, `extraction_parameters.json`, `ocr_raw.csv`,
`codigo_extraido.txt`, `relatorio_falhas.md`, `frames_usados/`). The failure
report surfaces every discarded frame, missing line, low-confidence passage,
and unextractable span — gaps are reported, never stitched over. Every named
failure mode (missing video, missing ffprobe/tesseract, undetectable FPS, empty
OCR, unwritable output directory) exits with code 1 and an actionable message;
`metadata_video.json`, `extraction_parameters.json`, and `frames_usados/` are
written before OCR-dependent stages where practical so failed runs stay
inspectable.
"""

import json
import math
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterable, Iterator
from fractions import Fraction
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Annotated, Any, Literal, NoReturn, Protocol, TypeAlias

import typer
from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz
from rich.console import Console
from rich.progress import track

if TYPE_CHECKING:
    from cv2.typing import MatLike
else:
    MatLike: TypeAlias = object

SAMPLE_STEP_BY_FPS_TIER = {30: 15, 60: 30, 120: 60}
"""Sampling step per FPS tier — roughly one candidate frame every 0.5 s."""

FORCED_SAMPLE_FRAMES = (1, 15)
"""Original-video frame numbers that are always sampled when inside the segment."""

UPSCALE_FACTOR = 2.0
"""Upscale factor applied to the grayscale frame before thresholding."""

DENOISE_KERNEL_SIZE = 3
"""Median-blur kernel that removes salt-and-pepper speckle after thresholding."""

BLUR_THRESHOLD = 100.0
"""Laplacian variance below this marks a frame as blurry (mid-scroll)."""

SSIM_THRESHOLD = 0.98
"""SSIM against the last accepted frame above this marks a near-duplicate."""

SSIM_COMPARE_WIDTH = 256
"""Frames are shrunk to this width before SSIM, for speed."""

LINE_NUMBER_RE = re.compile(
    r"^\s*(?P<number>\d{1,5})(?:(?P<punct_gap>\s*[:|.])"
    r"(?P<punct_content>.*)|(?P<space_content>[ \t]+.*))$"
)
"""Leading editor line number followed by whitespace, colon, pipe, or dot."""

LINE_NUMBER_ONLY_RE = re.compile(r"^\s*(?P<number>\d{1,5})\s*[:|.]?\s*$")
"""A gutter-only OCR line, possibly with a trailing separator."""

LINE_NUMBER_WORD_RE = re.compile(r"^\d{1,5}[:|.]?$")
"""A standalone gutter token in word-level OCR data."""

MIN_NUMBERED_SHARE = 0.35
"""Numbered reconstruction runs when enough reads carry a line number."""

MIN_INCREASING_SHARE = 0.8
"""...and detected numbers are increasing within a frame at least this often."""

OCR_UNCERTAIN_CONFIDENCE = 60.0
"""Merged lines whose best read is below this get an `[OCR_UNCERTAIN]` marker."""

FUZZY_MATCH_THRESHOLD = 85.0
"""rapidfuzz ratio (0-100) at/above which two reads count as the same line."""

MAX_FRAME_LINE_NUMBER_NEIGHBOR_DISTANCE = 30
"""Reject frame-local line numbers with no nearby numbered OCR evidence."""

TIMESTAMP_FORMAT_HELP = "seconds (12.5), MM:SS(.mmm), or HH:MM:SS(.mmm)"
"""Accepted CLI timestamp forms for segment bounds."""

SECONDS_ONLY_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
"""A seconds value such as ``12``, ``12.5``, or ``-1``."""

CLOCK_SECONDS_RE = re.compile(r"^\d+(?:\.\d+)?$")
"""Seconds component used in colon-delimited timestamps."""

TIMESTAMP_EPSILON = 1e-6
"""Small tolerance for comparing float timestamps against video duration."""

app = typer.Typer(add_completion=False)
console = Console()
err_console = Console(stderr=True)


def _fail(message: str) -> NoReturn:
    """Print a styled error message and exit with status 1."""
    err_console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _warn(message: str) -> None:
    """Print a styled warning message to stderr."""
    err_console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def _require_cv2() -> Any:
    """Import OpenCV only when video/image processing actually needs it."""
    try:
        import cv2  # noqa: PLC0415
    except ImportError:
        _fail(
            "OpenCV is required to read video frames and preprocess images. "
            "Install it with [bold]python -m pip install opencv-python[/bold], "
            "then re-run."
        )
    return cv2


def _require_pandas() -> Any:
    """Import pandas only when writing `ocr_raw.csv`."""
    try:
        import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        _fail(
            "pandas is required to write ocr_raw.csv. Install it with "
            "[bold]python -m pip install pandas[/bold], then re-run."
        )
    return pd


def _require_structural_similarity() -> Any:
    """Import scikit-image SSIM only when duplicate-frame detection runs."""
    try:
        from skimage.metrics import (  # type: ignore[import-untyped]  # noqa: PLC0415
            structural_similarity,
        )
    except ImportError:
        _fail(
            "scikit-image is required for near-duplicate frame detection. "
            "Install it with [bold]python -m pip install scikit-image[/bold], "
            "then re-run."
        )
    return structural_similarity


def _validation_error_summary(exc: ValidationError) -> str:
    """Compact Pydantic validation errors into one CLI-friendly sentence."""
    parts: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"])
        parts.append(f"{field}: {error['msg']}")
    return "; ".join(parts)


def _invalid_timestamp(option_name: str, value: str) -> NoReturn:
    """Fail with one consistent timestamp-format message."""
    _fail(
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


# --- Data models ---------------------------------------------------------


class VideoMetadata(BaseModel):
    """Metadata of the input video plus the sampling strategy of the run."""

    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    total_frames: int = Field(gt=0)
    codec: str | None = None
    source: Literal["ffprobe", "opencv"]
    sampling_strategy: str = ""
    """Set by `main()` once the adaptive step is chosen from the detected FPS."""


class InvalidVideoMetadataError(RuntimeError):
    """Raised when probed video metadata violates required invariants."""


def _build_video_metadata(**values: Any) -> VideoMetadata:
    """Construct metadata and turn Pydantic detail into an actionable error."""
    try:
        return VideoMetadata(**values)
    except ValidationError as exc:
        raise InvalidVideoMetadataError(_validation_error_summary(exc)) from exc


class OCRWord(BaseModel):
    """One word-level OCR token with geometry for conservative spacing."""

    text: str
    confidence: float | None = None
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class OCRLine(BaseModel):
    """One text line within an OCR engine read, with its own confidence."""

    text: str
    confidence: float | None = None
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None
    words: list[OCRWord] = Field(default_factory=list)
    """Word-level evidence used to preserve spacing and pair gutter/code OCR."""


class OCRResult(BaseModel):
    """One OCR engine read of a single image."""

    text: str
    confidence: float | None = None
    lines: list[OCRLine] = Field(default_factory=list)
    """Per-line reads backing `text`, in top-to-bottom image order."""


class OCRRow(BaseModel):
    """One `ocr_raw.csv` row: an OCR read tied to its exact frame and time."""

    text: str
    frame_number: int
    time_seconds: float
    time_formatted: str
    confidence: float | None = None
    sharpness: float = 0.0
    """Laplacian variance of the source frame — a merge quality signal."""
    frame_image_path: str
    lines: list[OCRLine] = Field(default_factory=list)
    """Per-line engine reads; feeds reconstruction, not the CSV."""


class LineRead(BaseModel):
    """One read of one on-screen code line, with provenance for tracing."""

    line_number: int | None = None
    content: str
    frame_number: int
    time_seconds: float
    time_formatted: str
    confidence: float | None = None
    sharpness: float = 0.0


class MergedLine(BaseModel):
    """The best read chosen for one reconstructed line of the output code."""

    read: LineRead
    uncertain: bool = False


class FrameOutcome(BaseModel):
    """Whether one sampled frame yielded usable text — feeds the failure report."""

    frame_number: int
    time_seconds: float
    time_formatted: str
    usable: bool
    """True when the frame survived selection and OCR returned non-blank text."""


# --- Metadata ------------------------------------------------------------


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
    cv2 = _require_cv2()
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            _fail(f"cannot open video with OpenCV: [cyan]{video}[/cyan]")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
    finally:
        capture.release()

    if fps <= 0:
        _fail(
            "FPS could not be detected by ffprobe or OpenCV; the video "
            f"[cyan]{video}[/cyan] may be corrupt or in an unsupported format."
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
        _fail(
            f"OpenCV returned invalid metadata for [cyan]{video}[/cyan]: {exc}. "
            "The video may be corrupt or in an unsupported format."
        )


def get_video_metadata(video: Path) -> VideoMetadata:
    """Read video metadata: ffprobe as primary source, OpenCV as fallback."""
    metadata = _metadata_from_ffprobe(video)
    if metadata is None:
        metadata = _metadata_from_opencv(video)
    return metadata


# --- Preprocessing & frame selection ---------------------------------------


class CropBox(BaseModel):
    """Pixels to trim from each edge before any other processing."""

    left: int = Field(default=0, ge=0)
    top: int = Field(default=0, ge=0)
    right: int = Field(default=0, ge=0)
    bottom: int = Field(default=0, ge=0)

    def validate_against(self, width: int, height: int) -> None:
        """Fail clearly if the crop leaves no image area at this resolution."""
        if self.left + self.right >= width:
            _fail(
                f"crop leaves no image area: left ({self.left}) + right "
                f"({self.right}) >= video width ({width})."
            )
        if self.top + self.bottom >= height:
            _fail(
                f"crop leaves no image area: top ({self.top}) + bottom "
                f"({self.bottom}) >= video height ({height})."
            )


class ExtractionParameters(BaseModel):
    """User-requested and effective extraction controls for one run."""

    requested_start_time: str | None = None
    requested_end_time: str | None = None
    requested_start_seconds: float | None = None
    requested_end_seconds: float | None = None
    effective_start_seconds: float = Field(ge=0)
    effective_end_seconds: float | None = None
    effective_start_time: str
    effective_end_time: str | None = None
    start_defaulted: bool
    end_defaulted: bool
    duration_seconds_available: float | None = None
    crop: CropBox
    sample_step: int = Field(gt=0)
    sample_start_frame: int = Field(ge=0)
    sample_end_frame_exclusive: int = Field(ge=0)
    expected_candidate_frames: int = Field(ge=0)
    first_candidate_frame: int | None = Field(default=None, ge=0)
    last_candidate_frame: int | None = Field(default=None, ge=0)


def _candidate_frame_window(
    metadata: VideoMetadata,
    *,
    start_seconds: float,
    end_seconds: float | None,
    step: int,
) -> tuple[int, int, int, int | None, int | None]:
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
        return start_frame, end_frame_exclusive, 0, None, None

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
    return start_frame, end_frame_exclusive, expected, first, last


def resolve_extraction_parameters(
    *,
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
        _fail(f"--start-time must be non-negative; got {start_seconds:g}.")
    if requested_end_seconds is not None and requested_end_seconds < 0:
        _fail(f"--end-time must be non-negative; got {requested_end_seconds:g}.")
    if (
        duration_seconds is not None
        and start_seconds > duration_seconds + TIMESTAMP_EPSILON
    ):
        _fail(
            f"--start-time ({_format_time(start_seconds)}) is beyond the video "
            f"duration ({_format_time(duration_seconds)})."
        )
    if (
        duration_seconds is not None
        and end_seconds is not None
        and end_seconds > duration_seconds + TIMESTAMP_EPSILON
    ):
        _fail(
            f"--end-time ({_format_time(end_seconds)}) is beyond the video "
            f"duration ({_format_time(duration_seconds)})."
        )
    if end_seconds is not None and end_seconds <= start_seconds + TIMESTAMP_EPSILON:
        _fail(
            f"--end-time ({_format_time(end_seconds)}) must be greater than "
            f"--start-time ({_format_time(start_seconds)})."
        )

    start_frame, end_frame_exclusive, expected, first, last = _candidate_frame_window(
        metadata,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        step=step,
    )
    try:
        return ExtractionParameters(
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
            sample_start_frame=start_frame,
            sample_end_frame_exclusive=end_frame_exclusive,
            expected_candidate_frames=expected,
            first_candidate_frame=first,
            last_candidate_frame=last,
        )
    except ValidationError as exc:
        _fail(f"invalid extraction parameters: {_validation_error_summary(exc)}")


class SelectionStats(BaseModel):
    """Counts of sampled frames discarded before OCR (feeds the failure report)."""

    frames_sampled: int = 0
    frames_discarded_blurry: int = 0
    frames_discarded_duplicate: int = 0

    @property
    def frames_kept(self) -> int:
        return (
            self.frames_sampled
            - self.frames_discarded_blurry
            - self.frames_discarded_duplicate
        )


def apply_crop(image: MatLike, crop: CropBox) -> MatLike:
    """Slice the frame to the crop box; an all-zero crop is the identity."""
    height, width = image.shape[:2]
    return image[crop.top : height - crop.bottom, crop.left : width - crop.right]


def _cropped_grayscale(image: MatLike, crop: CropBox) -> MatLike:
    """Crop then convert to grayscale — the input to selection and preprocessing."""
    cv2 = _require_cv2()
    return cv2.cvtColor(apply_crop(image, crop), cv2.COLOR_BGR2GRAY)


def preprocess_frame(image: MatLike, crop: CropBox) -> MatLike:
    """Prepare a frame for OCR: crop → grayscale → upscale → threshold → denoise."""
    cv2 = _require_cv2()
    gray = _cropped_grayscale(image, crop)
    upscaled = cv2.resize(
        gray, None, fx=UPSCALE_FACTOR, fy=UPSCALE_FACTOR, interpolation=cv2.INTER_CUBIC
    )
    _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if float(binary.mean()) < 127:
        # Dark editor theme: Tesseract reads dark-on-light best, so invert.
        binary = cv2.bitwise_not(binary)
    return cv2.medianBlur(binary, DENOISE_KERNEL_SIZE)


def frame_sharpness(gray_image: MatLike) -> float:
    """Laplacian variance — the sharpness score for the blur gate and merging."""
    cv2 = _require_cv2()
    return float(cv2.Laplacian(gray_image, cv2.CV_64F).var())


def is_frame_blurry(sharpness: float) -> bool:
    """Sharpness gate: True when the score is below ``BLUR_THRESHOLD``."""
    return sharpness < BLUR_THRESHOLD


def _ssim_thumbnail(gray_image: MatLike) -> MatLike:
    """Shrink a grayscale frame for fast SSIM (min 7 px, skimage's window size)."""
    cv2 = _require_cv2()
    height, width = gray_image.shape[:2]
    thumb_height = max(7, round(height * SSIM_COMPARE_WIDTH / width))
    return cv2.resize(
        gray_image, (SSIM_COMPARE_WIDTH, thumb_height), interpolation=cv2.INTER_AREA
    )


# --- OCR engine seam ------------------------------------------------------


class OCREngineUnavailableError(RuntimeError):
    """Raised when an OCR engine's backing binary is not installed."""


class OCREngine(Protocol):
    """Narrow OCR seam: one image in, one :class:`OCRResult` out."""

    def recognize(self, image: MatLike) -> OCRResult: ...


def _require_pytesseract() -> Any:
    """Import pytesseract only when the Tesseract engine is instantiated."""
    try:
        import pytesseract  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise OCREngineUnavailableError(
            "the pytesseract Python package is not installed. Install it with "
            "[bold]python -m pip install pytesseract[/bold], then re-run."
        ) from exc
    return pytesseract


def _parse_tesseract_int(value: object) -> int:
    """Parse integer-ish Tesseract fields, defaulting invalid geometry to 0."""
    try:
        return max(0, int(float(str(value))))
    except ValueError:
        return 0


def _parse_tesseract_confidence(value: object) -> float | None:
    """Parse a Tesseract confidence value; `-1` means no confidence."""
    try:
        confidence = float(str(value))
    except ValueError:
        return None
    return confidence if confidence >= 0 else None


def _mean_confidence(values: Iterable[float | None]) -> float | None:
    """Mean of present confidence values, rounded for stable artifacts."""
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 2) if present else None


def _word_right(word: OCRWord) -> int:
    """Right edge of one OCR word bounding box."""
    return word.left + word.width


def _line_right(line: OCRLine) -> int | None:
    """Right edge of one OCR line bounding box when geometry is available."""
    if line.left is None or line.width is None:
        return None
    return line.left + line.width


def _median_char_width(words: list[OCRWord]) -> float:
    """Estimate character width from OCR word boxes for spacing reconstruction."""
    widths = [
        word.width / len(word.text) for word in words if word.text and word.width > 0
    ]
    return max(1.0, float(median(widths))) if widths else 8.0


def _reconstruct_words(words: list[OCRWord], *, origin_left: int | None = None) -> str:
    """Rebuild a line from word boxes, preserving measured spaces only."""
    ordered = sorted(words, key=lambda word: word.left)
    if not ordered:
        return ""

    char_width = _median_char_width(ordered)
    origin = ordered[0].left if origin_left is None else origin_left
    pieces: list[str] = []
    first_gap = ordered[0].left - origin
    if first_gap > char_width * 0.75:
        pieces.append(" " * max(0, round(first_gap / char_width)))

    cursor = _word_right(ordered[0])
    pieces.append(ordered[0].text)
    for word in ordered[1:]:
        gap = word.left - cursor
        if gap > char_width * 0.5:
            pieces.append(" " * max(1, round(gap / char_width)))
        pieces.append(word.text)
        cursor = max(cursor, _word_right(word))
    return "".join(pieces)


def _build_ocr_line(words: list[OCRWord], *, origin_left: int | None) -> OCRLine:
    """Build one line model with geometry and evidence-preserving text."""
    left = min(word.left for word in words)
    top = min(word.top for word in words)
    right = max(_word_right(word) for word in words)
    bottom = max(word.top + word.height for word in words)
    return OCRLine(
        text=_reconstruct_words(words, origin_left=origin_left),
        confidence=_mean_confidence(word.confidence for word in words),
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
        words=sorted(words, key=lambda word: word.left),
    )


class TesseractEngine:
    """`OCREngine` implementation backed by pytesseract / Tesseract.

    The rest of the pipeline must depend only on :class:`OCREngine`;
    pytesseract is referenced exclusively inside this class.
    """

    def __init__(self) -> None:
        self._pytesseract = _require_pytesseract()
        try:
            self._pytesseract.get_tesseract_version()
        except self._pytesseract.TesseractNotFoundError as exc:
            raise OCREngineUnavailableError(
                "the tesseract binary is not installed. Install it with "
                "[bold]brew install tesseract[/bold] (macOS) or your system "
                "package manager, then re-run."
            ) from exc

    def recognize(self, image: MatLike) -> OCRResult:
        """OCR the whole image; per-line reads with mean word confidence each."""
        data = self._pytesseract.image_to_data(
            image,
            config="-c preserve_interword_spaces=1",
            output_type=self._pytesseract.Output.DICT,
        )
        words_by_line: dict[tuple[int, int, int], list[OCRWord]] = {}
        words = zip(
            data["text"],
            data["conf"],
            data["block_num"],
            data["par_num"],
            data["line_num"],
            data["left"],
            data["top"],
            data["width"],
            data["height"],
            strict=True,
        )
        for word, conf, block, paragraph, line, left, top, width, height in words:
            if not word.strip():
                continue
            key = (
                _parse_tesseract_int(block),
                _parse_tesseract_int(paragraph),
                _parse_tesseract_int(line),
            )
            words_by_line.setdefault(key, []).append(
                OCRWord(
                    text=str(word),
                    confidence=_parse_tesseract_confidence(conf),
                    left=_parse_tesseract_int(left),
                    top=_parse_tesseract_int(top),
                    width=_parse_tesseract_int(width),
                    height=_parse_tesseract_int(height),
                )
            )

        all_words = [
            word for words_in_line in words_by_line.values() for word in words_in_line
        ]
        if not all_words:
            return OCRResult(text="", confidence=None, lines=[])

        origin_left = min(word.left for word in all_words)
        lines = [
            _build_ocr_line(words_in_line, origin_left=origin_left)
            for words_in_line in words_by_line.values()
        ]
        lines.sort(
            key=lambda line: (line.top if line.top is not None else 0, line.left or 0)
        )
        mean_confidence = _mean_confidence(word.confidence for word in all_words)
        text = "\n".join(line.text for line in lines)
        return OCRResult(text=text, confidence=mean_confidence, lines=lines)


# --- Sampling & OCR pipeline ----------------------------------------------


def _nearest_fps_tier(fps: float) -> int:
    """Snap a detected FPS to the nearest configured tier (30 / 60 / 120)."""
    return min(SAMPLE_STEP_BY_FPS_TIER, key=lambda tier: abs(tier - fps))


def adaptive_sample_step(fps: float) -> int:
    """Sampling step for the detected FPS — one candidate roughly every 0.5 s."""
    return SAMPLE_STEP_BY_FPS_TIER[_nearest_fps_tier(fps)]


def sample_frames(
    video: Path,
    metadata: VideoMetadata,
    parameters: ExtractionParameters,
) -> Iterator[tuple[int, float, MatLike]]:
    """Yield sampled frames inside the selected segment on the original timeline."""
    cv2 = _require_cv2()
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            _fail(f"cannot open video for decoding: [cyan]{video}[/cyan]")
        if parameters.expected_candidate_frames == 0:
            return

        frame_number = parameters.sample_start_frame
        if frame_number:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

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
            _fail(
                f"video [cyan]{video}[/cyan] opened but no frames could be decoded "
                "inside the selected segment; it may be corrupt, truncated, or in "
                "an unsupported format."
            )
    finally:
        capture.release()


def _format_time(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm``."""
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    s = total_ms // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}.{ms:03d}"


def run_ocr(
    frames: Iterable[tuple[int, float, MatLike]],
    engine: OCREngine,
    frames_dir: Path,
    expected_samples: int,
    crop: CropBox,
) -> tuple[list[OCRRow], SelectionStats, list[FrameOutcome]]:
    """OCR the sampled frames that survive selection.

    Per candidate: crop + grayscale → blur gate → SSIM near-duplicate gate
    against the last accepted frame → full preprocessing → save the
    preprocessed image (what OCR actually sees) to `frames_usados/` → OCR.
    An empty OCR read is recorded as a row with empty text, not an error.
    Every sampled frame also yields a :class:`FrameOutcome` — usable only
    when it was kept and OCR returned non-blank text — so the failure report
    can surface unextractable time spans from observed outcomes.
    """
    rows: list[OCRRow] = []
    stats = SelectionStats()
    outcomes: list[FrameOutcome] = []
    cv2 = _require_cv2()
    structural_similarity = _require_structural_similarity()

    def record_outcome(frame_number: int, time_seconds: float, usable: bool) -> None:
        outcomes.append(
            FrameOutcome(
                frame_number=frame_number,
                time_seconds=round(time_seconds, 3),
                time_formatted=_format_time(time_seconds),
                usable=usable,
            )
        )

    last_accepted_thumbnail: MatLike | None = None
    progress = track(
        frames,
        total=expected_samples,
        description="OCR on sampled frames...",
        console=console,
    )
    for frame_number, time_seconds, image in progress:
        stats.frames_sampled += 1
        gray = _cropped_grayscale(image, crop)
        sharpness = frame_sharpness(gray)
        if is_frame_blurry(sharpness):
            stats.frames_discarded_blurry += 1
            record_outcome(frame_number, time_seconds, usable=False)
            continue
        thumbnail = _ssim_thumbnail(gray)
        if last_accepted_thumbnail is not None:
            score = structural_similarity(
                thumbnail, last_accepted_thumbnail, data_range=255
            )
            if score > SSIM_THRESHOLD:
                stats.frames_discarded_duplicate += 1
                record_outcome(frame_number, time_seconds, usable=False)
                continue
        last_accepted_thumbnail = thumbnail

        processed = preprocess_frame(image, crop)
        frame_path = frames_dir / f"frame_{frame_number}.png"
        if not cv2.imwrite(str(frame_path), processed):
            _fail(f"could not save frame image: [cyan]{frame_path}[/cyan]")
        result = engine.recognize(processed)
        record_outcome(frame_number, time_seconds, usable=bool(result.text.strip()))
        rows.append(
            OCRRow(
                text=result.text,
                frame_number=frame_number,
                time_seconds=round(time_seconds, 3),
                time_formatted=_format_time(time_seconds),
                confidence=result.confidence,
                sharpness=round(sharpness, 2),
                frame_image_path=str(frame_path),
                lines=result.lines,
            )
        )
    return rows, stats, outcomes


# --- Reconstruction --------------------------------------------------------


def _split_numbered_text(text: str) -> tuple[int, str] | None:
    """Split text that begins with an editor gutter number plus separator."""
    match = LINE_NUMBER_RE.match(text)
    if not match:
        return None

    number = int(match.group("number"))
    punct_content = match.group("punct_content")
    if punct_content is not None:
        return number, punct_content

    space_content = match.group("space_content") or ""
    # In the plain form (`12 print(...)`), one whitespace character is the
    # separator; additional spaces are evidence of indentation.
    return number, space_content[1:]


def _number_only_line_number(text: str) -> int | None:
    """Return the gutter number from a number-only OCR line, if present."""
    match = LINE_NUMBER_ONLY_RE.match(text)
    return int(match.group("number")) if match else None


def _line_center_y(line: OCRLine) -> float | None:
    """Vertical center of an OCR line when geometry is available."""
    if line.top is None or line.height is None:
        return None
    return line.top + line.height / 2


def _content_words_after_gutter(line: OCRLine) -> list[OCRWord] | None:
    """Return word boxes after a standalone gutter token, if the line has one."""
    if len(line.words) < 2:
        return None
    if not LINE_NUMBER_WORD_RE.match(line.words[0].text.strip()):
        return None

    index = 1
    while index < len(line.words) and line.words[index].text.strip() in {":", "|", "."}:
        index += 1
    return line.words[index:]


def _code_origin_for_frame(lines: list[OCRLine]) -> int | None:
    """Left edge of the code column inferred from word geometry in one frame."""
    origins: list[int] = []
    for line in lines:
        content_words = _content_words_after_gutter(line)
        if content_words:
            origins.append(content_words[0].left)
            continue
        if _number_only_line_number(line.text) is not None:
            continue
        if _split_numbered_text(line.text) is not None:
            continue
        if line.left is not None:
            origins.append(line.left)
    return min(origins) if origins else None


def _line_content_from_words(line: OCRLine, code_origin: int | None) -> str:
    """Render one code OCR line from word boxes when possible."""
    if line.words:
        return _reconstruct_words(line.words, origin_left=code_origin)
    return line.text


def _content_from_numbered_line(
    line: OCRLine, fallback_content: str, code_origin: int | None
) -> str:
    """Extract content after a gutter number, preferring positional evidence."""
    content_words = _content_words_after_gutter(line)
    if content_words is not None:
        return _reconstruct_words(content_words, origin_left=code_origin)
    return fallback_content


def _combined_confidence(*values: float | None) -> float | None:
    """Mean confidence for paired OCR lines."""
    return _mean_confidence(values)


def _find_paired_code_line(
    gutter_index: int, lines: list[OCRLine], paired_code_lines: set[int]
) -> int | None:
    """Find code text OCR'd separately from a gutter-only line number."""
    gutter = lines[gutter_index]
    gutter_center = _line_center_y(gutter)
    gutter_right = _line_right(gutter)
    candidates: list[tuple[float, int, int, int]] = []

    for index, line in enumerate(lines):
        if index == gutter_index or index in paired_code_lines:
            continue
        if not line.text.strip():
            continue
        if _number_only_line_number(line.text) is not None:
            continue
        if _split_numbered_text(line.text) is not None:
            continue
        if (
            gutter_right is not None
            and line.left is not None
            and line.left <= gutter_right
        ):
            continue
        if (
            gutter.left is not None
            and line.left is not None
            and line.left <= gutter.left
        ):
            continue

        line_center = _line_center_y(line)
        if gutter_center is None or line_center is None:
            if abs(index - gutter_index) > 1:
                continue
            vertical_distance = 0.0
        else:
            vertical_distance = abs(line_center - gutter_center)
            max_height = max(gutter.height or 0, line.height or 0, 12)
            if vertical_distance > max(8.0, max_height * 0.75):
                continue

        candidates.append(
            (vertical_distance, abs(index - gutter_index), line.left or 10**9, index)
        )

    if not candidates:
        return None
    return min(candidates)[-1]


def _to_line_read(
    row: OCRRow,
    *,
    line_number: int | None,
    content: str,
    confidence: float | None,
) -> LineRead:
    """Build a line read while copying frame provenance from its OCR row."""
    return LineRead(
        line_number=line_number,
        content=content,
        frame_number=row.frame_number,
        time_seconds=row.time_seconds,
        time_formatted=row.time_formatted,
        confidence=confidence,
        sharpness=row.sharpness,
    )


def _filter_frame_line_number_outliers(reads: list[LineRead]) -> list[LineRead]:
    """Drop implausible frame-local gutter numbers without guessing a repair."""
    numbered = [read.line_number for read in reads if read.line_number is not None]
    if len(numbered) < 3:
        return reads

    filtered: list[LineRead] = []
    for read in reads:
        if read.line_number is None:
            filtered.append(read)
            continue

        neighbors = [number for number in numbered if number != read.line_number]
        if not neighbors:
            filtered.append(read)
            continue
        nearest = min(abs(read.line_number - number) for number in neighbors)
        if nearest <= MAX_FRAME_LINE_NUMBER_NEIGHBOR_DISTANCE:
            filtered.append(read)
            continue

        # Preserve the OCR content and provenance, but do not let one isolated
        # gutter glitch create a fabricated line number or thousands of gaps.
        filtered.append(read.model_copy(update={"line_number": None}))
    return filtered


def parse_code_lines(
    rows: list[OCRRow], *, strip_line_numbers: bool = True
) -> list[LineRead]:
    """Split each frame read into per-line reads, extracting leading line numbers.

    Numbered reads can be plain (`12 print(...)`), colon/pipe separated
    (`12:print(...)`, `12|print(...)`), or split into neighboring OCR lines
    where the gutter number and code text have separate boxes. Content is
    reconstructed from word geometry when available so indentation and
    meaningful intra-line spacing survive the OCR stage.

    With ``strip_line_numbers=False`` every line keeps its full text — used by
    the unnumbered path so code that merely starts with an integer is not cut.
    """
    reads: list[LineRead] = []
    for row in rows:
        frame_reads: list[LineRead] = []
        frame_lines = [line for line in row.lines if line.text.strip()]
        if not strip_line_numbers:
            for line in frame_lines:
                frame_reads.append(
                    _to_line_read(
                        row,
                        line_number=None,
                        content=line.text,
                        confidence=line.confidence,
                    )
                )
            reads.extend(frame_reads)
            continue

        code_origin = _code_origin_for_frame(frame_lines)
        paired_code_lines: set[int] = set()
        gutter_pairs: dict[int, int] = {}
        for index, line in enumerate(frame_lines):
            if _number_only_line_number(line.text) is None:
                continue
            pair = _find_paired_code_line(index, frame_lines, paired_code_lines)
            if pair is not None:
                gutter_pairs[index] = pair
                paired_code_lines.add(pair)

        for index, line in enumerate(frame_lines):
            if index in paired_code_lines:
                continue
            if not line.text.strip():
                continue

            number_only = _number_only_line_number(line.text)
            if number_only is not None:
                paired_index = gutter_pairs.get(index)
                if paired_index is None:
                    frame_reads.append(
                        _to_line_read(
                            row,
                            line_number=number_only,
                            content="",
                            confidence=line.confidence,
                        )
                    )
                    continue

                code_line = frame_lines[paired_index]
                frame_reads.append(
                    _to_line_read(
                        row,
                        line_number=number_only,
                        content=_line_content_from_words(code_line, code_origin),
                        confidence=_combined_confidence(
                            line.confidence, code_line.confidence
                        ),
                    )
                )
                continue

            split = _split_numbered_text(line.text)
            if split:
                line_number, fallback_content = split
                content = _content_from_numbered_line(
                    line, fallback_content, code_origin
                )
            else:
                line_number = None
                content = line.text
            frame_reads.append(
                _to_line_read(
                    row,
                    line_number=line_number,
                    content=content,
                    confidence=line.confidence,
                )
            )
        reads.extend(_filter_frame_line_number_outliers(frame_reads))
    return reads


def has_line_numbers(reads: list[LineRead]) -> bool:
    """Decide whether the video shows editor line numbers.

    True when enough reads carry a leading number (``MIN_NUMBERED_SHARE``) and
    those numbers are mostly increasing within each frame
    (``MIN_INCREASING_SHARE``) — guarding against code that merely starts
    with integers.
    """
    if not reads:
        return False
    numbered = [read for read in reads if read.line_number is not None]
    if len(numbered) / len(reads) < MIN_NUMBERED_SHARE:
        return False

    increasing = 0
    total_pairs = 0
    by_frame: dict[int, list[int]] = {}
    for read in numbered:
        assert read.line_number is not None
        by_frame.setdefault(read.frame_number, []).append(read.line_number)
    for numbers in by_frame.values():
        for previous, current in zip(numbers, numbers[1:], strict=False):
            total_pairs += 1
            if current > previous:
                increasing += 1
    if total_pairs == 0:
        return True
    return increasing / total_pairs >= MIN_INCREASING_SHARE


def _normalized(text: str) -> str:
    """Collapse whitespace for frequency counting and fuzzy comparison."""
    return " ".join(text.split())


def _same_line(a: str, b: str) -> bool:
    """Fuzzy-decide whether two reads show the same on-screen line.

    Comparison only — the texts are never blended, averaged, or repaired.
    """
    return fuzz.ratio(_normalized(a), _normalized(b)) >= FUZZY_MATCH_THRESHOLD


def _best_read(group: list[LineRead]) -> MergedLine:
    """Pick a group's best read: frequency, then confidence, then sharpness.

    The most frequent content wins (whitespace-normalized for counting),
    ties broken by confidence then frame sharpness. The winning read's
    content is emitted verbatim — reads are never blended. Below
    ``OCR_UNCERTAIN_CONFIDENCE`` (or with no confidence at all) the line is
    flagged uncertain.
    """
    frequency = Counter(_normalized(read.content) for read in group)
    top_count = max(frequency.values())
    finalists = [
        read for read in group if frequency[_normalized(read.content)] == top_count
    ]
    winner = max(
        finalists,
        key=lambda read: (
            read.confidence if read.confidence is not None else -1.0,
            read.sharpness,
        ),
    )
    uncertain = (
        winner.confidence is None or winner.confidence < OCR_UNCERTAIN_CONFIDENCE
    )
    return MergedLine(read=winner, uncertain=uncertain)


def merge_ocr_results(reads: list[LineRead]) -> list[MergedLine]:
    """Consolidate repeated reads of each numbered line into one best read.

    Reads are grouped by detected line number and each group's winner is
    chosen by :func:`_best_read`; the result is ordered by line number.
    Gaps in numbering are left as gaps.
    """
    by_number: dict[int, list[LineRead]] = {}
    for read in reads:
        if read.line_number is not None:
            by_number.setdefault(read.line_number, []).append(read)
    return [_best_read(by_number[number]) for number in sorted(by_number)]


def _overlap_length(document: list[list[LineRead]], frame_lines: list[LineRead]) -> int:
    """Longest document suffix whose lines all fuzzy-match the frame's head.

    Tried from the longest candidate down; every aligned pair must match, so
    an ambiguous alignment yields 0 (keeping a duplicate) rather than a
    partial merge that could drop a real line.
    """
    for overlap in range(min(len(document), len(frame_lines)), 0, -1):
        start = len(document) - overlap
        if all(
            _same_line(frame_lines[index].content, document[start + index][-1].content)
            for index in range(overlap)
        ):
            return overlap
    return 0


def reconstruct_by_time(reads: list[LineRead]) -> list[MergedLine]:
    """Reconstruct unnumbered code in video-time order, deduplicating scroll.

    Frames are processed in ascending time; within a frame, lines keep their
    on-screen top-to-bottom order. Each frame's lines are aligned against the
    tail of the document built so far: the overlapping reads join the
    existing per-line groups, only the lines past the overlap are appended as
    new. With no overlap the whole frame is appended — a duplicate is always
    preferable to a dropped line. Each group's winner is then chosen by
    :func:`_best_read`, verbatim.
    """
    by_frame: dict[int, list[LineRead]] = {}
    for read in reads:
        by_frame.setdefault(read.frame_number, []).append(read)

    document: list[list[LineRead]] = []
    for frame_number in sorted(by_frame):
        frame_lines = by_frame[frame_number]
        overlap = _overlap_length(document, frame_lines)
        start = len(document) - overlap
        for index, read in enumerate(frame_lines):
            if index < overlap:
                document[start + index].append(read)
            else:
                document.append([read])
    return [_best_read(group) for group in document]


# --- Gap detection & failure report -----------------------------------------


class GapNeighbor(BaseModel):
    """The nearest extracted line on one side of a numbering gap."""

    line_number: int
    frame_number: int
    time_seconds: float
    time_formatted: str


class MissingLine(BaseModel):
    """One line number absent from the numbered reconstruction.

    Either neighbor is None when the gap touches the start or end of the
    numbering — the report then says so instead of fabricating a timestamp.
    """

    line_number: int
    before: GapNeighbor | None = None
    after: GapNeighbor | None = None


class TimeSpan(BaseModel):
    """A contiguous run of sampled frames that yielded no usable text."""

    start_seconds: float
    end_seconds: float
    start_formatted: str
    end_formatted: str
    frames: int


class FailureReport(BaseModel):
    """Everything `relatorio_falhas.md` renders, aggregated from run data."""

    video_path: str
    metadata: VideoMetadata
    stats: SelectionStats
    lines_extracted: int
    line_numbers_detected: bool
    missing_lines: list[MissingLine] = Field(default_factory=list)
    uncertain_lines: list[MergedLine] = Field(default_factory=list)
    unextractable: list[TimeSpan] = Field(default_factory=list)


def _gap_neighbor(item: MergedLine) -> GapNeighbor:
    """Provenance of a merged line as one side of a numbering gap."""
    read = item.read
    assert read.line_number is not None
    return GapNeighbor(
        line_number=read.line_number,
        frame_number=read.frame_number,
        time_seconds=read.time_seconds,
        time_formatted=read.time_formatted,
    )


def detect_missing_lines(merged: list[MergedLine]) -> list[MissingLine]:
    """Flag every line number absent from the numbered reconstruction.

    Walks the numbered merged lines in line-number order: each jump greater
    than 1 yields one :class:`MissingLine` per absent number, carrying the
    surrounding lines' timestamps; numbering that starts above 1 yields the
    leading numbers as gaps with no before-neighbor. Reads without line
    numbers (the time-ordered path) produce no gaps — where numbering is
    absent, missing lines are never guessed. Empty and single-line input
    return an empty list.
    """
    numbered = sorted(
        (
            (item.read.line_number, item)
            for item in merged
            if item.read.line_number is not None
        ),
        key=lambda pair: pair[0],
    )
    if not numbered:
        return []

    missing: list[MissingLine] = []
    first_number, first_item = numbered[0]
    for absent in range(1, first_number):
        missing.append(MissingLine(line_number=absent, after=_gap_neighbor(first_item)))
    for (previous_number, previous_item), (next_number, next_item) in zip(
        numbered, numbered[1:], strict=False
    ):
        for absent in range(previous_number + 1, next_number):
            missing.append(
                MissingLine(
                    line_number=absent,
                    before=_gap_neighbor(previous_item),
                    after=_gap_neighbor(next_item),
                )
            )
    return missing


def unextractable_sections(outcomes: list[FrameOutcome]) -> list[TimeSpan]:
    """Group consecutive unusable sampled frames into (start, end) time spans.

    Spans come only from observed per-frame outcomes — frames discarded as
    blurry / near-duplicate or whose OCR came back blank; content is never
    inferred.
    """
    spans: list[TimeSpan] = []
    run: list[FrameOutcome] = []

    def flush_run() -> None:
        if run:
            spans.append(
                TimeSpan(
                    start_seconds=run[0].time_seconds,
                    end_seconds=run[-1].time_seconds,
                    start_formatted=run[0].time_formatted,
                    end_formatted=run[-1].time_formatted,
                    frames=len(run),
                )
            )
            run.clear()

    for outcome in outcomes:
        if outcome.usable:
            flush_run()
        else:
            run.append(outcome)
    flush_run()
    return spans


CAPTURE_RECOMMENDATIONS = [
    "Grave em resolução maior (1080p ou superior).",
    "Reduza a velocidade do scroll durante a gravação.",
    "Aumente a fonte do editor de código.",
    "Use um tema de alto contraste no editor.",
]
"""Static capture recommendations mandated by the README, always included."""

BLURRY_SHARE_WARNING = 0.3
"""Above this share of blurry discards, the report reinforces slower scrolling."""


def _missing_line_entry(missing: MissingLine) -> str:
    """Render one missing line per the README phrasing, without inventing times."""
    if missing.before and missing.after:
        # Scroll overlap means the neighbors' best reads may come from any
        # frame each line appears in; render the window chronologically.
        first, second = sorted(
            (missing.before, missing.after), key=lambda side: side.time_seconds
        )
        return (
            f"Linha {missing.line_number} possivelmente ausente entre os tempos "
            f"{first.time_formatted} e {second.time_formatted}."
        )
    if missing.after:
        return (
            f"Linha {missing.line_number} possivelmente ausente antes do tempo "
            f"{missing.after.time_formatted} (sem linha extraída antes da lacuna)."
        )
    if missing.before:
        return (
            f"Linha {missing.line_number} possivelmente ausente depois do tempo "
            f"{missing.before.time_formatted} (sem linha extraída depois da lacuna)."
        )
    return (
        f"Linha {missing.line_number} possivelmente ausente "
        "(sem linhas vizinhas extraídas)."
    )


def _uncertain_entry(item: MergedLine) -> str:
    """Render one low-confidence merged line with its frame/time provenance."""
    read = item.read
    line_part = f"linha {read.line_number}, " if read.line_number is not None else ""
    confidence = f"{read.confidence:.1f}" if read.confidence is not None else "n/d"
    return (
        f"- {line_part}frame={read.frame_number}, tempo={read.time_formatted}, "
        f'confiança={confidence}: `"{read.content}"`'
    )


def _write_text_file(path: Path, content: str) -> None:
    """Write a text output file, naming the path on permission failures."""
    try:
        path.write_text(content, "utf-8")
    except OSError as exc:
        _fail(f"cannot write output file [cyan]{path}[/cyan]: {exc}")


def write_failure_report(report: FailureReport, output: Path) -> None:
    """Render `relatorio_falhas.md` in Portuguese, one section per README item.

    Counts are always stated, including zeros. Failures are surfaced, never
    repaired: missing lines stay absent from `codigo_extraido.txt`.
    """
    metadata = report.metadata
    stats = report.stats
    lines = [
        "# Relatório de falhas",
        "",
        "## Resumo do vídeo",
        "",
        f"- Arquivo: `{report.video_path}`",
        f"- Resolução: {metadata.width}x{metadata.height}",
        f"- Duração: {metadata.duration_seconds:g}s "
        f"({_format_time(metadata.duration_seconds)})",
        f"- Total de frames: {metadata.total_frames}",
        f"- Codec: {metadata.codec or 'desconhecido'}",
        f"- Fonte dos metadados: {metadata.source}",
        "",
        "## FPS detectado",
        "",
        f"- FPS detectado: {metadata.fps:g}",
        f"- Estratégia de amostragem: `{metadata.sampling_strategy}`",
        "",
        "## Frames analisados",
        "",
        f"- Frames amostrados (analisados): {stats.frames_sampled}",
        f"- Frames mantidos para OCR: {stats.frames_kept}",
        "",
        "## Frames descartados por baixa nitidez",
        "",
        f"- Descartados por baixa nitidez (borrados): {stats.frames_discarded_blurry}",
        f"- Descartados como quase duplicados: {stats.frames_discarded_duplicate}",
        "",
        "## Linhas extraídas",
        "",
        f"- Linhas extraídas: {report.lines_extracted}",
    ]
    if report.line_numbers_detected:
        lines.append("- Reconstrução: por número de linha (numeração visível).")
    else:
        lines.append(
            "- Reconstrução: por ordem temporal (sem números de linha visíveis)."
        )
    if report.lines_extracted == 0:
        lines.append("- Nenhuma linha pôde ser extraída deste vídeo.")

    lines += ["", "## Linhas faltantes", ""]
    if not report.line_numbers_detected:
        lines.append(
            "A detecção de lacunas requer números de linha visíveis no editor. "
            "Este vídeo foi reconstruído sem numeração, portanto nenhuma lacuna "
            "pôde ser verificada — linhas faltantes nunca são adivinhadas."
        )
    else:
        lines.append(f"- Linhas possivelmente ausentes: {len(report.missing_lines)}")
        if report.missing_lines:
            lines.append("")
            lines += [_missing_line_entry(missing) for missing in report.missing_lines]
        else:
            lines.append("- Nenhuma linha faltante detectada.")

    lines += [
        "",
        "## Trechos com baixa confiança",
        "",
        f"- Trechos com baixa confiança: {len(report.uncertain_lines)}",
    ]
    if report.uncertain_lines:
        lines.append(
            "- Cada trecho está marcado com `[OCR_UNCERTAIN]` em "
            "`codigo_extraido.txt`; o frame correspondente está em "
            "`frames_usados/` e a leitura bruta em `ocr_raw.csv`."
        )
        lines.append("")
        lines += [_uncertain_entry(item) for item in report.uncertain_lines]
    else:
        lines.append("- Nenhum trecho com baixa confiança.")

    lines += [
        "",
        "## Trechos impossíveis de extrair",
        "",
        f"- Trechos sem texto utilizável: {len(report.unextractable)}",
    ]
    if report.unextractable:
        lines.append("")
        lines += [
            f"- De {span.start_formatted} a {span.end_formatted} "
            f"({span.frames} frame(s) amostrado(s) sem texto utilizável — "
            "descartados ou com OCR vazio)."
            for span in report.unextractable
        ]
    else:
        lines.append("- Nenhum trecho impossível de extrair.")

    lines += ["", "## Recomendações de captura", ""]
    lines += [f"- {item}" for item in CAPTURE_RECOMMENDATIONS]
    if (
        stats.frames_sampled
        and stats.frames_discarded_blurry / stats.frames_sampled > BLURRY_SHARE_WARNING
    ):
        lines.append(
            f"- Atenção: {stats.frames_discarded_blurry} de "
            f"{stats.frames_sampled} frames amostrados foram descartados por "
            "baixa nitidez — reduzir a velocidade do scroll deve melhorar "
            "bastante a extração."
        )

    report_path = output / "relatorio_falhas.md"
    _write_text_file(report_path, "\n".join(lines) + "\n")


# --- Outputs ---------------------------------------------------------------


def _clear_frames_dir(frames_dir: Path) -> None:
    """Remove stale frame artifacts so `frames_usados/` is run-scoped."""
    for child in frames_dir.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            _fail(f"cannot remove stale frame artifact [cyan]{child}[/cyan]: {exc}")


def prepare_output_tree(output: Path) -> Path:
    """Create the output tree, verify writability, and clear stale frames."""
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"cannot create output directory [cyan]{output}[/cyan]: {exc}")
    if not output.is_dir():
        _fail(f"output path is not a directory: [cyan]{output}[/cyan]")

    frames_dir = output / "frames_usados"
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"cannot create frames directory [cyan]{frames_dir}[/cyan]: {exc}")

    probe = output / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        _fail(f"output directory [cyan]{output}[/cyan] is not writable: {exc}")

    _clear_frames_dir(frames_dir)
    return frames_dir


def _uncertain_marker(read: LineRead) -> str:
    """The exact `[OCR_UNCERTAIN]` comment mandated by the mission spec."""
    return (
        f"# [OCR_UNCERTAIN] frame={read.frame_number} "
        f'time={read.time_formatted} texto_original="{read.content}"'
    )


def write_metadata(metadata: VideoMetadata, output: Path) -> None:
    """Write `metadata_video.json`.

    Called as soon as the sampling strategy is known — before OCR — so that
    even a run that fails later (e.g. empty OCR) leaves the metadata on disk
    for inspection.
    """
    metadata_path = output / "metadata_video.json"
    _write_text_file(metadata_path, metadata.model_dump_json(indent=2) + "\n")


def write_extraction_parameters(parameters: ExtractionParameters, output: Path) -> None:
    """Write the effective extraction settings for reproducible inspection."""
    parameters_path = output / "extraction_parameters.json"
    _write_text_file(parameters_path, parameters.model_dump_json(indent=2) + "\n")


def write_ocr_raw(rows: list[OCRRow], output: Path) -> None:
    """Write the raw OCR inspection CSV."""
    pd = _require_pandas()
    ordered = sorted(rows, key=lambda row: row.time_seconds)
    frame = pd.DataFrame(
        {
            "text": [row.text for row in ordered],
            "frame": [row.frame_number for row in ordered],
            "time": [row.time_formatted for row in ordered],
            "confidence": [row.confidence for row in ordered],
            "sharpness": [row.sharpness for row in ordered],
            "frame_image_path": [row.frame_image_path for row in ordered],
        }
    )
    csv_path = output / "ocr_raw.csv"
    try:
        frame.to_csv(csv_path, index=False)
    except OSError as exc:
        _fail(f"cannot write output file [cyan]{csv_path}[/cyan]: {exc}")


def write_extracted_code(merged: list[MergedLine], output: Path) -> None:
    """Write reconstructed code, preserving uncertainty markers."""
    lines: list[str] = []
    for item in merged:
        if item.uncertain:
            lines.append(_uncertain_marker(item.read))
        lines.append(item.read.content)
    body = "\n".join(lines)
    _write_text_file(output / "codigo_extraido.txt", f"{body}\n" if body else "")


def write_outputs(
    metadata: VideoMetadata,
    parameters: ExtractionParameters,
    rows: list[OCRRow],
    merged: list[MergedLine],
    report: FailureReport,
    output: Path,
) -> None:
    """Write the run's JSON, CSV, code, and Markdown report artifacts.

    `codigo_extraido.txt` is the reconstructed code — merged by line number
    when numbers were detected, otherwise time-ordered with scroll duplicates
    consolidated — each uncertain line preceded by its `[OCR_UNCERTAIN]`
    marker. Frame images are produced by `run_ocr()` inside the run-scoped
    directory prepared by `prepare_output_tree()`.
    """
    write_metadata(metadata, output)
    write_extraction_parameters(parameters, output)
    write_ocr_raw(rows, output)
    write_extracted_code(merged, output)
    write_failure_report(report, output)


# --- CLI -------------------------------------------------------------------


@app.command()
def main(
    video: Annotated[
        Path,
        typer.Option(help="Path to the input video file."),
    ],
    output: Annotated[
        Path,
        typer.Option(help="Path to the output directory."),
    ],
    crop_left: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the left edge before OCR."),
    ] = None,
    crop_top: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the top edge before OCR."),
    ] = None,
    crop_right: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the right edge before OCR."),
    ] = None,
    crop_bottom: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the bottom edge before OCR."),
    ] = None,
    start_time: Annotated[
        str | None,
        typer.Option(
            "--start-time",
            help=f"Start timestamp for extraction; accepted forms: {TIMESTAMP_FORMAT_HELP}.",
        ),
    ] = None,
    end_time: Annotated[
        str | None,
        typer.Option(
            "--end-time",
            help=f"End timestamp for extraction; accepted forms: {TIMESTAMP_FORMAT_HELP}.",
        ),
    ] = None,
) -> None:
    """Extract the source code shown in a screen-recording video."""
    if not video.exists():
        _fail(f"video not found: [cyan]{video}[/cyan]")
    if not video.is_file():
        _fail(f"video path is not a file: [cyan]{video}[/cyan]")

    try:
        crop = CropBox(
            left=crop_left or 0,
            top=crop_top or 0,
            right=crop_right or 0,
            bottom=crop_bottom or 0,
        )
    except ValidationError:
        _fail("crop values must be non-negative integers.")

    frames_dir = prepare_output_tree(output)

    metadata = get_video_metadata(video)
    console.print(
        f"[green]Video:[/green] {metadata.width}x{metadata.height} @ "
        f"{metadata.fps:g} fps, {metadata.duration_seconds:g}s, "
        f"{metadata.total_frames} frames "
        f"(codec: {metadata.codec or 'unknown'}, source: {metadata.source})"
    )
    crop.validate_against(metadata.width, metadata.height)

    step = adaptive_sample_step(metadata.fps)
    parameters = resolve_extraction_parameters(
        crop=crop,
        metadata=metadata,
        start_time=start_time,
        end_time=end_time,
        step=step,
    )
    segment_end = parameters.effective_end_time or "video_end_unknown"
    metadata.sampling_strategy = (
        f"adaptive_fps={_nearest_fps_tier(metadata.fps)},step={step},"
        f"segment={parameters.effective_start_time}-{segment_end}"
    )
    console.print(
        f"[green]Sampling:[/green] {metadata.sampling_strategy} "
        f"(~{parameters.expected_candidate_frames} candidate frames)"
    )
    console.print(
        f"[green]Segment:[/green] frames "
        f"{parameters.first_candidate_frame if parameters.first_candidate_frame is not None else 'none'}"
        f"→{parameters.last_candidate_frame if parameters.last_candidate_frame is not None else 'none'} "
        f"on the original video timeline"
    )
    write_metadata(metadata, output)
    write_extraction_parameters(parameters, output)

    if parameters.expected_candidate_frames == 0:
        stats = SelectionStats()
        report = FailureReport(
            video_path=str(video),
            metadata=metadata,
            stats=stats,
            lines_extracted=0,
            line_numbers_detected=False,
        )
        write_outputs(metadata, parameters, [], [], report, output)
        _fail(
            "the selected segment contains no frame timestamps to sample. "
            "Choose a wider interval or align the segment to visible video frames."
        )

    try:
        engine: OCREngine = TesseractEngine()
    except OCREngineUnavailableError as exc:
        _fail(str(exc))

    frames = sample_frames(video, metadata, parameters)
    rows, stats, outcomes = run_ocr(
        frames,
        engine,
        frames_dir,
        parameters.expected_candidate_frames,
        crop,
    )
    console.print(
        f"[green]Selection:[/green] {stats.frames_sampled} frames sampled, "
        f"{stats.frames_kept} kept, {stats.frames_discarded_blurry} discarded "
        f"as blurry, {stats.frames_discarded_duplicate} as near-duplicate"
    )
    if not rows:
        report = FailureReport(
            video_path=str(video),
            metadata=metadata,
            stats=stats,
            lines_extracted=0,
            line_numbers_detected=False,
            unextractable=unextractable_sections(outcomes),
        )
        write_outputs(metadata, parameters, rows, [], report, output)
        _fail(
            "every sampled frame was discarded by selection "
            f"({stats.frames_discarded_blurry} blurry, "
            f"{stats.frames_discarded_duplicate} near-duplicate) — nothing "
            "to OCR. Inspect ocr_raw.csv, codigo_extraido.txt, and "
            "relatorio_falhas.md, then check the crop region and video quality."
        )
    reads = parse_code_lines(rows)
    if not reads:
        report = FailureReport(
            video_path=str(video),
            metadata=metadata,
            stats=stats,
            lines_extracted=0,
            line_numbers_detected=False,
            unextractable=unextractable_sections(outcomes),
        )
        write_outputs(metadata, parameters, rows, [], report, output)
        _fail(
            f"OCR ran on {len(rows)} frame(s) but recognized no text in any "
            "of them. Inspect "
            f"[cyan]{output / 'ocr_raw.csv'}[/cyan], "
            f"[cyan]{output / 'codigo_extraido.txt'}[/cyan], "
            f"[cyan]{output / 'relatorio_falhas.md'}[/cyan], and the frames "
            f"in [cyan]{frames_dir}[/cyan]. "
            "Check that the crop region contains the code, and consider a "
            "larger editor font, a higher recording resolution, or a "
            "high-contrast editor theme."
        )
    numbered = has_line_numbers(reads)
    if numbered:
        merged = merge_ocr_results(reads)
        path_taken = "line numbers detected — merged by line number"
    else:
        reads = parse_code_lines(rows, strip_line_numbers=False)
        merged = reconstruct_by_time(reads)
        path_taken = "no line numbers detected — reconstructed by video time"
    uncertain = sum(1 for item in merged if item.uncertain)
    console.print(
        f"[green]Reconstruction:[/green] {path_taken}: "
        f"{len(merged)} lines from {len(reads)} reads "
        f"({uncertain} marked [OCR_UNCERTAIN])"
    )

    missing = detect_missing_lines(merged)
    report = FailureReport(
        video_path=str(video),
        metadata=metadata,
        stats=stats,
        lines_extracted=len(merged),
        line_numbers_detected=numbered,
        missing_lines=missing,
        uncertain_lines=[item for item in merged if item.uncertain],
        unextractable=unextractable_sections(outcomes),
    )
    write_outputs(metadata, parameters, rows, merged, report, output)

    console.print(
        f"[green]Report:[/green] {len(missing)} missing lines, "
        f"{uncertain} uncertain, {len(report.unextractable)} unextractable "
        f"spans → [cyan]{output / 'relatorio_falhas.md'}[/cyan]"
    )
    non_empty = sum(1 for row in rows if row.text)
    console.print(
        f"[green]Done:[/green] {len(rows)} frames OCR'd ({non_empty} with "
        f"text). Outputs in [cyan]{output}[/cyan]: codigo_extraido.txt, "
        "relatorio_falhas.md, ocr_raw.csv, metadata_video.json, "
        "extraction_parameters.json, frames_usados/"
    )


if __name__ == "__main__":
    app()
