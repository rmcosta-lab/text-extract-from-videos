"""Launch the local clip UI without changing the existing command entrypoints."""

from typing import Annotated

import typer
import uvicorn

from clip_ui.server import create_app

app = typer.Typer(add_completion=False)


@app.command()
def main(port: Annotated[int, typer.Option(min=1024, max=65535)] = 8770) -> None:
    """Open http://127.0.0.1:8770 after starting the workbench."""
    typer.echo(f"Bancada de clips: http://127.0.0.1:{port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
