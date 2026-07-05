"""Extract the source code shown in a screen-recording video via local OCR.

Phase 3: metadata (ffprobe with OpenCV fallback) → FPS-adaptive frame sampling
→ preprocessing (crop → grayscale → upscale → Otsu threshold → denoise) → blur
and near-duplicate skipping → OCR on the preprocessed frames → line-number
parsing and merge of repeated reads (best by frequency / confidence /
sharpness, `[OCR_UNCERTAIN]` markers on low-confidence lines) → outputs
(`metadata_video.json`, `ocr_raw.csv`, `codigo_extraido.txt`,
`frames_usados/`). Time-based reconstruction without line numbers and the
failure report arrive in later phases.
"""

import json
import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Iterator
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal, NoReturn, Protocol

import cv2
import pandas as pd
import pytesseract  # type: ignore[import-untyped]
import typer
from cv2.typing import MatLike
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.progress import track
from skimage.metrics import structural_similarity

SAMPLE_STEP_BY_FPS_TIER = {30: 15, 60: 30, 120: 60}
"""Sampling step per FPS tier — roughly one candidate frame every 0.5 s."""

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

LINE_NUMBER_RE = re.compile(r"^\s*(?P<number>\d{1,5})[:.|]?(?: (?P<content>.*))?$")
"""Leading editor line number: bounded digits, optional separator, then content."""

MIN_NUMBERED_SHARE = 0.6
"""Numbered reconstruction runs when at least this share of reads has a number."""

MIN_INCREASING_SHARE = 0.8
"""...and detected numbers are increasing within a frame at least this often."""

OCR_UNCERTAIN_CONFIDENCE = 60.0
"""Merged lines whose best read is below this get an `[OCR_UNCERTAIN]` marker."""

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


# --- Data models ---------------------------------------------------------


class VideoMetadata(BaseModel):
    """Metadata of the input video plus the sampling strategy of the run."""

    fps: float
    duration_seconds: float
    width: int
    height: int
    total_frames: int
    codec: str | None = None
    source: Literal["ffprobe", "opencv"]
    sampling_strategy: str = ""
    """Set by `main()` once the adaptive step is chosen from the detected FPS."""


class OCRLine(BaseModel):
    """One text line within an OCR engine read, with its own confidence."""

    text: str
    confidence: float | None = None


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
    """The best read chosen for one line number by `merge_ocr_results()`."""

    read: LineRead
    uncertain: bool = False


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
        _warn("ffprobe is not installed; falling back to OpenCV for metadata.")
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
    width = stream.get("width")
    height = stream.get("height")
    try:
        duration = float(
            stream.get("duration") or payload.get("format", {}).get("duration") or 0
        )
    except ValueError:
        duration = 0.0
    if not fps or not width or not height or duration <= 0:
        _warn("ffprobe metadata is incomplete; falling back to OpenCV.")
        return None

    nb_frames = str(stream.get("nb_frames", ""))
    total_frames = int(nb_frames) if nb_frames.isdigit() else round(duration * fps)
    return VideoMetadata(
        fps=fps,
        duration_seconds=round(duration, 3),
        width=int(width),
        height=int(height),
        total_frames=total_frames,
        codec=stream.get("codec_name"),
        source="ffprobe",
    )


