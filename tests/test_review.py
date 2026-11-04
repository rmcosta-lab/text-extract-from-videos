"""Review suggestions are anchored and validated before writing a new file."""

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from typer.testing import CliRunner

from review_ocr import app
from video_ocr.imaging import encode_review_webp
from video_ocr.models import CropBox, OutputExtension
from video_ocr.review import (
    ReviewEdit,
    ReviewResult,
    apply_review,
    prepare_request,
    request_review,
    save_review,
)


def result(**overrides: Any) -> ReviewResult:
    edit: dict[str, Any] = {
        "start_line": 1,
        "end_line": 1,
        "before": "x = l",
        "after": "x = 1",
        "kind": "visual_correction",
        "frames": [210],
        "reason": "Visible numeral",
    }
    edit.update(overrides)
    return ReviewResult(summary="Correction", edits=[ReviewEdit(**edit)], unresolved=[])


def test_valid_edit_keeps_other_lines_and_creates_diff(tmp_path: Path) -> None:
    original = "x = l\nprint(x)\n"
    review = result()
    corrected = apply_review(original, review, {210})
    assert corrected == "x = 1\nprint(x)\n"
    save_review(tmp_path, original, corrected, OutputExtension.py, review, {})
    assert "+x = 1" in (tmp_path / "comparativo.diff").read_text(encoding="utf-8")
    assert not (tmp_path / "codigo_extraido.py").exists()
    with pytest.raises(ValueError, match="exists"):
        save_review(tmp_path, original, corrected, OutputExtension.py, review, {})


@pytest.mark.parametrize(
    "override",
    [
        {"before": "different"},
        {"frames": []},
        {"frames": [999]},
        {"end_line": 3},
        {"kind": "formatting"},
    ],
)
def test_invalid_edits_are_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        apply_review("x = l\n", result(**override), {210})


def test_overlapping_edits_are_rejected() -> None:
    review = result()
    review.edits.append(review.edits[0])
    with pytest.raises(ValueError, match="Overlapping"):
        apply_review("x = l\n", review, {210})


def fixture_manifest(tmp_path: Path) -> Path:
    (tmp_path / "codigo_extraido.txt").write_text("x = l\n", encoding="utf-8")
    (tmp_path / "codigo_extraido.py").write_text("x = l\n", encoding="utf-8")
    Image.new("RGB", (100, 200)).save(tmp_path / "frame.png")
    manifest = {
        "schema_version": 1,
        "parameters": {
            "output_extension": "py",
            "crop": {"left": 10, "top": 20, "right": 10, "bottom": 0},
        },
        "ocr_original": "codigo_extraido.txt",
        "target_file": "codigo_extraido.py",
        "lines": [],
        "frames": [{"frame_number": 210, "original_image": "frame.png"}],
    }
    path = tmp_path / "review_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_dry_run_needs_no_key_and_never_calls_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_manifest(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = CliRunner().invoke(app, ["--extraction", str(tmp_path), "--dry-run"])
    assert response.exit_code == 0, response.output
    assert "No API call" in response.output
    assert not (tmp_path / "revisao").exists()


def test_request_has_images_and_uses_structured_response(tmp_path: Path) -> None:
    original, _, frame_ids, content, _ = prepare_request(fixture_manifest(tmp_path))
    captured: dict[str, Any] = {}

    def create(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            status="completed",
            output_text=result().model_dump_json(),
            output=[],
            id="test",
            model="test-model",
            usage=None,
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    review, audit = request_review(client, "test-model", content, 1000, "high")
    assert captured["store"] is False
    assert captured["reasoning"] == {"effort": "high"}
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"]["additionalProperties"] is False
    assert any(item["type"] == "input_image" for item in content)
    assert apply_review(original, review, frame_ids) == "x = 1\n"
    assert audit["response_id"] == "test"


def test_refusal_never_produces_review() -> None:
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                status="completed", output_text="", output=[]
            )
        )
    )
    with pytest.raises(ValueError, match="refused or incomplete"):
        request_review(client, "test", [], 100)


def test_manifest_cannot_send_files_outside_extraction(tmp_path: Path) -> None:
    path = fixture_manifest(tmp_path)
    data = json.loads(path.read_text())
    data["frames"][0]["original_image"] = "../.env.local"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        prepare_request(path)


def test_frame_limit_does_not_silently_omit_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frames"):
        prepare_request(fixture_manifest(tmp_path), max_frames=0)


