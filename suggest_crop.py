"""Suggest crop parameters for a video and preview them in a local web page.

Sample several frames spread across the video's duration, OCR each with the
selected engine (Tesseract default, PaddleOCR optional), and combine the
per-frame text geometry into one crop box that isolates the line-number
gutter plus the code text in **every** sampled frame — code scrolls and line
numbers grow wider over time, so a single frame is not representative. A
small FastAPI server (bound to 127.0.0.1) serves a single static page showing
a representative frame before and after the crop; editing the values re-crops
the cached frame on the backend and refreshes the preview. The confirmed
values are meant to be copied into `extract_code_from_video.py --crop-*` —
this tool never runs a full extraction and never applies a crop silently.
Frames with empty OCR contribute nothing; if no sampled frame yields text the
suggestion is a zero crop with an explicit "no text detected" notice, never a
fabricated region. All video/metadata/preprocessing/engine logic is imported
from `extract_code_from_video.py`, not re-implemented.
"""

import base64
import re
import threading
import webbrowser
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Annotated, TypeAlias

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from extract_code_from_video import (
    LINE_NUMBER_WORD_RE,
    UPSCALE_FACTOR,
    CropBox,
    EngineName,
    OCREngine,
    OCREngineUnavailableError,
    OCRLine,
    OCRResult,
    _fail,
    _require_cv2,
    create_ocr_engine,
    get_video_metadata,
    preprocess_frame,
)

if TYPE_CHECKING:
    from cv2.typing import MatLike
else:
    MatLike: TypeAlias = object

REFERENCE_FRAME_INDEX = 30
"""First sampled frame and preview reference (falls back to the last frame)."""

DEFAULT_SAMPLE_COUNT = 12
"""Frames sampled across the video's duration for the combined suggestion."""

CROP_MARGIN_FACTOR = 1.0
"""Margin around the detected text block, as a fraction of the median line height."""

MIN_CROP_MARGIN_PX = 8
"""Lower bound for the margin so tight text blocks still get breathing room."""

LINE_GAP_FACTOR = 3.0
"""Lines further apart than this × median line height start a new cluster."""

MIN_GUTTER_WORDS = 5
"""Aligned line-number tokens needed to anchor the crop on the editor gutter."""

SEGMENT_GAP_FRACTION = 0.05
"""Horizontal gaps wider than this × frame width split words into segments."""

MIN_SEGMENT_CONFIDENCE = 50.0
"""Right-side segments below this mean confidence are treated as UI noise
(minimap, scrollbar) and excluded from the suggested crop."""

RICH_MARKUP_RE = re.compile(r"\[/?[a-z ]+\]")
"""Rich console tags stripped from reused error messages before web display."""

cli = typer.Typer(add_completion=False)


class ReferenceFrameError(RuntimeError):
    """Raised when the reference frame cannot be decoded from the video."""


class TextBox(BaseModel):
    """One OCR line bounding box in original-frame pixel coordinates."""

    left: float = Field(ge=0)
    top: float = Field(ge=0)
    right: float = Field(gt=0)
    bottom: float = Field(gt=0)


class WordBox(BaseModel):
    """One OCR word bounding box in original-frame pixel coordinates."""

    text: str
    confidence: float | None = None
    left: float = Field(ge=0)
    top: float = Field(ge=0)
    right: float = Field(gt=0)
    bottom: float = Field(gt=0)


class TextGeometry(BaseModel):
    """Geometry of the text detected in one frame, in original-frame pixels."""

    left: float
    """Left edge of the line-number gutter (or of the kept text)."""
    top: float
    bottom: float
    text_right: float
    """Right edge of the kept (non-noise) text."""
    noise_left: float | None = None
    """Left edge of the low-confidence noise column (minimap), when detected."""
    line_height: float
    """Median height of the kept words, used to derive the crop margin."""
    gutter_anchored: bool = False
    """Whether the band was anchored on a detected line-number gutter (the
    cluster fallback can sweep in menu/status chrome, so it ranks lower)."""


class FrameObservation(BaseModel):
    """One sampled frame's OCR outcome: its text geometry, or none at all."""

    frame_index: int
    text: TextGeometry | None = None


class CropSuggestion(BaseModel):
    """Combined crop suggestion, with an honesty flag and sampling info."""

    crop: CropBox
    text_detected: bool
    analyzed_frame_indices: list[int] = []
    text_frame_indices: list[int] = []
    """Frames whose detected text informed the combined crop."""
    skipped_frame_indices: list[int] = []
    """Sampled indices that could not be decoded from the video."""


