"""UI contracts: CLI compatibility, preflight, queue dependencies and local HTTP."""

import inspect
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from clip_ui.crop_preview import create_preview
from clip_ui.runner import ClipJob, JobManager, safe_log
from clip_ui.server import create_app
from clip_ui.settings import (
    BatchRequest,
    ClipSettings,
    command,
    destinations,
    inventory,
    parse_crop,
    validate_video,
)
from review_ocr import app
from review_ocr import main as review_main
from suggest_crop import main as crop_main
from tests.test_review import fixture_manifest
from tests.test_review_workflow import FakeClient, response
from video_ocr.cli import main as extract_main
from video_ocr.models import (
    EngineName,
    InvalidExtractionParameterError,
    OutputExtension,
    VideoMetadata,
)


def clip(tmp_path: Path, name: str = "clip_006__vector_names.py.mp4") -> ClipSettings:
    folder = tmp_path / "my project" / "clip"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / name
    video.touch()
    return ClipSettings(video=video, extension=OutputExtension.py)


def wait_done(manager: JobManager) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if manager.snapshot()[-1]["done"]:
            return
        time.sleep(0.01)
    pytest.fail("Queue did not finish")


def test_inventory_inference_and_paths(tmp_path: Path) -> None:
    settings = clip(tmp_path)
    for name in (
        "clip_023.mp4",
        "notes.md.MOV",
        "unknown.js.mp4",
        "log.txt.avi",
        "clips.json",
    ):
        (settings.video.parent / name).touch()
    (settings.video.parent / "directory.mp4").mkdir()
    found = {entry.name: entry for entry in inventory(settings.video.parent)}
    assert len(found) == 5
    assert found[settings.video.name].extension == OutputExtension.py
    assert found["notes.md.MOV"].extension == OutputExtension.md
    assert found["log.txt.avi"].extension == OutputExtension.txt
    assert not found["unknown.js.mp4"].inferred
    assert not found["clip_023.mp4"].inferred
    paths = destinations(settings)
    assert paths.base == settings.video.parent.parent / "extract"
    assert paths.extraction == paths.base / settings.video.stem / "extract"
    assert paths.review == paths.extraction.parent / "revisao"
    assert not paths.exists
    paths.extraction.mkdir(parents=True)
    assert destinations(settings).exists


def test_override_and_nonconventional_folder(tmp_path: Path) -> None:
    settings = ClipSettings(video=tmp_path / "video.mp4")
    with pytest.raises(ValueError, match="base"):
        destinations(settings)
    settings.output_base = tmp_path / "other output"
    assert (
        destinations(settings).extraction == settings.output_base / "video" / "extract"
    )


@pytest.mark.parametrize(
    "text",
    [
        "--crop-left -1",
        "--crop-left 1 --crop-left 2",
        "--crop-left 1; echo secret",
        "--output x",
        "--crop-top",
        "--crop-left 1.5",
        "left 2",
    ],
)
def test_crop_rejects_untrusted_command_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_crop(text)


def test_command_defaults_and_zero_time(tmp_path: Path) -> None:
    settings = clip(tmp_path)
    settings.start_time = "0"
    settings.crop_text = "--crop-left 20 --crop-bottom 3"
    args = command(settings, "extract")
    assert args[0] == sys.executable
    assert args[args.index("--video") + 1] == str(settings.video)
    assert args[args.index("--engine") + 1] == "paddle"
    assert args[args.index("--start-time") + 1] == "0"
    assert "--end-time" not in args and "--prepare-review" in args
    assert args[args.index("--crop-left") + 1] == "20"
    assert args[args.index("--output-extension") + 1] == "py"
    review = command(settings, "review")
    assert "--engine" not in review and "--start-time" not in review
    assert review[review.index("--image-detail") + 1] == "original"
    assert review[review.index("--max-output-tokens") + 1] == "64000"
    assert "--system-certs" in review
    assert review[review.index("--output") + 1] == str(destinations(settings).review)
    crop = command(settings, "crop", 8777)
    assert "clip_ui.crop_preview" in crop and crop[crop.index("--port") + 1] == "8777"


def test_model_validation() -> None:
    with pytest.raises(ValidationError):
        ClipSettings(video=Path("x.mp4"), start_time="not time")
    with pytest.raises(ValidationError):
        ClipSettings.model_validate({"video": "x.mp4", "extension": "js"})
    assert ClipSettings(video=Path("x.mp4"), start_time=" ").start_time is None