@pytest.mark.parametrize(
    "total,selected,limit", [(31, None, 30), (5, {1, 2}, 1), (0, None, 30)]
)
def test_frame_limit_reports_total_and_selected_counts(
    tmp_path: Path, total: int, selected: set[int] | None, limit: int
) -> None:
    path = fixture_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    template = manifest["frames"][0]
    manifest["frames"] = [{**template, "frame_number": i} for i in range(1, total + 1)]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    count = total if selected is None else len(selected)
    with pytest.raises(ValueError) as error:
        prepare_request(path, max_frames=limit, selected_frames=selected)
    assert f"found {total} frames in the extraction manifest" in str(error.value)
    assert f"{count} selected for this request" in str(error.value)


def test_default_accepts_all_frames_beyond_previous_count_limit(tmp_path: Path) -> None:
    path = fixture_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    template = manifest["frames"][0]
    manifest["frames"] = [{**template, "frame_number": i} for i in range(1, 102)]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _, _, ids, _, _ = prepare_request(path)
    assert len(ids) == 101
    result = CliRunner().invoke(app, ["--extraction", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output


def test_all_frames_still_respect_image_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture_manifest(tmp_path)
    monkeypatch.setattr("video_ocr.review.MAX_REVIEW_IMAGE_BYTES", 1)
    with pytest.raises(ValueError, match="Images exceed 25 MB"):
        prepare_request(path)
    result = CliRunner().invoke(app, ["--extraction", str(tmp_path), "--dry-run"])
    assert result.exit_code == 1
    assert "No API call made" in result.output


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
def test_prepared_image_is_sent_unchanged_without_original(
    tmp_path: Path, fmt: str
) -> None:
    path = fixture_manifest(tmp_path)
    manifest = json.loads(path.read_text())
    crop = CropBox.model_validate(manifest["parameters"]["crop"])
    with Image.open(tmp_path / "frame.png") as image:
        encoded = encode_review_webp(image, crop)
    if fmt == "JPEG":
        buffer = io.BytesIO()
        with Image.open(io.BytesIO(encoded)) as image:
            image.save(buffer, format="JPEG", quality=95)
        encoded = buffer.getvalue()
    (tmp_path / "review.jpg").write_bytes(encoded)
    manifest["frames"][0].update(
        review_image="review.jpg", review_crop=crop.model_dump()
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "frame.png").unlink()
    _, _, _, content, _ = prepare_request(path)
    payload = next(
        item["image_url"] for item in content if item["type"] == "input_image"
    )
    assert payload.startswith(f"data:image/{fmt.lower()};base64,")
    assert base64.b64decode(payload.split(",", 1)[1]) == encoded
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (80, 180)


def test_changed_crop_regenerates_from_original(tmp_path: Path) -> None:
    path = fixture_manifest(tmp_path)
    manifest = json.loads(path.read_text())
    manifest["frames"][0].update(
        review_image="unused.jpg",
        review_crop={"left": 0, "top": 0, "right": 0, "bottom": 0},
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _, _, _, content, _ = prepare_request(path)
    payload = next(
        item["image_url"] for item in content if item["type"] == "input_image"
    )
    with Image.open(io.BytesIO(base64.b64decode(payload.split(",", 1)[1]))) as image:
        assert image.size == (80, 180)


def test_missing_manifest_explains_how_to_prepare_review(tmp_path: Path) -> None:
    response = CliRunner().invoke(app, ["--extraction", str(tmp_path), "--dry-run"])
    assert response.exit_code == 1
    assert "--prepare-review" in response.output
    assert "new output directory" in response.output


def test_model_and_reasoning_env_can_be_overridden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_manifest(tmp_path)
    monkeypatch.setenv("OPENAI_REVIEW_MODEL", "gpt-6-sol")
    monkeypatch.setenv("OPENAI_REVIEW_REASONING", "high")
    runner = CliRunner()
    args = ["--extraction", str(tmp_path), "--dry-run"]
    default = runner.invoke(app, args)
    assert default.exit_code == 0
    assert "gpt-6-sol; reasoning: high" in default.output
    override = runner.invoke(
        app, [*args, "--model", "another-model", "--reasoning-effort", "low"]
    )
    assert override.exit_code == 0
    assert "another-model; reasoning: low" in override.output


@pytest.mark.parametrize("reason", ["max_output_tokens", "content_filter"])
def test_incomplete_response_checked_before_parsing(reason: str) -> None:
    response = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason=reason),
        output_text='{"summary": "truncated',
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: response))
    with pytest.raises(ValueError, match=reason):
        request_review(client, "test", [], 12000)


def test_malformed_completed_json_is_reported_without_content() -> None:
    response = SimpleNamespace(status="completed", output=[], output_text='{"secret')
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: response))
    with pytest.raises(ValueError, match="invalid JSON") as error:
        request_review(client, "test", [], 12000)
    assert "secret" not in str(error.value)
