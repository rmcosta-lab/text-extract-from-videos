"""Models for local video OCR."""

import re
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    NoReturn,
    Protocol,
)

import typer
from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console

if TYPE_CHECKING:
    from cv2.typing import MatLike
else:
    type MatLike = object


SAMPLE_STEP_BY_FPS_TIER = {30: 15, 60: 30, 120: 60}
"""Sampling step per FPS tier — roughly one candidate frame every 0.5 s."""


LOW_FPS_THRESHOLD = 24.0
"""Below this FPS the tiers are too coarse (they would sample far apart), so the
step is computed directly from the rate instead of snapped to a tier."""


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
"""Tesseract-calibrated confidence floor for the `[OCR_UNCERTAIN]` marker."""


OCR_UNCERTAIN_CONFIDENCE_PADDLE = 95.0
"""PaddleOCR floor — its scores saturate above ~95 even for garbled reads, so
this catches only genuinely weak reads; saturated garbage is caught by the
read-agreement gate instead."""


MIN_AGREEMENT_SHARE = 0.5
"""A merged line is uncertain when fewer than this share of its reads
fuzzy-match the winning content — an engine-independent disagreement signal."""


MIN_READS_FOR_AGREEMENT = 3
"""The agreement gate only fires with at least this many reads of a line."""


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


def fail(message: str) -> NoReturn:
    """Print a styled error message and exit with status 1."""
    err_console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=1)


def _warn(message: str) -> None:
    """Print a styled warning message to stderr."""
    err_console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def require_cv2() -> Any:
    """Import OpenCV only when video/image processing actually needs it."""
    try:
        import cv2  # noqa: PLC0415
    except ImportError:
        fail(
            "OpenCV is required to read video frames and preprocess images. "
            "Install it with [bold]uv sync[/bold], "
            "then re-run."
        )
    return cv2


def _require_pandas() -> Any:
    """Import pandas only when writing `ocr_raw.csv`."""
    try:
        import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        fail(
            "pandas is required to write ocr_raw.csv. Install it with "
            "[bold]uv sync[/bold], then re-run."
        )
    return pd


def _require_structural_similarity() -> Any:
    """Import scikit-image SSIM only when duplicate-frame detection runs."""
    try:
        from skimage.metrics import (  # type: ignore[import-untyped]  # noqa: PLC0415
            structural_similarity,
        )
    except ImportError:
        fail(
            "scikit-image is required for near-duplicate frame detection. "
            "Install it with [bold]uv sync[/bold], "
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
    """Filled by `main()` (via `model_copy`) once the adaptive step is chosen."""


class InvalidVideoMetadataError(RuntimeError):
    """Raised when probed video metadata violates required invariants."""


class InvalidExtractionParameterError(RuntimeError):
    """Raised when segment/crop parameters are invalid for the video.

    Library seams raise this typed error; `main()` translates it into a CLI
    exit at the boundary, and `suggest_crop.py` reuses the message verbatim
    for its web/JSON errors.
    """


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
    """Whether one sampled frame's content was captured — feeds the failure report."""

    frame_number: int
    time_seconds: float
    time_formatted: str
    usable: bool
    """True when the frame's on-screen content was captured: either OCR here
    returned non-blank text, or the frame was a near-duplicate of the accepted
    neighbor that already carries the same content."""


class CropBox(BaseModel):
    """Pixels to trim from each edge before any other processing."""

    left: int = Field(default=0, ge=0)
    top: int = Field(default=0, ge=0)
    right: int = Field(default=0, ge=0)
    bottom: int = Field(default=0, ge=0)

    def validate_against(self, width: int, height: int) -> None:
        """Raise clearly if the crop leaves no image area at this resolution."""
        if self.left + self.right >= width:
            raise InvalidExtractionParameterError(
                f"crop leaves no image area: left ({self.left}) + right "
                f"({self.right}) >= video width ({width})."
            )
        if self.top + self.bottom >= height:
            raise InvalidExtractionParameterError(
                f"crop leaves no image area: top ({self.top}) + bottom "
                f"({self.bottom}) >= video height ({height})."
            )


class EngineName(StrEnum):
    """OCR engines selectable via ``--engine``."""

    tesseract = "tesseract"
    paddle = "paddle"
    paddle_vl = "paddle-vl"


class OutputExtension(StrEnum):
    txt = "txt"
    md = "md"
    py = "py"


class PreprocessProfile(StrEnum):
    legacy = "legacy"
    native = "native"
    bounded = "bounded"


class PreprocessConfig(BaseModel):
    """Explicit image treatment; legacy preserves the established default."""

    profile: PreprocessProfile = PreprocessProfile.legacy
    scale: float = Field(default=1.0, gt=0, le=4)
    max_side: int = Field(default=4000, ge=32)


def validate_output_name(value: str) -> str:
    """Require one portable directory/file stem, never a relative path."""
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or value != value.strip()
        or value.endswith(".")
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        or value.split(".", maxsplit=1)[0].upper() in reserved
        or value == "relatorio_falhas"
    ):
        raise ValueError("output-name must be a valid single folder/file name")
    return value


