"""Cli for local video OCR."""

from pathlib import Path
from typing import (
    Annotated,
)

import typer

from video_ocr.models import (
    TIMESTAMP_FORMAT_HELP,
    CropBox,
    EngineName,
    FailureReport,
    InvalidExtractionParameterError,
    OCREngineUnavailableError,
    OutputExtension,
    PreprocessConfig,
    PreprocessProfile,
    SelectionStats,
    app,
    console,
    fail,
)
from video_ocr.ocr import (
    create_ocr_engine,
)
from video_ocr.pipeline import (
    run_ocr,
)
from video_ocr.reconstruction import (
    detect_missing_lines,
    has_line_numbers,
    merge_ocr_results,
    parse_code_lines,
    reconstruct_by_time,
    unextractable_sections,
)
from video_ocr.reports import (
    _bail_with_report,
    prepare_output_tree,
    write_extraction_parameters,
    write_metadata,
    write_outputs,
)
from video_ocr.video import (
    adaptive_sample_step,
    get_video_metadata,
    resolve_extraction_parameters,
    sample_frames,
    uncertain_confidence_for,
)


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
        int,
        typer.Option(min=0, help="Pixels to crop from the left edge before OCR."),
    ] = 0,
    crop_top: Annotated[
        int,
        typer.Option(min=0, help="Pixels to crop from the top edge before OCR."),
    ] = 0,
    crop_right: Annotated[
        int,
        typer.Option(min=0, help="Pixels to crop from the right edge before OCR."),
    ] = 0,
    crop_bottom: Annotated[
        int,
        typer.Option(min=0, help="Pixels to crop from the bottom edge before OCR."),
    ] = 0,
    start_time: Annotated[
        str | None,
        typer.Option(
            "--start-time",
            help="Start timestamp for extraction; accepted forms: "
            f"{TIMESTAMP_FORMAT_HELP}.",
        ),
    ] = None,
    end_time: Annotated[
        str | None,
        typer.Option(
            "--end-time",
            help="End timestamp for extraction; accepted forms: "
            f"{TIMESTAMP_FORMAT_HELP}.",
        ),
    ] = None,
    engine_name: Annotated[
        EngineName,
        typer.Option(
            "--engine",
            help="OCR engine used to read the sampled frames.",
        ),
    ] = EngineName.tesseract,
    preprocess: Annotated[
        PreprocessProfile,
        typer.Option(
            help="legacy: binary 2x; native: original color; bounded: scaled color"
        ),
    ] = PreprocessProfile.legacy,
    ocr_scale: Annotated[
        float, typer.Option(min=0.1, max=4, help="Scale for bounded preprocessing.")
    ] = 1.0,
    ocr_max_side: Annotated[
        int, typer.Option(min=32, help="Longest side limit for bounded preprocessing.")
    ] = 4000,
    output_extension: Annotated[
        OutputExtension,
        typer.Option("--output-extension", help="Export extension: txt, md or py."),
    ] = OutputExtension.txt,
    prepare_review: Annotated[
        bool,
        typer.Option(help="Save original frames and evidence for later LLM review."),
    ] = False,
) -> None:
    """Extract the source code shown in a screen-recording video."""
    if not video.exists():
        fail(f"video not found: [cyan]{video}[/cyan]")
    if not video.is_file():
        fail(f"video path is not a file: [cyan]{video}[/cyan]")

    crop = CropBox(left=crop_left, top=crop_top, right=crop_right, bottom=crop_bottom)
    preprocessing = PreprocessConfig(
        profile=preprocess, scale=ocr_scale, max_side=ocr_max_side
    )

    frames_dir = prepare_output_tree(output)

    metadata = get_video_metadata(video)
    console.print(
        f"[green]Video:[/green] {metadata.width}x{metadata.height} @ "
        f"{metadata.fps:g} fps, {metadata.duration_seconds:g}s, "
        f"{metadata.total_frames} frames "
        f"(codec: {metadata.codec or 'unknown'}, source: {metadata.source})"
    )
    step = adaptive_sample_step(metadata.fps)
    try:
        crop.validate_against(metadata.width, metadata.height)
        parameters = resolve_extraction_parameters(
            engine=engine_name,
            crop=crop,
            metadata=metadata,
            start_time=start_time,
            end_time=end_time,
            step=step,
        )
    except InvalidExtractionParameterError as exc:
        fail(str(exc))
    segment_end = parameters.effective_end_time or "video_end_unknown"
    parameters.preprocessing = preprocessing
    parameters.output_extension = output_extension
    parameters.prepare_review = prepare_review
    metadata = metadata.model_copy(
        update={
            "sampling_strategy": (
                f"adaptive_fps={round(metadata.fps)},step={step},"
                f"segment={parameters.effective_start_time}-{segment_end}"
            )
        }
    )
    console.print(
        f"[green]Sampling:[/green] {metadata.sampling_strategy} "
        f"(~{parameters.expected_candidate_frames} candidate frames)"
    )
    first_label = (
        "none"
        if parameters.first_candidate_frame is None
        else parameters.first_candidate_frame
    )
    last_label = (
        "none"
        if parameters.last_candidate_frame is None
        else parameters.last_candidate_frame
    )
    console.print(
        f"[green]Segment:[/green] frames {first_label}->{last_label} "
        "on the original video timeline"
    )
    write_metadata(metadata, output)
    write_extraction_parameters(parameters, output)

    if parameters.expected_candidate_frames == 0:
        _bail_with_report(
            video=video,
            metadata=metadata,
            parameters=parameters,
            rows=[],
            stats=SelectionStats(),
            outcomes=[],
            output=output,
            message=(
                "the selected segment contains no frame timestamps to sample. "
                "Choose a wider interval or align the segment to visible video "
                "frames."
            ),
        )

    try:
        engine = create_ocr_engine(engine_name)
    except OCREngineUnavailableError as exc:
        fail(str(exc))

    frames = sample_frames(video, metadata, parameters)
    rows, stats, outcomes = run_ocr(
        frames,
        engine,
        frames_dir,
        parameters.expected_candidate_frames,
        crop,
        preprocessing,
        prepare_review,
    )
    console.print(
        f"[green]Selection:[/green] {stats.frames_sampled} frames sampled, "
        f"{stats.frames_kept} kept, {stats.frames_discarded_blurry} discarded "
        f"as blurry, {stats.frames_discarded_duplicate} as near-duplicate"
    )
    if not rows:
        _bail_with_report(
            video=video,
            metadata=metadata,
            parameters=parameters,
            rows=rows,
            stats=stats,
            outcomes=outcomes,
            output=output,
            message=(
                "every sampled frame was discarded by selection "
                f"({stats.frames_discarded_blurry} blurry, "
                f"{stats.frames_discarded_duplicate} near-duplicate) — nothing "
                "to OCR. Inspect ocr_raw.csv, codigo_extraido.txt, and "
                "relatorio_falhas.md, then check the crop region and video "
                "quality."
            ),
        )
    reads = parse_code_lines(rows)
    if not reads:
        _bail_with_report(
            video=video,
            metadata=metadata,
            parameters=parameters,
            rows=rows,
            stats=stats,
            outcomes=outcomes,
            output=output,
            message=(
                f"OCR ran on {len(rows)} frame(s) but recognized no text in any "
                "of them. Inspect "
                f"[cyan]{output / 'ocr_raw.csv'}[/cyan], "
                f"[cyan]{output / 'codigo_extraido.txt'}[/cyan], "
                f"[cyan]{output / 'relatorio_falhas.md'}[/cyan], and the frames "
                f"in [cyan]{frames_dir}[/cyan]. "
                "Check that the crop region contains the code, and consider a "
                "larger editor font, a higher recording resolution, or a "
                "high-contrast editor theme."
            ),
        )
    numbered = has_line_numbers(reads)
    uncertain_confidence = uncertain_confidence_for(engine_name)
    reads_without_number = 0
    if numbered:
        reads_without_number = sum(1 for read in reads if read.line_number is None)
        merged = merge_ocr_results(reads, uncertain_confidence=uncertain_confidence)
        path_taken = "line numbers detected — merged by line number"
    else:
        reads = parse_code_lines(rows, strip_line_numbers=False)
        merged = reconstruct_by_time(reads, uncertain_confidence=uncertain_confidence)
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
        reads_without_line_number=reads_without_number,
        missing_lines=missing,
        uncertain_lines=[item for item in merged if item.uncertain],
        unextractable=unextractable_sections(outcomes),
    )
    write_outputs(metadata, parameters, rows, merged, report, output)

    console.print(
        f"[green]Report:[/green] {len(missing)} missing lines, "
        f"{uncertain} uncertain, {len(report.unextractable)} unextractable "
        f"spans -> [cyan]{output / 'relatorio_falhas.md'}[/cyan]"
    )
    non_empty = sum(1 for row in rows if row.text)
    if output_extension != OutputExtension.txt:
        console.print(f"Export: {output / f'codigo_extraido.{output_extension.value}'}")
    if prepare_review:
        console.print(f"Review evidence: {output / 'review_manifest.json'}")
    console.print(
        f"[green]Done:[/green] {len(rows)} frames OCR'd ({non_empty} with "
        f"text). Outputs in [cyan]{output}[/cyan]: codigo_extraido.txt, "
        "relatorio_falhas.md, ocr_raw.csv, metadata_video.json, "
        "extraction_parameters.json, frames_usados/"
    )