@pytest.mark.parametrize(
    "changes",
    [
        {"end_time": "11"},
        {"start_time": "4", "end_time": "2"},
        {"crop_text": "--crop-left 100"},
        {"start_time": "0.001", "end_time": "0.002"},
    ],
)
def test_preflight_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    settings = clip(tmp_path).model_copy(update=changes)
    metadata = VideoMetadata(
        fps=30,
        duration_seconds=10,
        width=100,
        height=100,
        total_frames=300,
        source="ffprobe",
    )
    monkeypatch.setattr("video_ocr.video.get_video_metadata", lambda _: metadata)
    paths = destinations(settings)
    paths.extraction.mkdir(parents=True)
    sentinel = paths.extraction / "original.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises((ValueError, InvalidExtractionParameterError)):
        validate_video(settings)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "action,expected",
    [
        ("extract", ["extract"]),
        ("review", ["dry-run", "review"]),
        ("combined", ["extract", "dry-run", "review"]),
    ],
)
def test_queue_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: Any, expected: list[str]
) -> None:
    manager = JobManager()
    calls: list[str] = []

    def execute(args: list[str], job: ClipJob) -> int:
        calls.append(
            "dry-run"
            if "--dry-run" in args
            else "review"
            if "review_ocr.py" in args[2]
            else "extract"
        )
        manager.log(job, "live output")
        return 0

    monkeypatch.setattr("clip_ui.runner.validate_video", lambda *a, **kw: None)
    monkeypatch.setattr(manager, "_execute", execute)
    try:
        manager.submit(BatchRequest(action=action, clips=[clip(tmp_path)]))
        wait_done(manager)
        assert calls == expected
        assert all(s.state == "succeeded" for s in manager.jobs[0].clips[0].stages)
        assert "live output" in manager.jobs[0].clips[0].logs
    finally:
        manager.close()


def test_failed_extraction_blocks_stale_review_but_continues_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = JobManager()
    first, second = clip(tmp_path), clip(tmp_path, "second.mp4")
    paths = destinations(first)
    paths.extraction.mkdir(parents=True)
    fixture_manifest(paths.extraction)
    called: list[str] = []

    def execute(args: list[str], job: ClipJob) -> int:
        called.append(job.settings.video.name)
        return 1 if job.settings.video == first.video else 0

    monkeypatch.setattr("clip_ui.runner.validate_video", lambda *a, **kw: None)
    monkeypatch.setattr(manager, "_execute", execute)
    try:
        manager.submit(BatchRequest(action="combined", clips=[first, second]))
        wait_done(manager)
        assert [s.state for s in manager.jobs[0].clips[0].stages] == [
            "failed",
            "blocked",
        ]
        assert called.count(first.video.name) == 1
        assert [s.state for s in manager.jobs[0].clips[1].stages] == [
            "succeeded",
            "succeeded",
        ]
    finally:
        manager.close()


def test_review_missing_manifest_never_makes_paid_call(tmp_path: Path) -> None:
    manager = JobManager()
    try:
        manager.submit(BatchRequest(action="review", clips=[clip(tmp_path)]))
        wait_done(manager)
        stage = manager.jobs[0].clips[0].stages[0]
        assert stage.state == "failed"
        assert "manifesto" in (stage.error or "")
        assert not destinations(manager.jobs[0].clips[0].settings).review.exists()
    finally:
        manager.close()


def test_duplicate_submission_and_live_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = JobManager()
    ready, release = threading.Event(), threading.Event()

    def execute(args: list[str], job: ClipJob) -> int:
        manager.log(job, "first frame")
        ready.set()
        release.wait(10)
        return 0

    monkeypatch.setattr("clip_ui.runner.validate_video", lambda *a, **kw: None)
    monkeypatch.setattr(manager, "_execute", execute)
    request = BatchRequest(action="extract", clips=[clip(tmp_path)])
    try:
        manager.submit(request)
        assert ready.wait(5)
        assert not manager.jobs[0].done
        assert manager.jobs[0].clips[0].stages[0].state == "running"
        assert manager.jobs[0].clips[0].logs == ["first frame"]
        with pytest.raises(ValueError, match="fila"):
            manager.submit(request)
        release.set()
        wait_done(manager)
        with pytest.raises(ValueError, match="mesmo destino"):
            manager.submit(
                BatchRequest(
                    action="extract", clips=[request.clips[0], request.clips[0]]
                )
            )
    finally:
        release.set()
        manager.close()


def test_secret_redaction_and_log_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-private-value")
    assert "test-private-value" not in safe_log("failed test-private-value")
    assert "sk-abc123" not in safe_log("key sk-abc123")
    manager = JobManager()
    job = ClipJob(settings=clip(tmp_path), stages=[], extraction="", review="")
    try:
        for index in range(1100):
            manager.log(job, str(index))
        assert len(job.logs) == 1000 and job.logs[-1] == "1099"
    finally:
        manager.close()


