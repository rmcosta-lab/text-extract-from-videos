"""Typed clip settings, discovery and explicit CLI adapters."""

import shlex
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from video_ocr.models import (
    CropBox,
    EngineName,
    InvalidExtractionParameterError,
    OutputExtension,
    validate_output_name,
)
from video_ocr.video import _parse_timestamp

ROOT = Path(__file__).resolve().parent.parent
VIDEO_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".wmv",
    ".mts",
    ".m2ts",
}
Action = Literal["extract", "review", "combined", "crop"]


def parse_crop(text: str) -> CropBox:
    """Accept only the four numeric crop flags, without any shell execution."""
    tokens = shlex.split(text)
    values: dict[str, int] = {}
    if len(tokens) % 2:
        raise ValueError("Use pares como --crop-left 20 --crop-top 10.")
    for flag, value in zip(tokens[::2], tokens[1::2], strict=True):
        side = flag.removeprefix("--crop-")
        if flag != f"--crop-{side}" or side not in {"left", "top", "right", "bottom"}:
            raise ValueError(f"Parâmetro de crop não permitido: {flag}")
        if side in values or not value.isascii() or not value.isdecimal():
            raise ValueError(f"Valor inválido ou duplicado para {flag}.")
        values[side] = int(value)
    return CropBox.model_validate(values)


class ClipSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video: Path
    output_base: Path | None = None
    engine: EngineName = EngineName.paddle
    extension: OutputExtension = OutputExtension.txt
    crop_text: str = ""
    start_time: str | None = None
    end_time: str | None = None
    prepare_review: bool = True

    @field_validator("start_time", "end_time")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        if not value:
            return None
        try:
            _parse_timestamp(value, "tempo")
        except InvalidExtractionParameterError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("crop_text")
    @classmethod
    def crop_flags(cls, value: str) -> str:
        parse_crop(value)
        return value


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    clips: list[ClipSettings] = Field(min_length=1, max_length=500)
    concurrency: int = Field(default=3, ge=1, le=500, strict=True)


class Destinations(BaseModel):
    base: Path
    extraction: Path
    review: Path
    exists: bool


class ClipInfo(BaseModel):
    name: str
    video: Path
    extension: OutputExtension
    inferred: bool
    destinations: Destinations


def destinations(settings: ClipSettings) -> Destinations:
    video = settings.video.resolve()
    stem = validate_output_name(video.stem)
    if settings.output_base is None and video.parent.name.casefold() != "clip":
        raise ValueError(
            "Informe a pasta base de saída para pastas que não se chamam clip."
        )
    base = (settings.output_base or video.parent.parent / "extract").resolve()
    extraction = base / stem / "extract"
    review = base / stem / "revisao"
    return Destinations(
        base=base,
        extraction=extraction,
        review=review,
        exists=extraction.exists() or review.exists(),
    )


def inventory(folder: Path, output_base: Path | None = None) -> list[ClipInfo]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("Pasta não encontrada. Informe uma pasta local acessível.")
    result = []
    for video in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not video.is_file() or video.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        suffix = Path(video.stem).suffix.lower().lstrip(".")
        inferred = suffix in {extension.value for extension in OutputExtension}
        extension = OutputExtension(suffix) if inferred else OutputExtension.txt
        # Discovery remains usable outside the conventional layout; the UI shows
        # this explicit suggested base and sends it back in the submitted settings.
        base = output_base or video.parent.parent / "extract"
        settings = ClipSettings(video=video, output_base=base, extension=extension)
        result.append(
            ClipInfo(
                name=video.name,
                video=video,
                extension=extension,
                inferred=inferred,
                destinations=destinations(settings),
            )
        )
    return result


def command(settings: ClipSettings, stage: str, port: int = 0) -> list[str]:
    paths = destinations(settings)
    script = {
        "extract": "extract_code_from_video.py",
        "review": "review_ocr.py",
        "crop": "suggest_crop.py",
    }[stage]
    args = [sys.executable, "-u", str(ROOT / script)]
    if stage == "crop":
        args = [sys.executable, "-u", "-m", "clip_ui.crop_preview"]
    if stage == "review":
        return [
            *args,
            "--extraction",
            str(paths.extraction),
            "--output",
            str(paths.review),
            "--image-detail",
            "original",
            "--system-certs",
            "--max-output-tokens",
            "64000",
        ]
    args += [
        "--video",
        str(settings.video.resolve()),
        "--engine",
        settings.engine.value,
    ]
    for flag, value in (
        ("--start-time", settings.start_time),
        ("--end-time", settings.end_time),
    ):
        if value is not None:
            args += [flag, value]
    if stage == "crop":
        return [*args, "--port", str(port)]
    args += [
        "--output",
        str(paths.base),
        "--output-extension",
        settings.extension.value,
    ]
    if settings.prepare_review:
        args.append("--prepare-review")
    for side, value in parse_crop(settings.crop_text).model_dump().items():
        args += [f"--crop-{side}", str(value)]
    return args


def validate_video(settings: ClipSettings, *, crop_preview: bool = False) -> None:
    """Preflight before the extraction CLI can clear a pre-existing output tree."""
    from video_ocr.video import (  # noqa: PLC0415
        adaptive_sample_step,
        get_video_metadata,
        resolve_extraction_parameters,
    )

    if not settings.video.is_file():
        raise ValueError(f"Vídeo não encontrado: {settings.video}")
    metadata = get_video_metadata(settings.video)
    crop = CropBox() if crop_preview else parse_crop(settings.crop_text)
    crop.validate_against(metadata.width, metadata.height)
    parameters = resolve_extraction_parameters(
        engine=settings.engine,
        crop=crop,
        metadata=metadata,
        start_time=settings.start_time,
        end_time=settings.end_time,
        step=adaptive_sample_step(metadata.fps),
    )
    if parameters.expected_candidate_frames == 0:
        raise ValueError("O intervalo não contém frames. Amplie o início/fim.")
