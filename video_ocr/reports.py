"""Reports for local video OCR."""

import shutil
from pathlib import Path
from typing import (
    NoReturn,
)

from video_ocr.models import (
    BLURRY_SHARE_WARNING,
    CAPTURE_RECOMMENDATIONS,
    RUN_ARTIFACT_FILENAMES,
    ExtractionParameters,
    FailureReport,
    FrameOutcome,
    LineRead,
    MergedLine,
    OCRRow,
    SelectionStats,
    VideoMetadata,
    _format_time,
    _require_pandas,
    fail,
)
from video_ocr.reconstruction import (
    _missing_line_entries,
    _uncertain_entry,
    unextractable_sections,
)


def _write_text_file(path: Path, content: str) -> None:
    """Write a text output file, naming the path on permission failures."""
    try:
        path.write_text(content, "utf-8")
    except OSError as exc:
        fail(f"cannot write output file [cyan]{path}[/cyan]: {exc}")


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
        lines.append(
            "- Leituras sem número de linha detectável (excluídas da "
            "reconstrução numerada; texto bruto preservado em `ocr_raw.csv`): "
            f"{report.reads_without_line_number}"
        )
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
            lines += _missing_line_entries(report.missing_lines)
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
            "descartados por baixa nitidez ou com OCR vazio)."
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


def _clear_stale_artifacts(output: Path) -> None:
    """Remove the previous run's output files so the tree is run-scoped."""
    for name in RUN_ARTIFACT_FILENAMES:
        stale = output / name
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            fail(f"cannot remove stale output file [cyan]{stale}[/cyan]: {exc}")


def _clear_frames_dir(frames_dir: Path) -> None:
    """Remove stale frame artifacts so `frames_usados/` is run-scoped."""
    for child in frames_dir.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            fail(f"cannot remove stale frame artifact [cyan]{child}[/cyan]: {exc}")


def prepare_output_tree(output: Path) -> Path:
    """Create the output tree, verify writability, and clear stale artifacts."""
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(f"cannot create output directory [cyan]{output}[/cyan]: {exc}")
    if not output.is_dir():
        fail(f"output path is not a directory: [cyan]{output}[/cyan]")

    frames_dir = output / "frames_usados"
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(f"cannot create frames directory [cyan]{frames_dir}[/cyan]: {exc}")

    probe = output / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        fail(f"output directory [cyan]{output}[/cyan] is not writable: {exc}")

    _clear_stale_artifacts(output)
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
        fail(f"cannot write output file [cyan]{csv_path}[/cyan]: {exc}")


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

    The pandas-backed CSV is written last so that a missing-pandas failure
    still leaves the human-readable code and report on disk (and, on bail
    paths, does not mask the actionable error).
    """
    write_metadata(metadata, output)
    write_extraction_parameters(parameters, output)
    write_extracted_code(merged, output)
    write_failure_report(report, output)
    write_ocr_raw(rows, output)


def _bail_with_report(
    *,
    video: Path,
    metadata: VideoMetadata,
    parameters: ExtractionParameters,
    rows: list[OCRRow],
    stats: SelectionStats,
    outcomes: list[FrameOutcome],
    output: Path,
    message: str,
) -> NoReturn:
    """Write inspectable artifacts for a run with no extracted lines, then fail."""
    report = FailureReport(
        video_path=str(video),
        metadata=metadata,
        stats=stats,
        lines_extracted=0,
        line_numbers_detected=False,
        unextractable=unextractable_sections(outcomes),
    )
    write_outputs(metadata, parameters, rows, [], report, output)
    fail(message)
