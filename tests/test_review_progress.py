"""Review timings follow real operation boundaries without paid calls."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clip_ui.runner import ClipJob, JobManager
from clip_ui.settings import ClipSettings
from review_ocr import app
from tests.test_review import fixture_manifest
from tests.test_review_workflow import FakeClient, config, response
from video_ocr.review_plan import plan_review
from video_ocr.review_progress import PREFIX, phase, progress_session
from video_ocr.review_run import run_review


def events(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len(PREFIX) :])
        for line in text.splitlines()
        if line.startswith(PREFIX)
    ]


def test_durations_use_monotonic_clock_and_finish_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLIP_REVIEW_PROGRESS", "1")
    clock = [10.0]
    monkeypatch.setattr("video_ocr.review_progress.time.monotonic", lambda: clock[0])
    with pytest.raises(ValueError), progress_session():
        phase("Preparando", block="1/2")
        clock[0] = 12.5
        phase("Aguardando resposta")
        clock[0] = 25.0
        raise ValueError("failed")
    records = events(capsys.readouterr().out)
    assert [r["state"] for r in records] == [
        "running",
        "completed",
        "running",
        "failed",
    ]
    assert records[1]["duration_seconds"] == 2.5
    assert records[3]["duration_seconds"] == 12.5
    assert all("1/2" in r["label"] for r in records)
    phase("Outside session")
    assert not capsys.readouterr().out


def test_normal_cli_is_unchanged_and_dry_run_is_labeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_manifest(tmp_path)
    monkeypatch.delenv("CLIP_REVIEW_PROGRESS", raising=False)
    args = ["--extraction", str(tmp_path), "--dry-run"]
    ordinary = CliRunner().invoke(app, args)
    assert ordinary.exit_code == 0
    assert PREFIX not in ordinary.output
    monkeypatch.setenv("CLIP_REVIEW_PROGRESS", "1")
    observed = CliRunner().invoke(app, args)
    assert observed.exit_code == 0
    records = events(observed.output)
    assert records and all("Pré-verificação" in r["label"] for r in records)
    assert records[-1]["state"] == "completed"
    assert not any("Aguardando" in r["label"] for r in records)


@pytest.mark.parametrize("incomplete", [False, True])
def test_real_review_boundaries_with_simulated_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    incomplete: bool,
) -> None:
    monkeypatch.setenv("CLIP_REVIEW_PROGRESS", "1")
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    fake = FakeClient([response(status="incomplete") if incomplete else response()])
    output = tmp_path / "review"
    try:
        with progress_session():
            run_review(
                tmp_path, output, original, extension, blocks, plan, lambda: fake
            )
    except ValueError:
        assert incomplete
    records = events(capsys.readouterr().out)
    started = [r["label"] for r in records if r["state"] == "running"]
    waiting = next(i for i, label in enumerate(started) if "Aguardando" in label)
    received = next(
        i for i, label in enumerate(started) if "Resposta recebida" in label
    )
    validating = next(
        i for i, label in enumerate(started) if "Validando resposta" in label
    )
    assert waiting < received < validating
    assert "bloco 1/1" in started[waiting]
    assert fake.calls == 1
    assert records[-1]["state"] == ("failed" if incomplete else "completed")
    assert (output / "responses/block_0001/attempt_0001.json").exists()
    assert (output / "codigo_revisado.py").exists() is not incomplete
    assert all(r["duration_seconds"] >= 0 for r in records if r["state"] != "running")


def test_worker_drains_and_decodes_subprocess_events(tmp_path: Path) -> None:
    manager = JobManager()
    clip = ClipJob(
        settings=ClipSettings(video=tmp_path / "x.mp4"),
        stages=[],
        extraction="",
        review="",
    )
    source = (
        "from video_ocr.review_progress import progress_session, phase\n"
        "with progress_session():\n"
        " phase('Preparing')\n"
        " phase('Waiting', block='1/1')\n"
    )
    try:
        code = manager._execute([sys.executable, "-u", "-c", source], clip)
        assert code == 0
        assert [s.state for s in clip.review_steps] == ["completed", "completed"]
        assert all(s.duration_seconds is not None for s in clip.review_steps)
        assert not any(PREFIX in line for line in clip.logs)
    finally:
        manager.close()
