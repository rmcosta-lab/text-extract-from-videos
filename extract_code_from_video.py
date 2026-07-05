"""Extract the source code shown in a screen-recording video via local OCR.

Phase 0 skeleton: validates inputs and creates the output directory tree.
The extraction pipeline (frame sampling, OCR, reconstruction, reports)
arrives in later phases.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console()
err_console = Console(stderr=True)


def _fail(message: str) -> None:
    """Print a styled error message and exit with status 1."""
    err_console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=1)


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
        int | None,
        typer.Option(help="Pixels to crop from the left edge (Phase 2)."),
    ] = None,
    crop_top: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the top edge (Phase 2)."),
    ] = None,
    crop_right: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the right edge (Phase 2)."),
    ] = None,
    crop_bottom: Annotated[
        int | None,
        typer.Option(help="Pixels to crop from the bottom edge (Phase 2)."),
    ] = None,
) -> None:
    """Extract the source code shown in a screen-recording video."""
    if not video.exists():
        _fail(f"video not found: [cyan]{video}[/cyan]")
    if not video.is_file():
        _fail(f"video path is not a file: [cyan]{video}[/cyan]")

    frames_dir = output / "frames_usados"
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(f"cannot create output directory [cyan]{output}[/cyan]: {exc}")

    probe = output / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        _fail(f"output directory [cyan]{output}[/cyan] is not writable: {exc}")

    console.print(f"[green]Output tree created:[/green] [cyan]{output}[/cyan]")
    console.print(f"  [cyan]{frames_dir}[/cyan]")
    console.print(
        "[yellow]Extraction pipeline is not implemented yet[/yellow] "
        "(arrives in Phase 1); no code was extracted."
    )


if __name__ == "__main__":
    app()
