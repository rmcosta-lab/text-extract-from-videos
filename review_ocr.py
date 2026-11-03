"""Review an extracted file and its frames through the OpenAI Responses API."""

import os
from importlib import import_module
from pathlib import Path
from typing import Annotated, Literal

import typer

from video_ocr.review import apply_review, prepare_request, request_review, save_review

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
    max_frames: Annotated[int, typer.Option(min=1, max=100)] = 12,
    max_output_tokens: Annotated[
        int, typer.Option(min=100, max=64000, envvar="OPENAI_REVIEW_MAX_OUTPUT_TOKENS")
    ] = 12000,
    image_detail: Literal["high", "original"] = "high",
) -> None:
    """Send OCR text + cropped original frames, then save reviewed copy and diff.

    This command uses the paid OpenAI API. --dry-run validates locally without
    sending data or requiring a key. Model must support images and structured output.
    """
    try:
        original, extension, frame_ids, content, audit = prepare_request(
            extraction / "review_manifest.json", max_frames, image_detail
        )
        destination = output or extraction / "revisao"
        if any(
            (destination / name).exists()
            for name in (
                f"codigo_revisado.{extension.value}",
                "comparativo.diff",
                "revisao.json",
            )
        ):
            raise ValueError("Review output exists; select a new --output directory")
        typer.echo(
            f"Review: {len(frame_ids)} frames, {len(original)} text characters, "
            f"{audit['image_bytes']} image bytes. Output: {destination}"
        )
        typer.echo(
            f"Model: {model or 'unset'}; reasoning: {reasoning_effort or 'default'}; "
            f"max output tokens: {max_output_tokens}"
        )
        if dry_run:
            typer.echo("Local validation passed. No API call made.")
            return
        if not model:
            raise ValueError("Specify --model or OPENAI_REVIEW_MODEL")
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("Missing OPENAI_API_KEY; use uv run --env-file .env.local")
        try:
            if system_certs:
                import_module("truststore").inject_into_ssl()
            sdk = import_module("openai")
        except ImportError as exc:
            raise ValueError(
                "Install review dependencies: uv sync --group review"
            ) from exc
        try:
            with sdk.OpenAI(timeout=300, max_retries=0) as client:
                review, response_audit = request_review(
                    client, model, content, max_output_tokens, reasoning_effort
                )
        except sdk.APIError as exc:
            # Avoid dumping request contents or credentials in API error logs.
            raise ValueError(
                f"OpenAI request failed: {type(exc).__name__}; "
                f"HTTP {getattr(exc, 'status_code', 'unknown')}"
            ) from None
        corrected = apply_review(original, review, frame_ids)
        audit.update(response_audit)
        save_review(destination, original, corrected, extension, review, audit)
        typer.echo(
            f"Saved {len(review.edits)} proposed edits, "
            f"{len(review.unresolved)} unresolved issues and a diff in {destination}"
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
