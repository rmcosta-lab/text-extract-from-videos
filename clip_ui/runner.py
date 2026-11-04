"""Bounded parallel clip jobs with observable stages and managed local subprocesses."""

import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from uuid import uuid4

import typer
from pydantic import BaseModel, Field

from clip_ui.settings import (
    ROOT,
    BatchRequest,
    ClipSettings,
    command,
    destinations,
    validate_video,
)
from video_ocr.review_progress import PREFIX

State = Literal["pending", "running", "succeeded", "failed", "blocked"]
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def safe_log(value: str) -> str:
    value = ANSI.sub("", value)
    for name, secret in os.environ.items():
        if (
            any(part in name.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            and len(secret) >= 6
        ):
            value = value.replace(secret, "[redacted]")
    return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", value)[:4000]


class Stage(BaseModel):
    name: str
    state: State = "pending"
    exit_code: int | None = None
    error: str | None = None


class ReviewStep(BaseModel):
    id: str
    label: str
    state: Literal["running", "completed", "failed"]
    started_at: float
    duration_seconds: float | None = None


class ClipJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    settings: ClipSettings
    stages: list[Stage]
    extraction: str
    review: str
    preview_url: str | None = None
    logs: list[str] = Field(default_factory=list)
    review_steps: list[ReviewStep] = Field(default_factory=list)


class BatchJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    action: str
    clips: list[ClipJob]
    done: bool = False
    concurrency: int = 3


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="clip-workflow"
        )
        self.jobs: list[BatchJob] = []
        self.processes: list[subprocess.Popen[str]] = []
        self.readers: list[threading.Thread] = []
        self.process_readers: dict[int, threading.Thread] = {}

    def snapshot(self) -> list[dict[str, object]]:
        with self.lock:
            return [job.model_dump(mode="json") for job in self.jobs]

    def submit(self, request: BatchRequest) -> str:
        with self.lock:
            if self.stop.is_set():
                raise ValueError("O servidor está encerrando.")
            if any(not job.done for job in self.jobs):
                raise ValueError(
                    "Aguarde a fila atual terminar antes de iniciar outra."
                )
            if request.action == "crop" and len(request.clips) != 1:
                raise ValueError("Selecione um único vídeo para sugerir crop.")
            paths = [destinations(clip) for clip in request.clips]
            if len({str(path.extraction).casefold() for path in paths}) != len(paths):
                raise ValueError("Há vídeos selecionados com o mesmo destino de saída.")
            if request.action == "combined" and any(
                not clip.prepare_review for clip in request.clips
            ):
                raise ValueError(
                    "Extração + revisão exige preparar evidências de revisão."
                )
            stages = (
                ["extract", "review"]
                if request.action == "combined"
                else [request.action]
            )
            job = BatchJob(
                action=request.action,
                concurrency=request.concurrency,
                clips=[
                    ClipJob(
                        settings=clip.model_copy(deep=True),
                        stages=[Stage(name=stage) for stage in stages],
                        extraction=str(path.extraction),
                        review=str(path.review),
                    )
                    for clip, path in zip(request.clips, paths, strict=True)
                ],
            )
            self.jobs = [*self.jobs[-19:], job]
            self.pool.submit(self._run, job)
            return job.id

    def log(self, clip: ClipJob, line: str) -> None:
        with self.lock:
            if line.startswith(PREFIX):
                try:
                    step = ReviewStep.model_validate_json(line[len(PREFIX) :])
                except ValueError:
                    pass
                else:
                    for index, previous in enumerate(clip.review_steps):
                        if previous.id == step.id:
                            clip.review_steps[index] = step
                            break
                    else:
                        clip.review_steps.append(step)
                    suffix = (
                        f" — {step.duration_seconds:.2f}s ({step.state})"
                        if step.duration_seconds is not None
                        else ""
                    )
                    line = f"[Revisão] {step.label}{suffix}"
            clip.logs.append(safe_log(line.rstrip()))
            del clip.logs[:-1000]

    def _spawn(self, args: list[str], clip: ClipJob) -> subprocess.Popen[str]:
        with self.lock:
            if self.stop.is_set():
                raise ValueError("Execução interrompida pelo encerramento do servidor.")
            env = dict(
                os.environ,
                PYTHONUNBUFFERED="1",
                PYTHONIOENCODING="utf-8",
                NO_COLOR="1",
                CLIP_REVIEW_PROGRESS="1",
            )
            process = subprocess.Popen(
                args,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            self.processes.append(process)
            self.readers = [reader for reader in self.readers if reader.is_alive()]
            reader = threading.Thread(
                target=self._read, args=(process, clip), daemon=True
            )
            self.readers.append(reader)
            self.process_readers[process.pid] = reader
            reader.start()
            return process

    def _read(self, process: subprocess.Popen[str], clip: ClipJob) -> None:
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                self.log(clip, line)

    def _execute(self, args: list[str], clip: ClipJob) -> int:
        process = self._spawn(args, clip)
        code = process.wait()
        with self.lock:
            reader = self.process_readers.pop(process.pid, None)
        if reader is not None:
            reader.join(timeout=2)
        with self.lock:
            self.processes.remove(process)
        return code

    def _crop(self, clip: ClipJob) -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = self._spawn(command(clip.settings, "crop", port), clip)
        url = f"http://127.0.0.1:{port}/"
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and not self.stop.wait(0.25):
            code = process.poll()
            if code is not None:
                return code or 1
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    if response.status == 200:
                        with self.lock:
                            clip.preview_url = url
                        self.log(
                            clip,
                            "Preview pronto. Use Abrir preview; "
                            "copie o crop para os ajustes.",
                        )
                        return 0
            except (OSError, urllib.error.URLError):
                continue
        stop_process(process)
        raise ValueError(
            "O preview não ficou pronto em 10 minutos ou o servidor foi encerrado."
        )

    def _close_previews(self) -> None:
        # Called only by the single queue worker, before the next job starts.
        with self.lock:
            processes = list(self.processes)
        for process in processes:
            stop_process(process)
            reader = self.process_readers.pop(process.pid, None)
            if reader is not None:
                reader.join(timeout=2)
        with self.lock:
            self.processes.clear()
            for job in self.jobs:
                for clip in job.clips:
                    if clip.preview_url:
                        clip.preview_url = None
                        self.log(
                            clip,
                            "Preview encerrado para liberar recursos "
                            "para a próxima operação.",
                        )

    def _run(self, job: BatchJob) -> None:
        try:
            self._close_previews()
            with ThreadPoolExecutor(
                max_workers=min(job.concurrency, len(job.clips)),
                thread_name_prefix="clip-worker",
            ) as workers:
                futures = [workers.submit(self._run_clip, clip) for clip in job.clips]
                for future in futures:
                    future.result()
        finally:
            with self.lock:
                for clip in job.clips:
                    for stage in clip.stages:
                        if stage.state in {"running", "pending"}:
                            stage.state = "blocked"
                            stage.error = "Execução encerrada antes da conclusão."
                job.done = True

    def _run_clip(self, clip: ClipJob) -> None:
        failed = False
        for stage in clip.stages:
            with self.lock:
                if failed or self.stop.is_set():
                    stage.state = "blocked"
                    stage.error = "Etapa anterior falhou ou servidor encerrado."
                    continue
                stage.state = "running"
            try:
                if stage.name in {"crop", "extract"}:
                    validate_video(clip.settings, crop_preview=stage.name == "crop")
                if stage.name == "review":
                    self.log(clip, "Validando manifesto e evidências localmente…")
                    code = self._execute(
                        [*command(clip.settings, "review"), "--dry-run"], clip
                    )
                    if code:
                        raise ValueError(
                            "Revisão bloqueada: verifique "
                            "manifesto/evidências e os logs."
                        )
                code = (
                    self._crop(clip)
                    if stage.name == "crop"
                    else self._execute(command(clip.settings, stage.name), clip)
                )
                with self.lock:
                    stage.exit_code = code
                    stage.state = "succeeded" if code == 0 else "failed"
                    if code:
                        stage.error = (
                            f"Processo terminou com código {code}; consulte os logs."
                        )
                        if stage.name == "review":
                            recent = "\n".join(clip.logs[-30:]).lower()
                            if "apitimeouterror" in recent:
                                stage.error = (
                                    "Tempo limite da API excedido; consulte os logs."
                                )
                            elif "incomplete" in recent:
                                stage.error = (
                                    "Resposta incompleta; alterações não aplicadas."
                                )
                            elif "openai request failed" in recent:
                                stage.error = (
                                    "Falha na API de revisão; consulte os logs."
                                )
                failed = code != 0
            except (Exception, typer.Exit) as exc:
                failed = True
                error = safe_log(str(exc) or type(exc).__name__)
                self.log(clip, error)
                with self.lock:
                    stage.state = "failed"
                    stage.error = error
            finally:
                if stage.name == "review":
                    with self.lock:
                        for step in clip.review_steps:
                            if step.state == "running":
                                step.state = (
                                    "completed"
                                    if stage.state == "succeeded"
                                    else "failed"
                                )
                                step.duration_seconds = max(
                                    0, time.time() - step.started_at
                                )

    def close(self) -> None:
        with self.lock:
            self.stop.set()
            processes = list(self.processes)
        for process in processes:
            stop_process(process)
        self.pool.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for job in self.jobs:
                if not job.done:
                    for clip in job.clips:
                        for stage in clip.stages:
                            if stage.state == "pending":
                                stage.state = "blocked"
                                stage.error = "Servidor encerrado."
                    job.done = True
        for reader in self.readers:
            reader.join(timeout=2)
