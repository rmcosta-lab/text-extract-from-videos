"""Workbench-only crop launcher, preserving the standalone preview defaults."""

from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from clip_ui.settings import ROOT
from suggest_crop import create_app as create_crop_app
from video_ocr.models import EngineName

app = typer.Typer(add_completion=False)


def create_preview(
    video: Path, engine: EngineName, start_time: str | None, end_time: str | None
) -> FastAPI:
    preview = create_crop_app(video, engine, start_time=start_time, end_time=end_time)
    page = (ROOT / "crop_preview.html").read_text(encoding="utf-8")
    # The shared static page starts on Tesseract even when the server's default
    # is Paddle. Override only this UI's page, leaving the standalone CLI intact.
    page = page.replace('value="tesseract" selected', 'value="tesseract"')
    page = page.replace(f'value="{engine.value}"', f'value="{engine.value}" selected')
    preview.router.routes = [
        route for route in preview.router.routes if getattr(route, "path", None) != "/"
    ]

    @preview.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

    return preview


@app.command()
def main(
    video: Annotated[Path, typer.Option()],
    engine: EngineName = EngineName.paddle,
    start_time: str | None = None,
    end_time: str | None = None,
    port: int = 8765,
) -> None:
    if engine not in {EngineName.paddle, EngineName.tesseract}:
        raise typer.BadParameter("A sugestão de crop requer PaddleOCR ou Tesseract.")
    uvicorn.run(
        create_preview(video, engine, start_time, end_time),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    app()
