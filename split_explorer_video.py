"""Calibrate and split videos locally when the Explorer panel is hidden."""

import hashlib
import itertools
import json
import subprocess
from pathlib import Path
from typing import Annotated, Any, Literal

import cv2
import typer

from explorer_segments.detection import Profile, Region, TemplateDetector
from explorer_segments.media import VideoReader, executable, export_clip, probe
from explorer_segments.timeline import scan, summarize

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command("auto")
def automatic_split(
    video: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    scan_fps: Annotated[float, typer.Option(min=0, max=240)] = 4,
    interval_mode: Literal["continuous", "strict"] = "strict",
    discovery_samples: Annotated[int, typer.Option(min=4, max=1000)] = 32,
    model_root: Path | None = None,
    device: str = "gpu:0",
    analyze_only: bool = False,
    encoder: Literal["libx264", "h264_nvenc"] = "libx264",
    max_clip_seconds: Annotated[float, typer.Option(min=0)] = 0,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
) -> None:
    """Automatically locate Explorer using local AI; no reference times or ROIs."""
    from explorer_segments.automatic import LocalOCR, discover  # noqa: PLC0415

    try:
        if output.exists():
            raise ValueError("Output exists; choose a new directory")
        # Validate input/tool before loading the optional model runtime.
        probe(video, executable("ffprobe", ffprobe))
        ocr = LocalOCR(model_root, device)
        profile = discover(
            video, output / "automatic_profile", ocr, typer.echo, discovery_samples
        )
        del ocr
        split(
            video=video,
            profile=profile,
            output=output / "analysis",
            scan_fps=scan_fps,
            interval_mode=interval_mode,
            analyze_only=analyze_only,
            encoder=encoder,
            max_clip_seconds=max_clip_seconds,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        )
        typer.echo(f"Error: {detail}", err=True)
        raise typer.Exit(1) from None


def save_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def region(value: str) -> Region:
    numbers = [float(n) for n in value.split(",")]
    if len(numbers) != 4:
        raise ValueError("Region requires x,y,width,height normalized to 0..1")
    return Region(x=numbers[0], y=numbers[1], width=numbers[2], height=numbers[3])


