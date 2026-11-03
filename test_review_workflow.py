"""Durability, block ownership, offline recovery and evidence coverage."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from review_ocr import app
from test_review import fixture_manifest, result
from video_ocr.review import ReviewResult, request_review
from video_ocr.review_plan import plan_review, select_frames
from video_ocr.review_quality import ReviewReference, ReviewReferenceLine, score_review
from video_ocr.review_report import line_mapping, report_only
from video_ocr.review_run import run_review, validate_block
from video_ocr.review_storage import atomic_json, read_json


def config(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        model="test",
        reasoning_effort="high",
        max_frames=12,
        max_output_tokens=12000,
        image_detail="high",
        chunk_lines=None,
        context_lines=10,
        frame_selection="all",
    )
    values.update(changes)
    return values


def response(review: ReviewResult | None = None, **changes: Any) -> SimpleNamespace:
    values: dict[str, Any] = dict(
        status="completed",
        output_text=(review or result()).model_dump_json(),
        output=[],
        id="test-id",
        model="test",
        usage=None,
    )
    values.update(changes)
    return SimpleNamespace(**values)


class FakeClient:
    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.calls = 0
        self.responses = self

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def create(self, **kwargs: Any) -> Any:
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("kind", ["truncated", "refused", "invalid_edit"])
def test_response_saved_before_failure(tmp_path: Path, kind: str) -> None:
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    value = response(result(before="mismatch"))
    if kind == "truncated":
        value = response(
            status="incomplete",
            output_text='{"summary": "cut',
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
    if kind == "refused":
        value = response(
            output_text="",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="refusal", refusal="Cannot review")],
                )
            ],
        )
    client = FakeClient([value])
    output = tmp_path / "run"
    with pytest.raises(ValueError):
        run_review(tmp_path, output, original, extension, blocks, plan, lambda: client)
    saved = read_json(output / "responses/block_0001/attempt_0001.json")
    assert saved["output_text"] == value.output_text
    assert saved["audit"]["response_id"] == "test-id"
    assert "image_url" not in json.dumps(saved)
    assert not (output / "codigo_revisado.py").exists()
    assert read_json(output / "review_run.json")["status"] == "failed"
    with pytest.raises(ValueError):
        run_review(tmp_path, output, original, extension, blocks, plan, reapply=True)
    assert client.calls == 1


def test_reapply_recovers_after_response_before_state_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    output = tmp_path / "run"
    atomic_json(
        output / "review_run.json",
        {"schema_version": 1, "status": "running", "plan": plan, "blocks": {}},
    )

    def persist(record: dict[str, Any]) -> None:
        record.update(plan_sha256=plan["plan_sha256"], block_number=1)
        atomic_json(output / "responses/block_0001/attempt_0001.json", record)

    request_review(FakeClient([response()]), "test", [], 12000, "high", persist)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "review_ocr.import_module", lambda _: pytest.fail("SDK imported")
    )
    invoked = CliRunner().invoke(
        app, ["--extraction", str(tmp_path), "--output", str(output), "--reapply"]
    )
    assert invoked.exit_code == 0, invoked.output
    assert (output / "codigo_revisado.py").read_text() == "x = 1\n"
    assert read_json(output / "review_run.json")["status"] == "completed"
    with pytest.raises(ValueError, match="exists"):
        run_review(tmp_path, output, original, extension, blocks, plan, reapply=True)


def test_resume_only_failed_block(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path)
    for suffix in ("txt", "py"):
        (tmp_path / f"codigo_extraido.{suffix}").write_text("x = l\ny = l\n")
    original, extension, blocks, plan = plan_review(manifest, config(chunk_lines=1))
    client = FakeClient(
        [
            response(),
            OSError("network"),
            response(result(start_line=2, end_line=2, before="y = l", after="y = 1")),
        ]
    )
    output = tmp_path / "run"
    with pytest.raises(OSError):
        run_review(tmp_path, output, original, extension, blocks, plan, lambda: client)
    assert not (output / "revisao.json").exists()
    combined = run_review(
        tmp_path, output, original, extension, blocks, plan, lambda: client, resume=True
    )
    assert client.calls == 3
    assert len(combined.edits) == 2
    assert len(list((output / "responses/block_0001").glob("*.json"))) == 1


@pytest.mark.parametrize("change", ["config", "source", "image"])
def test_resume_rejects_changed_inputs(tmp_path: Path, change: str) -> None:
    manifest = fixture_manifest(tmp_path)
    settings = config()
    original, extension, blocks, plan = plan_review(manifest, settings)
    output = tmp_path / "run"
    with pytest.raises(OSError):
        run_review(
            tmp_path,
            output,
            original,
            extension,
            blocks,
            plan,
            lambda: FakeClient([OSError("offline")]),
        )
    if change == "config":
        settings = config(max_output_tokens=32000)
    elif change == "source":
        for suffix in ("txt", "py"):
            (tmp_path / f"codigo_extraido.{suffix}").write_text("changed\n")
    else:
        from PIL import Image  # noqa: PLC0415

        Image.new("RGB", (100, 200), "red").save(tmp_path / "frame.png")
    original, extension, blocks, plan = plan_review(manifest, settings)
    with pytest.raises(ValueError, match="hashes changed"):
        run_review(tmp_path, output, original, extension, blocks, plan, resume=True)


def test_block_boundaries_and_preflight(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path)
    for suffix in ("txt", "py"):
        (tmp_path / f"codigo_extraido.{suffix}").write_text("x = l\ny = l\n")
    original, _, blocks, _ = plan_review(manifest, config(chunk_lines=1))
    payload = json.loads(blocks[1].content[0]["text"])
    assert payload["numbered_file"][1]["line"] == 2
    assert payload["editable_lines"] == [2, 2]
    with pytest.raises(ValueError, match="boundary"):
        validate_block(
            original, result(end_line=2, before=original.rstrip()), blocks[0]
        )
    with pytest.raises(ValueError, match="frames"):
        plan_review(manifest, config(max_frames=0))


def test_mapping_and_report_links(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    output = tmp_path / "run"
    run_review(
        tmp_path,
        output,
        original,
        extension,
        blocks,
        plan,
        lambda: FakeClient([response(result(after="x = 1\nprint(x)"))]),
    )
    mapping = read_json(output / "line_mapping.json")
    assert mapping[0]["revised"] == [1, 2]
    assert mapping[0]["kind"] == "replacement"
    report_only(tmp_path, output)
    assert "../frame.png" in (output / "relatorio_revisao.md").read_text(
        encoding="utf-8"
    )
    (tmp_path / "codigo_extraido.txt").write_text("modified")
    with pytest.raises(ValueError, match="hash"):
        report_only(tmp_path, output)
    review = result(after="")
    assert line_mapping("x = l\nnext\n", review) == [
        {"original": 1, "revised": None, "kind": "removed"},
        {"original": 2, "revised": [1, 1], "kind": "unchanged"},
    ]


def test_coverage_retains_alternatives_and_best_sharpness() -> None:
    frames = []
    for index, content, sharpness in (
        (1, "x = 1", 5),
        (2, "x = l", 7),
        (3, "x = l", 10),
        (4, "other", 20),
    ):
        number = 2 if index == 4 else 1
        frames.append(
            {
                "frame_number": index,
                "ocr": {
                    "text": f"{number} {content}",
                    "frame_number": index,
                    "time_seconds": 0,
                    "time_formatted": "0",
                    "sharpness": sharpness,
                    "frame_image_path": "unused",
                    "lines": [{"text": f"{number} {content}"}],
                },
            }
        )
    manifest = {
        "frames": frames,
        "lines": [
            {"output_line": 1, "frame_number": 1, "content": "x = 1", "line_number": 1}
        ],
    }
    selected, audit = select_frames(manifest, ["x = 1"], 1, 1, "coverage", False)
    assert selected == {1, 3}
    assert audit["discarded"] == [2, 4]
    selected, audit = select_frames(manifest, ["missing"], 1, 1, "coverage", False)
    assert selected == {1, 2, 3, 4}
    assert audit["fallback"]


def test_quality_preserves_spaces_and_excludes_partial_replacements() -> None:
    original = 'x = " A "\nnext\n'
    review = result(before='x = " A "', after='x = "A"')
    reference = ReviewReference(
        source_sha256="unused",
        method="test",
        lines=[ReviewReferenceLine(original_line=1, frames=[210], text='x = " A "')],
    )
    evaluation = score_review(
        original, 'x = "A"\nnext\n', line_mapping(original, review), reference
    )
    assert evaluation["metrics"]["regressed_lines"] == 1
    assert evaluation["metrics"]["reviewed"]["cer"] > 0
    spanning = result(end_line=2, before=original.rstrip(), after="replacement")
    evaluation = score_review(
        original, "replacement\n", line_mapping(original, spanning), reference
    )
    assert evaluation["scored_lines"] == 0
    assert evaluation["excluded"]


def test_expanded_replacement_is_not_scored_against_one_reference_line() -> None:
    original = "Title\n"
    review = result(before="Title", after="Title\nRestored neighbor")
    reference = ReviewReference(
        source_sha256="unused",
        method="test",
        lines=[ReviewReferenceLine(original_line=1, frames=[210], text="Title")],
    )
    evaluation = score_review(
        original,
        "Title\nRestored neighbor\n",
        line_mapping(original, review),
        reference,
    )
    assert evaluation["scored_lines"] == 0
    assert "line count" in evaluation["excluded"][0]["reason"]


def test_resume_retains_failed_response_attempt(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    client = FakeClient([response(result(before="invalid")), response()])
    output = tmp_path / "run"
    with pytest.raises(ValueError):
        run_review(tmp_path, output, original, extension, blocks, plan, lambda: client)
    run_review(
        tmp_path, output, original, extension, blocks, plan, lambda: client, resume=True
    )
    assert client.calls == 2
    assert len(list((output / "responses/block_0001").glob("*.json"))) == 2


def test_publication_failure_can_be_reapplied_without_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = fixture_manifest(tmp_path)
    original, extension, blocks, plan = plan_review(manifest, config())
    output = tmp_path / "run"
    replace = Path.replace

    def interrupted(path: Path, destination: Any) -> Path:
        if destination == output / "comparativo.diff":
            raise OSError("publication interrupted")
        return replace(path, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupted)
        with pytest.raises(OSError, match="publication"):
            run_review(
                tmp_path,
                output,
                original,
                extension,
                blocks,
                plan,
                lambda: FakeClient([response()]),
            )
    assert not (output / "codigo_revisado.py").exists()
    run_review(tmp_path, output, original, extension, blocks, plan, reapply=True)
    assert (output / "codigo_revisado.py").exists()


def test_plan_checks_later_blocks_before_client_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_manifest(tmp_path)
    for suffix in ("txt", "py"):
        (tmp_path / f"codigo_extraido.{suffix}").write_text("x = l\n" + "a" * 100001)
    monkeypatch.setattr(
        "review_ocr.import_module", lambda _: pytest.fail("SDK imported")
    )
    invoked = CliRunner().invoke(
        app,
        ["--extraction", str(tmp_path), "--chunk-lines", "1", "--context-lines", "0"],
    )
    assert invoked.exit_code == 1
    assert "100000" in invoked.output
    assert not (tmp_path / "revisao").exists()


def test_dry_run_does_not_write_plan(tmp_path: Path) -> None:
    fixture_manifest(tmp_path)
    invoked = CliRunner().invoke(
        app,
        [
            "--extraction",
            str(tmp_path),
            "--dry-run",
            "--chunk-lines",
            "1",
            "--frame-selection",
            "coverage",
        ],
    )
    assert invoked.exit_code == 0, invoked.output
    assert "Block 1" in invoked.output
    assert "No reliable provenance" in invoked.output
    assert not (tmp_path / "revisao").exists()
