"""Local HTTP surface for the clip workbench."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from clip_ui.runner import JobManager
from clip_ui.settings import ROOT, BatchRequest, ClipSettings, destinations, inventory
from video_ocr.models import EngineName, OutputExtension


def create_app(manager: JobManager | None = None) -> FastAPI:
    jobs = manager or JobManager()
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.close()

    app = FastAPI(title="Bancada de clips", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_requests(request: Request, call_next: Any) -> Any:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin != expected:
            return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
        if request.method == "POST" and request.headers.get("x-clip-token") != token:
            return JSONResponse(
                {"detail": "Recarregue a página antes de executar."}, status_code=403
            )
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(OSError)
    async def os_error(request: Request, exc: OSError) -> JSONResponse:
        return JSONResponse(
            {"detail": f"Não foi possível acessar o caminho: {exc}"}, status_code=400
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(ROOT / "clip_ui/static/index.html")

    @app.get("/api/config")
    def config() -> dict[str, object]:
        return {
            "token": token,
            "root": str(ROOT),
            "engines": [engine.value for engine in EngineName],
            "extensions": [extension.value for extension in OutputExtension],
        }

    @app.get("/api/folders")
    def folders(path: str = str(ROOT)) -> dict[str, object]:
        current = Path(path).expanduser().resolve()
        if not current.is_dir():
            raise HTTPException(400, "Pasta não encontrada.")
        children = sorted(
            (p for p in current.iterdir() if p.is_dir()),
            key=lambda p: p.name.casefold(),
        )
        return {
            "path": str(current),
            "parent": str(current.parent),
            "folders": [{"name": p.name, "path": str(p)} for p in children],
        }

    @app.get("/api/clips")
    def clips(folder: str, output_base: str | None = None) -> list[dict[str, Any]]:
        return [
            clip.model_dump(mode="json")
            for clip in inventory(
                Path(folder), Path(output_base) if output_base else None
            )
        ]

    @app.post("/api/paths")
    def paths(settings: ClipSettings) -> dict[str, Any]:
        return destinations(settings).model_dump(mode="json")

    @app.get("/api/jobs")
    def job_list() -> list[dict[str, object]]:
        return jobs.snapshot()

    @app.post("/api/jobs", status_code=202)
    def submit(request: BatchRequest) -> dict[str, str]:
        return {"id": jobs.submit(request)}

    app.mount("/static", StaticFiles(directory=ROOT / "clip_ui/static"), name="static")
    return app
