"""Suggest crop parameters for a video and preview them in a local web page.

Phase 10: read a reference frame (frame 30) from the video, OCR it with the
selected engine (Tesseract default, PaddleOCR optional), and derive a crop box
that isolates the line-number gutter plus the code text. A small FastAPI
server (bound to 127.0.0.1) serves a single static page showing the frame
before and after the crop; editing the values re-crops the cached frame on the
backend and refreshes the preview. The confirmed values are meant to be copied
into `extract_code_from_video.py --crop-*` — this tool never runs a full
extraction and never applies a crop silently. Empty OCR on the reference frame
yields a zero crop with an explicit "no text detected" notice, never a
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
"""Frame used as the crop-suggestion reference (falls back to the last frame)."""

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


class CropSuggestion(BaseModel):
    """Suggested crop for the reference frame, with an honesty flag."""

    crop: CropBox
    text_detected: bool


class ReferenceFrame(BaseModel):
    """The decoded reference frame plus which index was actually used."""

    model_config = {"arbitrary_types_allowed": True}

    image: MatLike
    frame_index: int
    width: int
    height: int


class PreviewResponse(BaseModel):
    """`GET /api/preview` payload: suggestion plus both preview images."""

    video_name: str
    engine: EngineName
    frame_index: int
    frame_width: int
    frame_height: int
    text_detected: bool
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


def read_reference_frame(
    video: Path, index: int = REFERENCE_FRAME_INDEX
) -> ReferenceFrame:
    """Decode the reference frame, falling back to the last frame if shorter."""
    cv2 = _require_cv2()
    metadata = get_video_metadata(video)
    frame_index = min(index, metadata.total_frames - 1)
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ReferenceFrameError(f"cannot open video for decoding: {video}")
        if frame_index:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, image = capture.read()
        if not ok:
            raise ReferenceFrameError(
                f"could not decode frame {frame_index} of {video}; the video may "
                "be corrupt, truncated, or in an unsupported format."
            )
    finally:
        capture.release()
    height, width = image.shape[:2]
    return ReferenceFrame(
        image=image, frame_index=frame_index, width=width, height=height
    )


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


def suggest_crop(frame: ReferenceFrame, engine: OCREngine) -> CropSuggestion:
    """OCR the reference frame and derive an edge-based crop around the text.

    The frame goes through the same preprocessing as the extraction pipeline
    (zero crop), so OCR geometry comes back in upscaled coordinates and is
    mapped down by ``UPSCALE_FACTOR``. The vertical extent is anchored on the
    line-number gutter when one is detected (excluding menu/tab/status rows);
    otherwise it falls back to the largest vertical cluster of text lines.
    The right edge is deliberately conservative: it removes only the
    low-confidence noise column (minimap, scrollbar), cutting where that
    column starts — never at the end of the code text, since short lines
    would make that crop far too aggressive. Empty OCR yields a zero crop and
    ``text_detected=False`` — the suggestion never invents a region.
    """
    processed = preprocess_frame(frame.image, CropBox())
    result: OCRResult = engine.recognize(processed)
    words = _word_boxes(result.lines)
    if not words:
        return CropSuggestion(crop=CropBox(), text_detected=False)

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

    median_height = median(word.bottom - word.top for word in kept)
    margin = max(MIN_CROP_MARGIN_PX, round(median_height * CROP_MARGIN_FACTOR))
    crop = CropBox(
        left=max(0, round(x0) - margin),
        top=max(0, round(y0) - margin),
        right=0 if noise_left is None else max(0, frame.width - round(noise_left)),
        bottom=max(0, frame.height - round(y1) - margin),
    )
    return CropSuggestion(crop=crop, text_detected=True)


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


def create_app(video: Path, default_engine: EngineName) -> FastAPI:
    """Build the preview app: decode frame 30 and suggest the default crop eagerly.

    Failures (unreadable video, missing OCR backend) surface here, before the
    server starts. Suggestions are cached per engine; re-crops reuse the cached
    frame without reopening the video.
    """
    frame = read_reference_frame(video)
    suggestions: dict[EngineName, CropSuggestion] = {
        default_engine: suggest_crop(frame, create_ocr_engine(default_engine))
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
                suggestions[engine] = suggest_crop(frame, create_ocr_engine(engine))
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
        app = create_app(video, engine)
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
