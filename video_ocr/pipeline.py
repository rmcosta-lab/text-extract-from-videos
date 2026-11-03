"""Pipeline for local video OCR."""

from collections.abc import Iterable
from pathlib import Path

from rich.progress import track

from video_ocr.imaging import (
    _cropped_grayscale,
    _ssim_thumbnail,
    frame_sharpness,
    is_frame_blurry,
    preprocess_frame,
)
from video_ocr.models import (
    SSIM_THRESHOLD,
    CropBox,
    FrameOutcome,
    MatLike,
    OCREngine,
    OCRRow,
    PreprocessConfig,
    SelectionStats,
    _format_time,
    _require_structural_similarity,
    console,
    fail,
    require_cv2,
)


def run_ocr(
    frames: Iterable[tuple[int, float, MatLike]],
    engine: OCREngine,
    frames_dir: Path,
    expected_samples: int,
    crop: CropBox,
    preprocessing: PreprocessConfig | None = None,
) -> tuple[list[OCRRow], SelectionStats, list[FrameOutcome]]:
    """OCR the sampled frames that survive selection.

    Per candidate: crop + grayscale → blur gate → SSIM near-duplicate gate
    against the last accepted frame → full preprocessing → save the
    preprocessed image (what OCR actually sees) to `frames_usados/` → OCR.
    An empty OCR read is recorded as a row with empty text, not an error.
    Every sampled frame also yields a :class:`FrameOutcome` — usable when it
    was kept and OCR returned non-blank text, or when it was discarded as a
    near-duplicate (its content is covered by the accepted neighbor) — so the
    failure report can surface unextractable time spans from observed
    outcomes.
    """
    rows: list[OCRRow] = []
    stats = SelectionStats()
    outcomes: list[FrameOutcome] = []
    cv2 = require_cv2()
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
    last_accepted_usable = False
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
                # A near-duplicate is covered by the accepted neighbor only when
                # that neighbor actually yielded text; if the neighbor's OCR was
                # blank the span is still unread, not "impossible to extract".
                record_outcome(frame_number, time_seconds, usable=last_accepted_usable)
                continue
        last_accepted_thumbnail = thumbnail

        processed = preprocess_frame(image, crop, preprocessing)
        frame_path = frames_dir / f"frame_{frame_number}.png"
        if not cv2.imwrite(str(frame_path), processed):
            fail(f"could not save frame image: [cyan]{frame_path}[/cyan]")
        result = engine.recognize(processed)
        last_accepted_usable = bool(result.text.strip())
        record_outcome(frame_number, time_seconds, usable=last_accepted_usable)
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
