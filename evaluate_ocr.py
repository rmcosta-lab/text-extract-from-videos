"""Compare OCR preprocessing against a partial, manually transcribed reference."""

import hashlib
import json
import platform
from importlib import import_module, metadata
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any

import typer

from video_ocr.imaging import preprocess_frame
from video_ocr.models import (
    EngineName,
    OCRRow,
    PreprocessConfig,
    PreprocessProfile,
    require_cv2,
)
from video_ocr.ocr import create_ocr_engine
from video_ocr.quality import LineScore, ReferenceSet, score_lines, summarize
from video_ocr.reconstruction import parse_code_lines
from video_ocr.video import get_video_metadata, resolve_extraction_parameters

app = typer.Typer(add_completion=False)


@app.command()
def main(
    reference: Path = Path("tests/fixtures/IMG_1128.reference.json"),
    output: Path = Path("saida/avaliacao"),
    require_gpu: bool = False,
    profiles: Annotated[
        list[PreprocessProfile] | None, typer.Option("--profile")
    ] = None,
    max_cer: Annotated[float | None, typer.Option(min=0)] = None,
    min_number_accuracy: Annotated[float | None, typer.Option(min=0, max=1)] = None,
) -> None:
    """Score the same frames/crop across profiles; preserve per-line evidence."""
    spec = ReferenceSet.model_validate_json(reference.read_text(encoding="utf-8"))
    video = Path(spec.video)
    if require_gpu:
        paddle = import_module("paddle")
        if not paddle.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
            raise typer.BadParameter("A working Paddle CUDA GPU is required")
    info = get_video_metadata(video)
    window = resolve_extraction_parameters(
        engine=EngineName.paddle,
        crop=spec.crop,
        metadata=info,
        start_time=spec.start_time,
        end_time=spec.end_time,
        step=30,
    )
    spec.crop.validate_against(info.width, info.height)
    output.mkdir(parents=True, exist_ok=True)
    cv2 = require_cv2()
    capture = cv2.VideoCapture(str(video))
    frames: dict[int, Any] = {}
    try:
        for sample in spec.samples:
            if not (
                window.sample_start_frame
                <= sample.frame_index
                < window.sample_end_frame_exclusive
            ):
                raise typer.BadParameter("Reference frame is outside the segment")
            capture.set(cv2.CAP_PROP_POS_FRAMES, sample.frame_index)
            ok, image = capture.read()
            if not ok:
                raise RuntimeError(f"Cannot decode frame {sample.frame_index}")
            frames[sample.frame_index] = image
            if not cv2.imwrite(
                str(output / f"reference_{sample.frame_index}.png"), image
            ):
                raise RuntimeError("Cannot save reference image")
    finally:
        capture.release()
    engine = create_ocr_engine(EngineName.paddle)
    variants = profiles or list(PreprocessProfile)
    results: list[dict[str, Any]] = []
    for variant in variants:
        config = PreprocessConfig(profile=variant, scale=2, max_side=4000)
        # Warm each shape/profile once; initialization and warm-up are not timed.
        engine.recognize(
            preprocess_frame(next(iter(frames.values())), spec.crop, config)
        )
        all_scores: list[LineScore] = []
        samples = []
        elapsed = 0.0
        for sample in spec.samples:
            started = perf_counter()
            processed = preprocess_frame(frames[sample.frame_index], spec.crop, config)
            result = engine.recognize(processed)
            seconds = perf_counter() - started
            elapsed += seconds
            row = OCRRow(
                text=result.text,
                lines=result.lines,
                confidence=result.confidence,
                frame_number=sample.frame_index,
                time_seconds=sample.frame_index / info.fps,
                time_formatted=str(sample.frame_index / info.fps),
                sharpness=0,
                frame_image_path="",
            )
            scores = score_lines(sample.lines, parse_code_lines([row]))
            all_scores.extend(scores)
            samples.append(
                {
                    "frame_index": sample.frame_index,
                    "seconds": seconds,
                    "processed_shape": list(processed.shape),
                    "scores": [s.model_dump() for s in scores],
                    "ocr": result.model_dump(),
                }
            )
        summary = summarize(all_scores)
        results.append(
            {
                "config": config.model_dump(mode="json"),
                "seconds": elapsed,
                "summary": summary,
                "samples": samples,
            }
        )
        print(variant.value, json.dumps(summary), f"{elapsed:.2f}s")
    with video.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "reference": spec.model_dump(),
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "video_sha256": digest,
        "metadata": info.model_dump(),
        "python": platform.python_version(),
        "versions": {
            p: metadata.version(p)
            for p in ("paddleocr", "paddlepaddle-gpu", "opencv-contrib-python")
        },
        "timing": "One warm-up per profile excluded; preprocessing + OCR only. "
        "Single measurement, not a statistically robust benchmark.",
        "variants": results,
    }
    (output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for variant_result in results:
        measured = variant_result["summary"]
        accuracy = measured["correct_numbers"] / max(1, measured["reference_lines"])
        if (max_cer is not None and measured["cer"] > max_cer) or (
            min_number_accuracy is not None and accuracy < min_number_accuracy
        ):
            typer.echo(
                f"Quality gate failed: {variant_result['config']['profile']}", err=True
            )
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