@app.command()
def frame(
    video: Annotated[Path, typer.Option()],
    at: Annotated[float, typer.Option(min=0)],
    output: Annotated[Path, typer.Option()],
) -> None:
    """Save an oriented frame for choosing calibration regions (x/W,y/H,w/W,h/H)."""
    try:
        if output.exists():
            raise ValueError("Frame output exists")
        reader = VideoReader(video)
        try:
            index, seconds, image = reader.read_at(at)
        finally:
            reader.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output), image):
            raise OSError("Could not save frame")
        typer.echo(
            f"Frame {index}, {seconds:.6f}s, "
            f"{image.shape[1]}x{image.shape[0]} saved in {output}"
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("export")
def export_segments(
    report: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    encoder: Literal["libx264", "h264_nvenc"] = "libx264",
    ffmpeg: Path | None = None,
) -> None:
    """Export a saved analysis without scanning again; original video must match."""
    try:
        if output.exists():
            raise ValueError("Export output exists; choose a new directory")
        analysis = json.loads(report.read_text(encoding="utf-8"))
        if analysis.get("schema_version") != 1:
            raise ValueError("Unsupported analysis schema")
        video = Path(analysis["video"])
        if video.stat().st_size != analysis["video_size"] or (
            video.stat().st_mtime_ns != analysis["video_mtime_ns"]
        ):
            raise ValueError("Source video changed since analysis")
        binary = executable("ffmpeg", ffmpeg)
        duration = float(analysis["metadata"]["format"]["duration"])
        for clip in analysis["clips"]:
            if not 0 <= clip["start"] < clip["end"] <= duration:
                raise ValueError("Invalid segment in analysis")
        output.mkdir(parents=True)
        exported: dict[str, Any] = {
            "analysis": str(report.resolve()),
            "encoder": encoder,
            "analysis_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            "clips": [],
        }
        save_json(output / "export.json", exported)
        for index, clip in enumerate(analysis["clips"], 1):
            filename = f"clip_{index:03d}.mp4"
            typer.echo(f"Exporting {filename}: {clip['start']:.3f}..{clip['end']:.3f}s")
            export_clip(
                video, output / filename, clip["start"], clip["end"], binary, encoder
            )
            exported["clips"].append({**clip, "file": filename, "status": "exported"})
            save_json(output / "export.json", exported)
        typer.echo(f"Exported {len(exported['clips'])} clips in {output}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        )
        typer.echo(f"Error: {detail}", err=True)
        raise typer.Exit(1) from None


@app.command()
def calibrate(
    video: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    present_at: Annotated[float, typer.Option(min=0)],
    absent_at: Annotated[float, typer.Option(min=0)],
    panel_roi: Annotated[
        str, typer.Option(help="Stable Explorer area: normalized x,y,w,h.")
    ],
    anchor_roi: Annotated[str, typer.Option(help="Stable UI outside panel: x,y,w,h.")],
    present_threshold: float = 0.88,
    absent_threshold: float = 0.76,
    anchor_threshold: float = 0.72,
) -> None:
    """Create reusable references from two known moments; no model downloads."""
    try:
        if output.exists():
            raise ValueError("Calibration output exists; choose a new directory")
        profile = Profile(
            reference_present="present.png",
            reference_absent="absent.png",
            panel_region=region(panel_roi),
            anchor_region=region(anchor_roi),
            present_threshold=present_threshold,
            absent_threshold=absent_threshold,
            anchor_threshold=anchor_threshold,
        )
        reader = VideoReader(video)
        try:
            present = reader.read_at(present_at)
            absent = reader.read_at(absent_at)
        finally:
            reader.close()
        output.mkdir(parents=True)
        for name, observation in (("present", present), ("absent", absent)):
            if not cv2.imwrite(str(output / f"{name}.png"), observation[2]):
                raise OSError("Cannot save calibration frame")
        TemplateDetector(profile, output)
        save_json(output / "profile.json", profile.model_dump())
        save_json(
            output / "calibration.json",
            {
                "video": str(video.resolve()),
                "present": {"frame": present[0], "seconds": present[1]},
                "absent": {"frame": absent[0], "seconds": absent[1]},
            },
        )
        typer.echo(f"Calibration saved: {output / 'profile.json'}")
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def split(
    video: Annotated[Path, typer.Option()],
    profile: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    scan_fps: Annotated[float, typer.Option(min=0, max=240)] = 4,
    interval_mode: Literal["continuous", "strict"] = "strict",
    confirm_seconds: Annotated[float, typer.Option(min=0)] = 0.15,
    min_duration: Annotated[float, typer.Option(min=0.01)] = 1,
    max_clip_seconds: Annotated[float, typer.Option(min=0)] = 0,
    margin_seconds: Annotated[float, typer.Option(min=0)] = 0,
    analyze_only: bool = False,
    encoder: Literal["libx264", "h264_nvenc"] = "libx264",
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
) -> None:
    """Detect transitions and export continuous intervals or strict absent runs.

    --scan-fps 0 inspects every frame. Sampled mode can miss changes shorter than
    its interval; refined transitions do not imply exhaustive full-video coverage.
    """
    try:
        if output.exists():
            raise ValueError("Output exists; select a new directory")
        if max_clip_seconds and max_clip_seconds < min_duration:
            raise ValueError("--max-clip-seconds must be zero or >= --min-duration")
        settings = Profile.model_validate_json(profile.read_text(encoding="utf-8"))
        detector = TemplateDetector(settings, profile.parent)
        metadata = probe(video, executable("ffprobe", ffprobe))
        duration = float(metadata["format"]["duration"])
        binary = executable("ffmpeg", ffmpeg) if not analyze_only else ""
        reader = VideoReader(video)
        try:
            observations = scan(
                reader,
                detector,
                duration,
                scan_fps,
                progress=lambda t: typer.echo(f"Scanning {t:.1f}/{duration:.1f}s"),
                refinement_progress=lambda t: typer.echo(
                    f"Refining transitions {t:.1f}/{duration:.1f}s"
                ),
            )
            result = summarize(
                observations,
                min_duration,
                max_clip_seconds,
                margin_seconds,
                confirm_seconds,
                interval_mode=interval_mode,
            )
            output.mkdir(parents=True)
            for index, event in enumerate(result["transitions"], 1):
                for label, key in (
                    ("before", "last_previous_frame"),
                    ("after", "first_confirmed_frame"),
                ):
                    _, _, frame = reader.read_frame(event[key])
                    filename = f"transition_{index:03d}_{label}.jpg"
                    if not cv2.imwrite(str(output / filename), frame):
                        raise OSError("Could not save transition evidence")
                    event[label + "_image"] = filename
        finally:
            reader.close()
        for index, clip in enumerate(result["clips"], 1):
            clip.update(file=f"clip_{index:03d}.mp4", status="planned")
        result.update(
            schema_version=1,
            video=str(video.resolve()),
            video_size=video.stat().st_size,
            video_mtime_ns=video.stat().st_mtime_ns,
            metadata=metadata,
            profile=settings.model_dump(),
            reference_sha256={
                name: hashlib.sha256((profile.parent / name).read_bytes()).hexdigest()
                for name in (settings.reference_present, settings.reference_absent)
            },
            parameters={
                "scan_fps": scan_fps,
                "interval_mode": interval_mode,
                "confirm_seconds": confirm_seconds,
                "min_duration": min_duration,
                "max_clip_seconds": max_clip_seconds,
                "margin_seconds": margin_seconds,
                "encoder": encoder,
            },
            observations=[o.model_dump() for o in observations],
            coverage="every_frame"
            if scan_fps == 0
            else "sampled_with_transition_refinement",
            max_observed_gap_seconds=max(
                (b.seconds - a.seconds for a, b in itertools.pairwise(observations)),
                default=0,
            ),
            status="analyzed",
        )
        save_json(output / "segments.json", result)
        report = [
            "# Explorer: transições e cortes",
            "",
            "Detecção local calibrada por referências. Scores não são probabilidades.",
            (
                "Frames ambíguos são excluídos."
                if interval_mode == "strict"
                else "Modo contínuo: lacunas incertas e aparições breves são mantidas."
            ),
            "Confira as imagens das transições.",
            "",
            f"Cobertura: {result['coverage']}; maior intervalo observado: "
            f"{result['max_observed_gap_seconds']:.6f}s.",
            "",
            "## Transições",
            "",
        ]
        for event in result["transitions"]:
            report.append(
                f"- {event['event']}: {event['first_confirmed_seconds']:.6f}s, "
                f"frame {event['first_confirmed_frame']}; faixa de transição "
                f"{event['last_previous_seconds']:.6f}.."
                f"{event['first_confirmed_seconds']:.6f}s. "
                f"[Antes]({event['before_image']}) / [Depois]({event['after_image']})"
            )
        report += ["", "## Clipes planejados", ""]
        report += [
            f"- `{c['file']}`: {c['start']:.6f}..{c['end']:.6f}s ({c['duration']:.3f}s)"
            for c in result["clips"]
        ]
        (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        if not analyze_only:
            for clip in result["clips"]:
                typer.echo(f"Exporting {clip['file']} ({clip['duration']:.2f}s)")
                export_clip(
                    video,
                    output / clip["file"],
                    clip["start"],
                    clip["end"],
                    binary,
                    encoder,
                )
                clip["status"] = "exported"
                save_json(output / "segments.json", result)
            result["status"] = "completed"
            save_json(output / "segments.json", result)
        typer.echo(
            f"Done: {len(result['transitions'])} transitions, "
            f"{len(result['clips'])} clips. Results in {output}"
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        )
        typer.echo(f"Error: {detail}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