def test_http_local_inventory_paths_and_validation(tmp_path: Path) -> None:
    settings = clip(tmp_path)
    with TestClient(create_app()) as client:
        config = client.get("/api/config").json()
        headers = {"x-clip-token": config["token"]}
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert (
            client.get(
                "/api/clips", params={"folder": str(settings.video.parent)}
            ).json()[0]["extension"]
            == "py"
        )
        assert client.get("/api/folders", params={"path": str(tmp_path)}).json()[
            "folders"
        ]
        assert (
            client.get(
                "/api/clips", params={"folder": str(tmp_path / "missing")}
            ).status_code
            == 400
        )
        assert client.get("/api/clips", params={"folder": str(tmp_path)}).json() == []
        assert (
            client.post("/api/paths", json=settings.model_dump(mode="json")).status_code
            == 403
        )
        assert (
            client.get(
                "/api/config", headers={"origin": "https://foreign.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/config", headers={"host": "foreign.invalid"}).status_code
            == 400
        )
        resolved = client.post(
            "/api/paths", headers=headers, json=settings.model_dump(mode="json")
        )
        assert resolved.json()["review"] == str(destinations(settings).review)
        invalid = settings.model_dump(mode="json") | {"crop_text": "--output x"}
        assert (
            client.post(
                "/api/jobs",
                headers=headers,
                json={"action": "extract", "clips": [invalid]},
            ).status_code
            == 422
        )


def test_direct_cli_defaults_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extract = inspect.signature(extract_main).parameters
    assert extract["engine_name"].default == EngineName.tesseract
    assert extract["prepare_review"].default is False
    assert extract["output_extension"].default == OutputExtension.txt
    review = inspect.signature(review_main).parameters
    assert review["max_output_tokens"].default == 12000
    assert review["image_detail"].default == "high"
    assert review["system_certs"].default is False
    assert (
        inspect.signature(crop_main).parameters["engine"].default
        == EngineName.tesseract
    )


def test_review_adapter_dry_run_real_cli(tmp_path: Path) -> None:
    settings = clip(tmp_path)
    paths = destinations(settings)
    paths.extraction.mkdir(parents=True)
    fixture_manifest(paths.extraction)
    result = CliRunner().invoke(app, [*command(settings, "review")[3:], "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Local validation passed" in result.output
    assert not paths.review.exists()


def test_shutdown_terminates_managed_process(tmp_path: Path) -> None:
    manager = JobManager()
    job = ClipJob(settings=clip(tmp_path), stages=[], extraction="", review="")
    process = manager._spawn(
        [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(120)"],
        job,
    )
    manager.close()
    assert process.poll() is not None


@pytest.mark.parametrize("action", ["review", "combined"])
def test_http_queue_writes_review_with_mocked_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    settings = clip(tmp_path)
    paths = destinations(settings)
    if action == "review":
        paths.extraction.mkdir(parents=True)
        fixture_manifest(paths.extraction)
    fake = FakeClient([response()])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("OPENAI_REVIEW_MODEL", "test")
    monkeypatch.setattr("clip_ui.runner.validate_video", lambda *a, **kw: None)
    monkeypatch.setattr(
        "review_ocr.import_module",
        lambda name: (
            SimpleNamespace(inject_into_ssl=lambda: None)
            if name == "truststore"
            else SimpleNamespace(OpenAI=lambda **kw: fake)
        ),
    )
    manager = JobManager()

    def execute(args: list[str], job: ClipJob) -> int:
        if "extract_code_from_video.py" in args[2]:
            paths.extraction.mkdir(parents=True)
            fixture_manifest(paths.extraction)
            return 0
        result = CliRunner().invoke(app, args[3:])
        manager.log(job, result.output)
        return result.exit_code

    monkeypatch.setattr(manager, "_execute", execute)
    with TestClient(create_app(manager)) as client:
        token = client.get("/api/config").json()["token"]
        result = client.post(
            "/api/jobs",
            headers={"x-clip-token": token},
            json={
                "action": action,
                "clips": [settings.model_dump(mode="json")],
            },
        )
        assert result.status_code == 202
        wait_done(manager)
        assert all(
            stage.state == "succeeded" for stage in manager.jobs[0].clips[0].stages
        )
        assert fake.calls == 1
        assert (paths.extraction / "codigo_extraido.txt").read_text(
            encoding="utf-8"
        ) == "x = l\n"
        assert (paths.review / "codigo_revisado.py").read_text(
            encoding="utf-8"
        ) == "x = 1\n"
        assert (paths.review / "relatorio_revisao.md").exists()


def test_workbench_preview_selects_requested_engine_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def crop_app(video: Path, engine: EngineName, **kwargs: Any) -> FastAPI:
        captured.update(engine=engine, **kwargs)
        return FastAPI()

    monkeypatch.setattr("clip_ui.crop_preview.create_crop_app", crop_app)
    with TestClient(
        create_preview(tmp_path / "x.mp4", EngineName.paddle, "0", "2")
    ) as client:
        html = client.get("/").text
        assert 'value="paddle" selected' in html
        assert 'value="tesseract" selected' not in html
    assert captured == {"engine": EngineName.paddle, "start_time": "0", "end_time": "2"}