class ExtractionParameters(BaseModel):
    """User-requested and effective extraction controls for one run."""

    engine: EngineName = EngineName.tesseract
    output_extension: OutputExtension = OutputExtension.txt
    output_name: str = "codigo_extraido"

    @field_validator("output_name")
    @classmethod
    def valid_output_name(cls, value: str) -> str:
        return validate_output_name(value)

    prepare_review: bool = False
    blur_retry_seconds: float = Field(default=0.25, ge=0, le=1)
    stability_window_seconds: float = Field(default=0.5, ge=0, le=2)
    preprocessing: PreprocessConfig = Field(default_factory=PreprocessConfig)
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


class CandidateFrameWindow(NamedTuple):
    """Frame bounds and candidate counts for the effective segment."""

    start_frame: int
    end_frame_exclusive: int
    expected: int
    first: int | None
    last: int | None


class SelectionStats(BaseModel):
    """Counts of sampled frames discarded before OCR (feeds the failure report)."""

    frames_sampled: int = 0
    frames_discarded_blurry: int = 0
    frames_recovered_blurry: int = 0
    frames_discarded_unstable: int = 0
    frames_replaced_stability: int = 0
    frames_skipped_after_replacement: int = 0
    frames_discarded_duplicate: int = 0

    @property
    def frames_kept(self) -> int:
        return (
            self.frames_sampled
            - self.frames_discarded_blurry
            - self.frames_discarded_duplicate
            - self.frames_discarded_unstable
            - self.frames_skipped_after_replacement
        )


class OCREngineUnavailableError(RuntimeError):
    """Raised when an OCR engine's backing binary is not installed."""


class OCREngine(Protocol):
    """Narrow OCR seam: one image in, one :class:`OCRResult` out."""

    def recognize(self, image: MatLike) -> OCRResult: ...


def _format_time(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm``."""
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    s = total_ms // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}.{ms:03d}"


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
    reads_without_line_number: int = 0
    """Reads excluded from the numbered reconstruction because no line number
    was detected for them — their raw text survives in `ocr_raw.csv`."""
    missing_lines: list[MissingLine] = Field(default_factory=list)
    uncertain_lines: list[MergedLine] = Field(default_factory=list)
    unextractable: list[TimeSpan] = Field(default_factory=list)


CAPTURE_RECOMMENDATIONS = [
    "Grave em resolução maior (1080p ou superior).",
    "Reduza a velocidade do scroll durante a gravação.",
    "Aumente a fonte do editor de código.",
    "Use um tema de alto contraste no editor.",
]
"""Static capture recommendations mandated by the README, always included."""


BLURRY_SHARE_WARNING = 0.3
"""Above this share of blurry discards, the report reinforces slower scrolling."""


MISSING_RUN_COLLAPSE_MIN = 4
"""A contiguous run of this many absent line numbers is rendered as one range
entry instead of one line each, so a single gutter misread cannot flood the
report; shorter runs stay itemized because each line is still worth naming."""


RUN_ARTIFACT_FILENAMES = (
    "codigo_extraido.txt",
    "relatorio_falhas.md",
    "ocr_raw.csv",
    "metadata_video.json",
    "extraction_parameters.json",
    "review_manifest.json",
)
"""Run-scoped output files cleared up front so failed runs cannot leave a
previous run's artifacts mixed with this run's fresh outputs."""