def _metadata_from_opencv(video: Path) -> VideoMetadata:
    """Read FPS / frame count / resolution via OpenCV (codec best-effort)."""
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
    return VideoMetadata(
        fps=fps,
        duration_seconds=round(total_frames / fps, 3),
        width=width,
        height=height,
        total_frames=total_frames,
        codec=codec,
        source="opencv",
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


class SelectionStats(BaseModel):
    """Counts of sampled frames discarded before OCR (feeds the Phase 5 report)."""

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
    return cv2.cvtColor(apply_crop(image, crop), cv2.COLOR_BGR2GRAY)


def preprocess_frame(image: MatLike, crop: CropBox) -> MatLike:
    """Prepare a frame for OCR: crop → grayscale → upscale → threshold → denoise."""
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
    return float(cv2.Laplacian(gray_image, cv2.CV_64F).var())


def is_frame_blurry(sharpness: float) -> bool:
    """Sharpness gate: True when the score is below ``BLUR_THRESHOLD``."""
    return sharpness < BLUR_THRESHOLD


def _ssim_thumbnail(gray_image: MatLike) -> MatLike:
    """Shrink a grayscale frame for fast SSIM (min 7 px, skimage's window size)."""
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


class TesseractEngine:
    """`OCREngine` implementation backed by pytesseract / Tesseract.

    The rest of the pipeline must depend only on :class:`OCREngine`;
    pytesseract is referenced exclusively inside this class.
    """

    def __init__(self) -> None:
        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError as exc:
            raise OCREngineUnavailableError(
                "the tesseract binary is not installed. Install it with "
                "[bold]brew install tesseract[/bold] (macOS) or your system "
                "package manager, then re-run."
            ) from exc

    def recognize(self, image: MatLike) -> OCRResult:
        """OCR the whole image; per-line reads with mean word confidence each."""
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words_by_line: dict[tuple[int, int, int], list[str]] = {}
        confs_by_line: dict[tuple[int, int, int], list[float]] = {}
        words = zip(
            data["text"],
            data["conf"],
            data["block_num"],
            data["par_num"],
            data["line_num"],
            strict=True,
        )
        for word, conf, block, paragraph, line in words:
            if not word.strip():
                continue
            key = (block, paragraph, line)
            words_by_line.setdefault(key, []).append(word)
            confidence = float(conf)
            if confidence >= 0:
                confs_by_line.setdefault(key, []).append(confidence)

        lines: list[OCRLine] = []
        for key, parts in words_by_line.items():
            confs = confs_by_line.get(key, [])
            lines.append(
                OCRLine(
                    text=" ".join(parts),
                    confidence=round(sum(confs) / len(confs), 2) if confs else None,
                )
            )
        all_confs = [c for confs in confs_by_line.values() for c in confs]
        mean_confidence = (
            round(sum(all_confs) / len(all_confs), 2) if all_confs else None
        )
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
    video: Path, fps: float, step: int
) -> Iterator[tuple[int, float, MatLike]]:
    """Yield ``(frame_number, time_seconds, image)`` every ``step`` frames."""
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            _fail(f"cannot open video for decoding: [cyan]{video}[/cyan]")
        frame_number = 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            if frame_number % step == 0:
                yield frame_number, frame_number / fps, image
            frame_number += 1
        if frame_number == 0:
            _fail(
                f"video [cyan]{video}[/cyan] opened but zero frames could be "
                "decoded; it may be corrupt or in an unsupported format."
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
) -> tuple[list[OCRRow], SelectionStats]:
    """OCR the sampled frames that survive selection.

    Per candidate: crop + grayscale → blur gate → SSIM near-duplicate gate
    against the last accepted frame → full preprocessing → save the
    preprocessed image (what OCR actually sees) to `frames_usados/` → OCR.
    An empty OCR read is recorded as a row with empty text, not an error.
    """
    rows: list[OCRRow] = []
    stats = SelectionStats()
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
            continue
        thumbnail = _ssim_thumbnail(gray)
        if last_accepted_thumbnail is not None:
            score = structural_similarity(
                thumbnail, last_accepted_thumbnail, data_range=255
            )
            if score > SSIM_THRESHOLD:
                stats.frames_discarded_duplicate += 1
                continue
        last_accepted_thumbnail = thumbnail

        processed = preprocess_frame(image, crop)
        frame_path = frames_dir / f"frame_{frame_number}.png"
        if not cv2.imwrite(str(frame_path), processed):
            _fail(f"could not save frame image: [cyan]{frame_path}[/cyan]")
        result = engine.recognize(processed)
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
    return rows, stats


# --- Reconstruction --------------------------------------------------------


def parse_code_lines(rows: list[OCRRow]) -> list[LineRead]:
    """Split each frame read into per-line reads, extracting leading line numbers.

    A read that matches ``LINE_NUMBER_RE`` has its number and separator
    stripped, keeping the content's own indentation; anything else keeps its
    full text with ``line_number=None``. Fully blank reads are dropped.
    """
    reads: list[LineRead] = []
    for row in rows:
        for line in row.lines:
            if not line.text.strip():
                continue
            match = LINE_NUMBER_RE.match(line.text)
            if match:
                line_number = int(match.group("number"))
                content = match.group("content") or ""
            else:
                line_number = None
                content = line.text
            reads.append(
                LineRead(
                    line_number=line_number,
                    content=content,
                    frame_number=row.frame_number,
                    time_seconds=row.time_seconds,
                    time_formatted=row.time_formatted,
                    confidence=line.confidence,
                    sharpness=row.sharpness,
                )
            )
    return reads


