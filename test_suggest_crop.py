"""Tests for the crop-suggestion preview tool (`suggest_crop.py`).

Unit tests exercise the heuristic with a fake OCR engine on synthetic frames;
API tests run the FastAPI app against `sample-video/IMG_5430.MOV` and are
skipped cleanly when the video or the Tesseract backend is unavailable.
"""

import base64
import struct
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from extract_code_from_video import (
    UPSCALE_FACTOR,
    CropBox,
    EngineName,
    OCREngineUnavailableError,
    OCRLine,
    OCRResult,
    OCRWord,
)
from suggest_crop import (
    ReferenceFrame,
    _crop_error,
    create_app,
    suggest_crop,
)

SAMPLE_VIDEO = Path(__file__).resolve().parent / "sample-video" / "IMG_5430.MOV"


class FakeEngine:
    """`OCREngine` stub returning a canned result regardless of the image."""

    def __init__(self, result: OCRResult) -> None:
        self._result = result

    def recognize(self, image: object) -> OCRResult:
        return self._result


def _frame(width: int = 600, height: int = 400) -> ReferenceFrame:
    """A black synthetic reference frame (content is irrelevant to FakeEngine)."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    return ReferenceFrame(image=image, frame_index=30, width=width, height=height)


def _line(text: str, *, top: int, left: int = 80, right: int = 700) -> OCRLine:
    """One upscaled-coordinate OCR line: a gutter token plus a code token."""
    code_left = left + 80
    words = [
        OCRWord(text=text.split()[0], left=left, top=top, width=40, height=20),
        OCRWord(
            text=text.split()[1],
            left=code_left,
            top=top,
            width=right - code_left,
            height=20,
        ),
    ]
    return OCRLine(text=text, words=words)


def _gutter_lines() -> list[OCRLine]:
    """Six numbered lines whose gutter tokens right-align into a column."""
    return [_line(f"{10 + n} code", top=100 + 40 * n) for n in range(6)]


def _png_size(png_base64: str) -> tuple[int, int]:
    """Decode a base64 PNG header and return (width, height)."""
    raw = base64.b64decode(png_base64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


# --- Heuristic unit tests ---------------------------------------------------


def test_empty_ocr_yields_zero_crop() -> None:
    suggestion = suggest_crop(_frame(), FakeEngine(OCRResult(text="", lines=[])))
    assert suggestion.crop == CropBox()
    assert suggestion.text_detected is False


def test_gutter_column_anchors_the_crop() -> None:
    suggestion = suggest_crop(
        _frame(), FakeEngine(OCRResult(text="code", lines=_gutter_lines()))
    )
    assert suggestion.text_detected is True
    # Upscaled box (80..700) x (100..320) maps to (40..350) x (50..160) at
    # UPSCALE_FACTOR=2; line height 10 -> margin max(8, 10) = 10.
    assert UPSCALE_FACTOR == 2.0
    assert suggestion.crop == CropBox(left=30, top=40, right=240, bottom=230)


def test_text_outside_gutter_band_is_ignored() -> None:
    # A status-bar-like row far below the gutter, with a different alignment.
    lines = [*_gutter_lines(), _line("99 status", top=700, left=400, right=800)]
    with_outlier = suggest_crop(
        _frame(), FakeEngine(OCRResult(text="code", lines=lines))
    )
    without_outlier = suggest_crop(
        _frame(), FakeEngine(OCRResult(text="code", lines=lines[:-1]))
    )
    assert with_outlier.crop == without_outlier.crop


def test_low_confidence_right_segment_is_trimmed() -> None:
    # Minimap-like junk: low confidence, far to the right, inside the band.
    junk = OCRLine(
        text="xx",
        words=[
            OCRWord(text="xx", confidence=5.0, left=1100, top=140, width=60, height=20)
        ],
    )
    with_junk = suggest_crop(
        _frame(),
        FakeEngine(OCRResult(text="code", lines=[*_gutter_lines(), junk])),
    )
    without_junk = suggest_crop(
        _frame(), FakeEngine(OCRResult(text="code", lines=_gutter_lines()))
    )
    assert with_junk.crop == without_junk.crop


def test_fallback_clusters_lines_when_no_gutter() -> None:
    lines = [_line("def code", top=100 + 40 * n) for n in range(4)]
    suggestion = suggest_crop(_frame(), FakeEngine(OCRResult(text="code", lines=lines)))
    assert suggestion.text_detected is True
    # Same geometry as the gutter test but only 4 rows of non-number tokens:
    # band comes from line clustering, (40..350) x (50..120), margin 10.
    assert suggestion.crop == CropBox(left=30, top=40, right=240, bottom=270)


def test_crop_error_reuses_validate_against() -> None:
    assert _crop_error(CropBox(left=10, right=10), 600, 400) is None
    message = _crop_error(CropBox(left=300, right=300), 600, 400)
    assert message is not None and "no image area" in message


# --- API tests against the sample video -------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    if not SAMPLE_VIDEO.is_file():
        pytest.skip(f"sample video not available: {SAMPLE_VIDEO}")
    try:
        app = create_app(SAMPLE_VIDEO, EngineName.tesseract)
    except OCREngineUnavailableError as exc:
        pytest.skip(f"tesseract unavailable: {exc}")
    return TestClient(app)


def test_index_serves_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Sugestão de crop" in response.text


def test_preview_returns_valid_suggestion(client: TestClient) -> None:
    response = client.get("/api/preview")
    assert response.status_code == 200
    data = response.json()
    crop = CropBox(**data["crop"])
    assert crop.left + crop.right < data["frame_width"]
    assert crop.top + crop.bottom < data["frame_height"]
    assert _png_size(data["original_png_base64"]) == (
        data["frame_width"],
        data["frame_height"],
    )
    cropped_width = data["frame_width"] - crop.left - crop.right
    cropped_height = data["frame_height"] - crop.top - crop.bottom
    assert _png_size(data["cropped_png_base64"]) == (cropped_width, cropped_height)
    assert f"--crop-left {crop.left}" in data["cli_flags"]


def test_crop_endpoint_recrops_to_requested_box(client: TestClient) -> None:
    preview = client.get("/api/preview").json()
    body = {"left": 10, "top": 20, "right": 30, "bottom": 40}
    response = client.post("/api/crop", json=body)
    assert response.status_code == 200
    data = response.json()
    expected_width = preview["frame_width"] - 40
    expected_height = preview["frame_height"] - 60
    assert (data["cropped_width"], data["cropped_height"]) == (
        expected_width,
        expected_height,
    )
    assert _png_size(data["cropped_png_base64"]) == (expected_width, expected_height)
    assert (
        data["cli_flags"]
        == "--crop-left 10 --crop-top 20 --crop-right 30 --crop-bottom 40"
    )


def test_crop_endpoint_rejects_degenerate_values(client: TestClient) -> None:
    preview = client.get("/api/preview").json()
    half = preview["frame_width"] // 2 + 1
    response = client.post(
        "/api/crop", json={"left": half, "top": 0, "right": half, "bottom": 0}
    )
    assert response.status_code == 422
    assert "no image area" in response.json()["detail"]


def test_crop_endpoint_rejects_negative_values(client: TestClient) -> None:
    response = client.post(
        "/api/crop", json={"left": -1, "top": 0, "right": 0, "bottom": 0}
    )
    assert response.status_code == 422
