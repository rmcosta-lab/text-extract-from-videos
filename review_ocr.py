"""Review an extracted file and its frames through the OpenAI Responses API."""

import os
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from video_ocr.review_plan import plan_review
from video_ocr.review_report import report_only as generate_report
from video_ocr.review_run import run_review
from video_ocr.review_storage import read_json

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    extraction: Annotated[
        Path, typer.Option(help="Directory produced with --prepare-review.")
    ],
    model: Annotated[str | None, typer.Option(envvar="OPENAI_REVIEW_MODEL")] = None,
    reasoning_effort: Annotated[
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None,
        typer.Option("--reasoning-effort", envvar="OPENAI_REVIEW_REASONING"),
    ] = None,
    output: Path | None = None,
    dry_run: bool = False,
    system_certs: bool = False,
    max_frames: Annotated[
        int | None,
        typer.Option(
            min=1,
            help="Optional frame count limit; default includes all selected frames. "
            "The 25 MB image limit still applies.",
        ),
    ] = None,
    max_output_tokens: Annotated[
        int, typer.Option(min=100, max=64000, envvar="OPENAI_REVIEW_MAX_OUTPUT_TOKENS")
    ] = 12000,
    image_detail: Literal["high", "original"] = "high",
    chunk_lines: Annotated[int | None, typer.Option(min=1)] = None,
    context_lines: Annotated[int, typer.Option(min=0)] = 10,
    frame_selection: Literal["all", "coverage"] = "all",
    resume: bool = False,
    reapply: bool = False,
    report_only: bool = False,
) -> None:
    """Send OCR text + cropped original frames, then save reviewed copy and diff.

    This command uses the paid OpenAI API. --dry-run validates locally without
    sending data or requiring a key. Model must support images and structured output.
    """
    try:
        if sum((resume, reapply, report_only)) > 1:
            raise ValueError("Choose only one of --resume, --reapply, --report-only")
        destination = output or extraction / "revisao"
        if report_only:
            if dry_run:
                raise ValueError("--report-only cannot be combined with --dry-run")
            generate_report(extraction, destination)
            typer.echo(f"Report saved in {destination}. No API call made.")
            return
        config = {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "max_frames": max_frames,
            "max_output_tokens": max_output_tokens,
            "image_detail": image_detail,
            "chunk_lines": chunk_lines,
            "context_lines": context_lines,
            "frame_selection": frame_selection,
        }
        if reapply:
            config = read_json(destination / "review_run.json")["plan"]["configuration"]
        original, extension, blocks, plan = plan_review(
            extraction / "review_manifest.json", config
        )
        typer.echo(
            f"Review: {len(blocks)} block(s), {len(original)} text characters. "
            f"Output: {destination}"
        )
        typer.echo(
            f"Model: {config['model'] or 'unset'}; "
            f"reasoning: {config['reasoning_effort'] or 'default'}; "
            f"max output tokens: {config['max_output_tokens']} per call"
        )
        for block in blocks:
            typer.echo(
                f"Block {block.number}: lines {block.start}..{block.end}, "
                f"context {block.context_start}..{block.context_end}; "
                f"frames {sorted(block.frames)}; "
                f"{block.audit['image_bytes']} image bytes"
            )
            fallback = block.audit["selection"].get("fallback")
            if fallback:
                typer.echo(f"  Selection: {fallback}")
        if dry_run:
            typer.echo("Local validation passed. No API call made.")
            return
        if reapply:
            review = run_review(
                extraction, destination, original, extension, blocks, plan, reapply=True
            )
            typer.echo(f"Reapplied {len(review.edits)} edits. No API call made.")
            return
        if not model:
            raise ValueError("Specify --model or OPENAI_REVIEW_MODEL")

        def client_factory() -> Any:
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise ValueError(
                    "Missing OPENAI_API_KEY; use uv run --env-file .env.local"
                )
            try:
                if system_certs:
                    import_module("truststore").inject_into_ssl()
                sdk = import_module("openai")
            except ImportError as exc:
                raise ValueError(
                    "Install review dependencies: uv sync --group review"
                ) from exc
            return sdk.OpenAI(timeout=300, max_retries=0)

        try:
            review = run_review(
                extraction,
                destination,
                original,
                extension,
                blocks,
                plan,
                client_factory,
                resume=resume,
            )
        except Exception as exc:
            # SDK errors may include request/response text. Keep terminal output safe.
            if type(exc).__module__.startswith("openai"):
                raise ValueError(
                    f"OpenAI request failed: {type(exc).__name__}; "
                    f"HTTP {getattr(exc, 'status_code', 'unknown')}. "
                    "Use --resume with the same configuration."
                ) from None
            raise
        typer.echo(
            f"Saved {len(review.edits)} proposed edits, "
            f"{len(review.unresolved)} unresolved issues and a diff in {destination}"
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