def has_line_numbers(reads: list[LineRead]) -> bool:
    """Decide whether the video shows editor line numbers.

    True when most reads carry a leading number (``MIN_NUMBERED_SHARE``) and
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


def merge_ocr_results(reads: list[LineRead]) -> list[MergedLine]:
    """Consolidate repeated reads of each numbered line into one best read.

    Per line number: the most frequent content wins (whitespace-normalized
    for counting), ties broken by confidence then frame sharpness. The
    winning read's content is emitted verbatim — reads are never blended.
    Below ``OCR_UNCERTAIN_CONFIDENCE`` (or with no confidence at all) the
    line is flagged uncertain. Gaps in numbering are left as gaps.
    """
    by_number: dict[int, list[LineRead]] = {}
    for read in reads:
        if read.line_number is not None:
            by_number.setdefault(read.line_number, []).append(read)

    merged: list[MergedLine] = []
    for line_number in sorted(by_number):
        group = by_number[line_number]
        frequency = Counter(" ".join(read.content.split()) for read in group)
        top_count = max(frequency.values())
        finalists = [
            read
            for read in group
            if frequency[" ".join(read.content.split())] == top_count
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
        merged.append(MergedLine(read=winner, uncertain=uncertain))
    return merged


# --- Outputs ---------------------------------------------------------------


def _uncertain_marker(read: LineRead) -> str:
    """The exact `[OCR_UNCERTAIN]` comment mandated by the mission spec."""
    return (
        f"# [OCR_UNCERTAIN] frame={read.frame_number} "
        f'time={read.time_formatted} texto_original="{read.content}"'
    )


def write_outputs(
    metadata: VideoMetadata,
    rows: list[OCRRow],
    merged: list[MergedLine] | None,
    output: Path,
) -> None:
    """Write `metadata_video.json`, `ocr_raw.csv`, and `codigo_extraido.txt`.

    With ``merged`` (line numbers detected), `codigo_extraido.txt` is the
    consolidated code in line-number order, each uncertain line preceded by
    its `[OCR_UNCERTAIN]` marker. Without it, the naive time-ordered
    concatenation is kept (time-based reconstruction is Phase 4).
    """
    metadata_path = output / "metadata_video.json"
    metadata_path.write_text(metadata.model_dump_json(indent=2) + "\n", "utf-8")

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
    frame.to_csv(output / "ocr_raw.csv", index=False)

    if merged is not None:
        lines: list[str] = []
        for item in merged:
            if item.uncertain:
                lines.append(_uncertain_marker(item.read))
            lines.append(item.read.content)
        code = "\n".join(lines)
    else:
        # Naive concatenation in video-time order — no merging or synthesis.
        code = "\n\n".join(row.text for row in ordered)
    (output / "codigo_extraido.txt").write_text(code + "\n", "utf-8")


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

    frames_dir = output / "frames_usados"
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"cannot create output directory [cyan]{output}[/cyan]: {exc}")

    probe = output / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        _fail(f"output directory [cyan]{output}[/cyan] is not writable: {exc}")

    try:
        engine: OCREngine = TesseractEngine()
    except OCREngineUnavailableError as exc:
        _fail(str(exc))

    metadata = get_video_metadata(video)
    console.print(
        f"[green]Video:[/green] {metadata.width}x{metadata.height} @ "
        f"{metadata.fps:g} fps, {metadata.duration_seconds:g}s, "
        f"{metadata.total_frames} frames "
        f"(codec: {metadata.codec or 'unknown'}, source: {metadata.source})"
    )
    crop.validate_against(metadata.width, metadata.height)

    step = adaptive_sample_step(metadata.fps)
    metadata.sampling_strategy = (
        f"adaptive_fps={_nearest_fps_tier(metadata.fps)},step={step}"
    )
    console.print(f"[green]Sampling:[/green] {metadata.sampling_strategy}")

    expected_samples = -(-metadata.total_frames // step)
    frames = sample_frames(video, metadata.fps, step)
    rows, stats = run_ocr(frames, engine, frames_dir, expected_samples, crop)
    if not rows:
        _fail(
            "every sampled frame was discarded by selection "
            f"({stats.frames_discarded_blurry} blurry, "
            f"{stats.frames_discarded_duplicate} near-duplicate) — nothing "
            "to OCR. Check the crop region and the video quality."
        )
    reads = parse_code_lines(rows)
    merged: list[MergedLine] | None = None
    if has_line_numbers(reads):
        merged = merge_ocr_results(reads)
        uncertain = sum(1 for item in merged if item.uncertain)
        console.print(
            f"[green]Reconstruction:[/green] line numbers detected — "
            f"{len(merged)} lines merged from {len(reads)} reads "
            f"({uncertain} marked [OCR_UNCERTAIN])"
        )
    else:
        console.print(
            "[green]Reconstruction:[/green] no line numbers detected — "
            "keeping naive time-ordered concatenation"
        )
    write_outputs(metadata, rows, merged, output)

    console.print(
        f"[green]Selection:[/green] {stats.frames_sampled} frames sampled, "
        f"{stats.frames_kept} kept, {stats.frames_discarded_blurry} discarded "
        f"as blurry, {stats.frames_discarded_duplicate} as near-duplicate"
    )
    non_empty = sum(1 for row in rows if row.text)
    console.print(
        f"[green]Done:[/green] {len(rows)} frames OCR'd "
        f"({non_empty} with text) → [cyan]{output}[/cyan]"
    )


if __name__ == "__main__":
    app()