class ReferenceFrame(BaseModel):
    """One decoded frame plus which index was actually used."""

    model_config = {"arbitrary_types_allowed": True}

    image: MatLike
    frame_index: int
    width: int
    height: int


class SampledFrames(BaseModel):
    """The decoded sample frames; the first one doubles as the preview frame."""

    frames: list[ReferenceFrame] = Field(min_length=1)
    failed_indices: list[int] = []


class PreviewResponse(BaseModel):
    """`GET /api/preview` payload: suggestion plus both preview images."""

    video_name: str
    engine: EngineName
    frame_index: int
    frame_width: int
    frame_height: int
    text_detected: bool
    analyzed_frame_indices: list[int]
    text_frame_indices: list[int]
    skipped_frame_indices: list[int]
    crop: CropBox
    cli_flags: str
    original_png_base64: str
    cropped_png_base64: str


class CropRequest(BaseModel):
    """`POST /api/crop` body: user-edited crop values to preview."""

    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(ge=0)
    bottom: int = Field(ge=0)


class CropResponse(BaseModel):
    """`POST /api/crop` payload: the re-cropped preview image."""

    crop: CropBox
    cli_flags: str
    cropped_width: int
    cropped_height: int
    cropped_png_base64: str


def _plain(message: str) -> str:
    """Strip rich markup from reused CLI error messages for web/JSON output."""
    return RICH_MARKUP_RE.sub("", message)


def sample_frame_indices(total_frames: int, count: int) -> list[int]:
    """Evenly spaced indices from the reference frame to the end of the video."""
    last = max(0, total_frames - 1)
    first = min(REFERENCE_FRAME_INDEX, last)
    if count <= 1 or first == last:
        return [first]
    step = (last - first) / (count - 1)
    return sorted({round(first + step * position) for position in range(count)})


def read_sampled_frames(
    video: Path, count: int = DEFAULT_SAMPLE_COUNT
) -> SampledFrames:
    """Decode the sampled frames in one capture session.

    Frames that fail to decode are recorded in ``failed_indices`` and skipped;
    only a video where *no* sampled frame decodes is an error.
    """
    cv2 = _require_cv2()
    metadata = get_video_metadata(video)
    indices = sample_frame_indices(metadata.total_frames, count)
    capture = cv2.VideoCapture(str(video))
    frames: list[ReferenceFrame] = []
    failed: list[int] = []
    try:
        if not capture.isOpened():
            raise ReferenceFrameError(f"cannot open video for decoding: {video}")
        for frame_index in indices:
            if frame_index:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, image = capture.read()
            if not ok:
                failed.append(frame_index)
                continue
            height, width = image.shape[:2]
            frames.append(
                ReferenceFrame(
                    image=image, frame_index=frame_index, width=width, height=height
                )
            )
    finally:
        capture.release()
    if not frames:
        raise ReferenceFrameError(
            f"could not decode any sampled frame ({indices}) of {video}; the "
            "video may be corrupt, truncated, or in an unsupported format."
        )
    return SampledFrames(frames=frames, failed_indices=failed)


def _line_boxes(lines: list[OCRLine]) -> list[TextBox]:
    """Collect per-line text boxes, mapped back to original-frame pixels."""
    boxes: list[TextBox] = []
    for line in lines:
        if line.words:
            left = min(word.left for word in line.words)
            top = min(word.top for word in line.words)
            right = max(word.left + word.width for word in line.words)
            bottom = max(word.top + word.height for word in line.words)
        elif None not in (line.left, line.top, line.width, line.height):
            assert line.left is not None and line.top is not None
            assert line.width is not None and line.height is not None
            left, top = line.left, line.top
            right, bottom = line.left + line.width, line.top + line.height
        else:
            continue
        if right <= left or bottom <= top or not line.text.strip():
            continue
        boxes.append(
            TextBox(
                left=left / UPSCALE_FACTOR,
                top=top / UPSCALE_FACTOR,
                right=right / UPSCALE_FACTOR,
                bottom=bottom / UPSCALE_FACTOR,
            )
        )
    return boxes


