"""Offline comparison of original and reviewed OCR against an anchored reference."""

from pathlib import Path
from typing import Annotated

import typer

from video_ocr.review_quality import evaluate_review

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    extraction: Annotated[Path, typer.Option()],
    review: Annotated[Path, typer.Option()],
    reference: Path = Path("tests/fixtures/casos_de_uso.review.reference.json"),
    output: Path = Path("saida/avaliacao-revisao"),
) -> None:
    try:
        result = evaluate_review(extraction, review, reference, output)
        typer.echo(
            f"Evaluated {result['scored_lines']}/{result['reference_lines']} lines. "
            f"Results in {output}. No API call made."
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