def _main_text_cluster(boxes: list[TextBox]) -> list[TextBox]:
    """Keep the largest vertical run of lines; drop isolated outliers (UI chrome)."""
    ordered = sorted(boxes, key=lambda box: box.top)
    median_height = max(1.0, median(box.bottom - box.top for box in ordered))
    max_gap = median_height * LINE_GAP_FACTOR

    clusters: list[list[TextBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        if box.top - clusters[-1][-1].top > max_gap:
            clusters.append([box])
        else:
            clusters[-1].append(box)
    return max(clusters, key=len)


def _word_boxes(lines: list[OCRLine]) -> list[WordBox]:
    """Collect word boxes mapped to original-frame pixels (lines as fallback)."""
    boxes: list[WordBox] = []
    for line in lines:
        if line.words:
            for word in line.words:
                if word.width <= 0 or word.height <= 0 or not word.text.strip():
                    continue
                boxes.append(
                    WordBox(
                        text=word.text,
                        confidence=word.confidence,
                        left=word.left / UPSCALE_FACTOR,
                        top=word.top / UPSCALE_FACTOR,
                        right=(word.left + word.width) / UPSCALE_FACTOR,
                        bottom=(word.top + word.height) / UPSCALE_FACTOR,
                    )
                )
        elif (
            line.left is not None
            and line.top is not None
            and line.width is not None
            and line.height is not None
            and line.width > 0
            and line.height > 0
            and line.text.strip()
        ):
            boxes.append(
                WordBox(
                    text=line.text,
                    confidence=line.confidence,
                    left=line.left / UPSCALE_FACTOR,
                    top=line.top / UPSCALE_FACTOR,
                    right=(line.left + line.width) / UPSCALE_FACTOR,
                    bottom=(line.top + line.height) / UPSCALE_FACTOR,
                )
            )
    return boxes


def _gutter_column(words: list[WordBox]) -> list[WordBox] | None:
    """Find the editor's line-number column: many right-aligned number tokens."""
    candidates = [
        word for word in words if LINE_NUMBER_WORD_RE.fullmatch(word.text.strip())
    ]
    if len(candidates) < MIN_GUTTER_WORDS:
        return None

    # Gutter numbers are right-aligned, so their right edges bunch tightly.
    tolerance = max(2.0, median(word.bottom - word.top for word in candidates))
    ordered = sorted(candidates, key=lambda word: word.right)
    groups: list[list[WordBox]] = [[ordered[0]]]
    for word in ordered[1:]:
        if word.right - groups[-1][-1].right > tolerance:
            groups.append([word])
        else:
            groups[-1].append(word)
    best = max(groups, key=len)
    return best if len(best) >= MIN_GUTTER_WORDS else None


def _keep_confident_segments(
    words: list[WordBox], frame_width: int
) -> tuple[list[WordBox], float | None]:
    """Split words on wide horizontal gaps; drop low-confidence right segments.

    A minimap or scrollbar OCRs as junk far to the right of the code. The
    leftmost segment (gutter + code) is always kept; segments after a gap
    survive only when their mean confidence does not look like noise. Returns
    the kept words plus the left edge of the first noisy segment (``None``
    when nothing was dropped) so the crop can cut right where the noise
    column starts instead of at the end of the code text.
    """
    ordered = sorted(words, key=lambda word: word.left)
    max_gap = frame_width * SEGMENT_GAP_FRACTION
    segments: list[list[WordBox]] = [[ordered[0]]]
    segment_right = ordered[0].right
    for word in ordered[1:]:
        if word.left - segment_right > max_gap:
            segments.append([word])
            segment_right = word.right
        else:
            segments[-1].append(word)
            segment_right = max(segment_right, word.right)

    kept = segments[0]
    for segment in segments[1:]:
        confidences = [
            word.confidence for word in segment if word.confidence is not None
        ]
        mean = sum(confidences) / len(confidences) if confidences else None
        if mean is not None and mean < MIN_SEGMENT_CONFIDENCE:
            return kept, min(word.left for word in segment)
        kept = kept + segment
    return kept, None


def observe_frame(frame: ReferenceFrame, engine: OCREngine) -> FrameObservation:
    """OCR one frame and record the geometry of the text it shows.

    The frame goes through the same preprocessing as the extraction pipeline
    (zero crop), so OCR geometry comes back in upscaled coordinates and is
    mapped down by ``UPSCALE_FACTOR``. The vertical extent is anchored on the
    line-number gutter when one is detected (excluding menu/tab/status rows);
    otherwise it falls back to the largest vertical cluster of text lines.
    Empty OCR yields ``text=None`` — an observation never invents a region.
    """
    processed = preprocess_frame(frame.image, CropBox())
    result: OCRResult = engine.recognize(processed)
    words = _word_boxes(result.lines)
    if not words:
        return FrameObservation(frame_index=frame.frame_index)

    gutter = _gutter_column(words)
    if gutter is not None:
        y0 = min(word.top for word in gutter)
        y1 = max(word.bottom for word in gutter)
    else:
        cluster = _main_text_cluster(_line_boxes(result.lines))
        y0 = min(box.top for box in cluster)
        y1 = max(box.bottom for box in cluster)

    band = [word for word in words if y0 <= (word.top + word.bottom) / 2 <= y1]
    kept, noise_left = _keep_confident_segments(band, frame.width)
    # With a gutter, nothing left of it belongs to the code (activity bar,
    # breakpoint column); the gutter itself is the true left edge.
    x0 = min(word.left for word in gutter or kept)
    return FrameObservation(
        frame_index=frame.frame_index,
        text=TextGeometry(
            left=x0,
            top=y0,
            bottom=y1,
            text_right=max(word.right for word in kept),
            noise_left=noise_left,
            line_height=median(word.bottom - word.top for word in kept),
            gutter_anchored=gutter is not None,
        ),
    )


def combine_observations(
    observations: list[FrameObservation],
    frame_width: int,
    frame_height: int,
    skipped_frame_indices: list[int] | None = None,
) -> CropSuggestion:
    """Merge per-frame observations into one crop safe for every frame.

    Gutter-anchored observations outrank cluster-fallback ones: the fallback
    band can sweep in menu/status chrome and reflections, so it informs the
    crop only when no sampled frame found a gutter (the same precedence
    ``observe_frame`` applies within a frame). Among the informing frames,
    left/top/bottom take the union of the detected text bands, so the widest
    observed gutter and the tallest text block are never cut. The right edge
    is deliberately conservative: it cuts only when a majority of the
    informing frames detected a noise column (minimap, scrollbar), and then
    at the rightmost noise start clamped past every informing frame's kept
    text — never at the end of the code, since short lines would make that
    crop far too aggressive. Empty-OCR observations contribute nothing; when
    none has text the result is a zero crop with ``text_detected=False``.
    """
    analyzed = [observation.frame_index for observation in observations]
    skipped = skipped_frame_indices or []
    candidates = [
        (obs.frame_index, obs.text) for obs in observations if obs.text is not None
    ]
    anchored = [(index, g) for index, g in candidates if g.gutter_anchored]
    informing = anchored or candidates
    geometries = [g for _, g in informing]
    if not geometries:
        return CropSuggestion(
            crop=CropBox(),
            text_detected=False,
            analyzed_frame_indices=analyzed,
            skipped_frame_indices=skipped,
        )

    line_height = median(geometry.line_height for geometry in geometries)
    margin = max(MIN_CROP_MARGIN_PX, round(line_height * CROP_MARGIN_FACTOR))
    noise_lefts = [g.noise_left for g in geometries if g.noise_left is not None]
    if 2 * len(noise_lefts) > len(geometries):
        cut = max([*noise_lefts, *(g.text_right for g in geometries)])
        right = max(0, frame_width - round(cut))
    else:
        right = 0
    crop = CropBox(
        left=max(0, round(min(g.left for g in geometries)) - margin),
        top=max(0, round(min(g.top for g in geometries)) - margin),
        right=right,
        bottom=max(0, frame_height - round(max(g.bottom for g in geometries)) - margin),
    )
    return CropSuggestion(
        crop=crop,
        text_detected=True,
        analyzed_frame_indices=analyzed,
        text_frame_indices=[index for index, _ in informing],
        skipped_frame_indices=skipped,
    )


def suggest_crop(frame: ReferenceFrame, engine: OCREngine) -> CropSuggestion:
    """Single-frame suggestion: observe one frame and combine it alone."""
    return combine_observations(
        [observe_frame(frame, engine)], frame.width, frame.height
    )


def suggest_crop_for_video(samples: SampledFrames, engine: OCREngine) -> CropSuggestion:
    """Observe every sampled frame and combine them into one video-wide crop."""
    observations = [observe_frame(frame, engine) for frame in samples.frames]
    reference = samples.frames[0]
    return combine_observations(
        observations,
        reference.width,
        reference.height,
        skipped_frame_indices=samples.failed_indices,
    )


def cli_flags(crop: CropBox) -> str:
    """Format a crop as ready-to-copy `extract_code_from_video.py` flags."""
    return (
        f"--crop-left {crop.left} --crop-top {crop.top} "
        f"--crop-right {crop.right} --crop-bottom {crop.bottom}"
    )


def _crop_error(crop: CropBox, width: int, height: int) -> str | None:
    """Reuse `CropBox.validate_against`, converting its CLI exit into a message."""
    try:
        crop.validate_against(width, height)
    except typer.Exit:
        return (
            f"crop leaves no image area for a {width}x{height} frame: "
            f"left + right must stay below {width} and top + bottom below {height}."
        )
    return None


def _png_base64(image: MatLike) -> str:
    """Encode an image as a base64 PNG string for JSON transport."""
    cv2 = _require_cv2()
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("could not encode the preview image as PNG.")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _apply_crop_view(frame: ReferenceFrame, crop: CropBox) -> MatLike:
    """Slice the reference frame to the crop box (same semantics as the CLI)."""
    return frame.image[
        crop.top : frame.height - crop.bottom, crop.left : frame.width - crop.right
    ]


def create_app(
    video: Path,
    default_engine: EngineName,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> FastAPI:
    """Build the preview app: sample frames and suggest the default crop eagerly.

    Failures (unreadable video, missing OCR backend) surface here, before the
    server starts. The first sampled frame is the before/after preview image;
    suggestions combine all sampled frames and are cached per engine, and
    re-crops reuse the cached frame without reopening the video.
    """
    samples = read_sampled_frames(video, sample_count)
    frame = samples.frames[0]
    suggestions: dict[EngineName, CropSuggestion] = {
        default_engine: suggest_crop_for_video(
            samples, create_ocr_engine(default_engine)
        )
    }
    original_png = _png_base64(frame.image)
    page = (Path(__file__).parent / "crop_preview.html").read_text(encoding="utf-8")

    app = FastAPI(title="Crop suggestion preview")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

    @app.get("/api/preview")
    def preview(engine: EngineName = default_engine) -> PreviewResponse:
        if engine not in suggestions:
            try:
                suggestions[engine] = suggest_crop_for_video(
                    samples, create_ocr_engine(engine)
                )
            except OCREngineUnavailableError as exc:
                raise HTTPException(status_code=400, detail=_plain(str(exc))) from exc
        suggestion = suggestions[engine]
        return PreviewResponse(
            video_name=video.name,
            engine=engine,
            frame_index=frame.frame_index,
            frame_width=frame.width,
            frame_height=frame.height,
            text_detected=suggestion.text_detected,
            analyzed_frame_indices=suggestion.analyzed_frame_indices,
            text_frame_indices=suggestion.text_frame_indices,
            skipped_frame_indices=suggestion.skipped_frame_indices,
            crop=suggestion.crop,
            cli_flags=cli_flags(suggestion.crop),
            original_png_base64=original_png,
            cropped_png_base64=_png_base64(_apply_crop_view(frame, suggestion.crop)),
        )

    @app.post("/api/crop")
    def crop_preview(request: CropRequest) -> CropResponse:
        crop = CropBox(
            left=request.left,
            top=request.top,
            right=request.right,
            bottom=request.bottom,
        )
        error = _crop_error(crop, frame.width, frame.height)
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        cropped = _apply_crop_view(frame, crop)
        return CropResponse(
            crop=crop,
            cli_flags=cli_flags(crop),
            cropped_width=frame.width - crop.left - crop.right,
            cropped_height=frame.height - crop.top - crop.bottom,
            cropped_png_base64=_png_base64(cropped),
        )

    return app


@cli.command()
def main(
    video: Annotated[Path, typer.Option(help="Video to suggest a crop for.")],
    engine: Annotated[
        EngineName,
        typer.Option(help="OCR engine for the crop suggestion."),
    ] = EngineName.tesseract,
    sample_count: Annotated[
        int,
        typer.Option(min=1, help="Frames sampled across the video for the suggestion."),
    ] = DEFAULT_SAMPLE_COUNT,
    host: Annotated[
        str, typer.Option(help="Interface to bind; keep the local default.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port for the local server.")] = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page automatically.")
    ] = True,
) -> None:
    """Serve a local page to preview and fine-tune crop values for VIDEO."""
    if not video.is_file():
        _fail(f"video file not found: [cyan]{video}[/cyan]")
    try:
        app = create_app(video, engine, sample_count)
    except (ReferenceFrameError, OCREngineUnavailableError) as exc:
        _fail(str(exc))

    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except OSError as exc:
        _fail(f"could not start the server on {url} ({exc}); try another --port.")


if __name__ == "__main__":
    cli()
