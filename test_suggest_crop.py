"""Tests for the crop-suggestion preview tool (`suggest_crop.py`).

Unit tests exercise the heuristic with a fake OCR engine on synthetic frames;
API tests run the FastAPI app against `sample-video/IMG_5430.MOV` and are
skipped cleanly when the video or the Tesseract backend is unavailable.
"""

import base64
import math
import struct
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from extract_code_from_video import (
    UPSCALE_FACTOR,
    CropBox,
    EngineName,
    InvalidExtractionParameterError,
    OCREngineUnavailableError,
    OCRLine,
    OCRResult,
    OCRWord,
    get_video_metadata,
)
from suggest_crop import (
    REFERENCE_FRAME_INDEX,
    THUMBNAIL_WIDTH,
    FrameObservation,
    ReferenceFrame,
    TextGeometry,
    _crop_error,
    combine_observations,
    create_app,
    read_sampled_frames,
    sample_frame_indices,
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
        OCRWord(
            text=text.split(maxsplit=1)[0], left=left, top=top, width=40, height=20
        ),
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
    # UPSCALE_FACTOR=2; line height 10 -> margin max(8, 10) = 10. The right
    # edge stays at 0: there is no noise column to remove.
    assert UPSCALE_FACTOR == 2.0
    assert suggestion.crop == CropBox(left=30, top=40, right=0, bottom=230)


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


def test_right_crop_cuts_at_the_noise_column_start() -> None:
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
    # The junk never widens the text box (left/top/bottom are unchanged), and
    # the right crop removes exactly the noise column: the junk starts at
    # upscaled x=1100 -> 550 original, so 600 - 550 = 50 pixels are cut.
    assert with_junk.crop == without_junk.crop.model_copy(update={"right": 50})
    assert without_junk.crop.right == 0


def test_fallback_clusters_lines_when_no_gutter() -> None:
    lines = [_line("def code", top=100 + 40 * n) for n in range(4)]
    suggestion = suggest_crop(_frame(), FakeEngine(OCRResult(text="code", lines=lines)))
    assert suggestion.text_detected is True
    # Same geometry as the gutter test but only 4 rows of non-number tokens:
    # band comes from line clustering, (40..350) x (50..120), margin 10.
    assert suggestion.crop == CropBox(left=30, top=40, right=0, bottom=270)


def _observation(
    index: int,
    *,
    left: float = 40.0,
    top: float = 50.0,
    bottom: float = 160.0,
    text_right: float = 350.0,
    noise_left: float | None = None,
    line_height: float = 10.0,
    gutter_anchored: bool = False,
) -> FrameObservation:
    """A text-bearing observation with the gutter-test geometry as defaults."""
    return FrameObservation(
        frame_index=index,
        text=TextGeometry(
            left=left,
            top=top,
            bottom=bottom,
            text_right=text_right,
            noise_left=noise_left,
            line_height=line_height,
            gutter_anchored=gutter_anchored,
        ),
    )


# --- Sampling unit tests ------------------------------------------------------


def test_sample_indices_are_evenly_spread() -> None:
    indices = sample_frame_indices(total_frames=1030, count=5)
    assert indices == [30, 280, 530, 779, 1029]


def test_sample_indices_short_video_falls_back_to_last_frame() -> None:
    assert sample_frame_indices(total_frames=10, count=5) == [9]


def test_sample_indices_count_one_uses_the_reference_frame() -> None:
    assert sample_frame_indices(total_frames=1030, count=1) == [REFERENCE_FRAME_INDEX]


def test_sample_indices_deduplicate_when_video_is_short() -> None:
    indices = sample_frame_indices(total_frames=34, count=12)
    assert indices == sorted(set(indices))
    assert indices[0] == 30 and indices[-1] == 33


def test_sample_indices_respect_an_explicit_window() -> None:
    indices = sample_frame_indices(
        total_frames=1030, count=5, start_frame=100, end_frame_exclusive=601
    )
    assert indices == [100, 225, 350, 475, 600]


def test_sample_indices_explicit_start_skips_the_reference_offset() -> None:
    # `--start-time` before the reference frame is respected exactly: the
    # artifact-skipping default only applies when no window start was given.
    indices = sample_frame_indices(total_frames=1030, count=3, start_frame=10)
    assert indices[0] == 10 and indices[-1] == 1029


def test_read_sampled_frames_respects_the_time_window() -> None:
    if not SAMPLE_VIDEO.is_file():
        pytest.skip(f"sample video not available: {SAMPLE_VIDEO}")
    metadata = get_video_metadata(SAMPLE_VIDEO)
    samples = read_sampled_frames(SAMPLE_VIDEO, 3, start_time="2", end_time="4")
    indices = [frame.frame_index for frame in samples.frames]
    assert indices == sorted(indices)
    assert indices[0] >= math.floor(2 * metadata.fps)
    assert indices[-1] <= math.ceil(4 * metadata.fps)


def test_read_sampled_frames_rejects_an_inverted_window() -> None:
    if not SAMPLE_VIDEO.is_file():
        pytest.skip(f"sample video not available: {SAMPLE_VIDEO}")
    with pytest.raises(InvalidExtractionParameterError):
        read_sampled_frames(SAMPLE_VIDEO, 3, start_time="5", end_time="2")


def test_read_sampled_frames_rejects_a_subframe_window() -> None:
    if not SAMPLE_VIDEO.is_file():
        pytest.skip(f"sample video not available: {SAMPLE_VIDEO}")
    fps = get_video_metadata(SAMPLE_VIDEO).fps
    # A valid window that falls strictly between two frame timestamps: it must
    # be rejected, not silently widened to a frame outside the window.
    start = f"{(10 + 0.3) / fps:.6f}"
    end = f"{(10 + 0.7) / fps:.6f}"
    with pytest.raises(InvalidExtractionParameterError):
        read_sampled_frames(SAMPLE_VIDEO, 3, start_time=start, end_time=end)


# --- Combination unit tests ---------------------------------------------------


def test_combine_widest_gutter_wins_on_the_left() -> None:
    # Line numbers grew wider later in the video: frame 500 sees a gutter
    # starting further left; the combined crop must not cut it. Margin is
    # max(8, 10) = 10.
    combined = combine_observations(
        [_observation(30, left=40), _observation(500, left=25)], 600, 400
    )
    assert combined.crop.left == 15
    assert combined.text_frame_indices == [30, 500]


def test_combine_vertical_band_is_the_union() -> None:
    combined = combine_observations(
        [_observation(30, top=50, bottom=160), _observation(500, top=80, bottom=300)],
        600,
        400,
    )
    assert combined.crop.top == 40
    assert combined.crop.bottom == 400 - 300 - 10


def test_combine_noise_column_needs_a_majority() -> None:
    minority = combine_observations(
        [
            _observation(30, noise_left=550),
            _observation(300),
            _observation(600),
        ],
        600,
        400,
    )
    assert minority.crop.right == 0
    majority = combine_observations(
        [
            _observation(30, noise_left=550),
            _observation(300, noise_left=560),
            _observation(600),
        ],
        600,
        400,
    )
    assert majority.crop.right == 600 - 560


def test_combine_right_cut_stays_at_the_rightmost_noise_start() -> None:
    # Both frames agree the noise column starts by x=500; frame 600's "kept"
    # text reaching x=550 is junk that leaked past the per-frame confidence
    # filter and must not push the cut right of the noise column.
    combined = combine_observations(
        [
            _observation(30, noise_left=500),
            _observation(600, noise_left=500, text_right=550),
        ],
        600,
        400,
    )
    assert combined.crop.right == 600 - 500


def test_combine_right_cut_excludes_junk_merged_into_kept_text() -> None:
    # Frame 600 never detected the noise column: the minimap junk merged into
    # its kept text (text_right=590). The majority located the noise at
    # x<=560, so the combined crop still cuts the column there.
    combined = combine_observations(
        [
            _observation(30, noise_left=560),
            _observation(300, noise_left=550),
            _observation(600, text_right=590),
        ],
        600,
        400,
    )
    assert combined.crop.right == 600 - 560


def test_combine_ignores_empty_frames_and_reports_them() -> None:
    combined = combine_observations(
        [FrameObservation(frame_index=30), _observation(500)],
        600,
        400,
        skipped_frame_indices=[999],
    )
    assert combined.text_detected is True
    assert combined.analyzed_frame_indices == [30, 500]
    assert combined.text_frame_indices == [500]
    assert combined.skipped_frame_indices == [999]


def test_combine_gutter_anchored_frames_outrank_fallback_ones() -> None:
    # A fallback-cluster frame swept in menu-bar/status-bar chrome (band from
    # y=2 to the frame bottom, "text" to the right edge). With one gutter
    # frame present it must not widen the crop; alone, it still informs.
    chrome = _observation(310, left=5, top=2, bottom=390, text_right=600)
    anchored = _observation(30, gutter_anchored=True)
    combined = combine_observations([chrome, anchored], 600, 400)
    assert combined.text_frame_indices == [30]
    assert combined.crop == combine_observations([anchored], 600, 400).crop
    alone = combine_observations([chrome], 600, 400)
    assert alone.text_frame_indices == [310]
    assert alone.crop.top == 0


def test_combine_all_empty_yields_zero_crop() -> None:
    combined = combine_observations(
        [FrameObservation(frame_index=30), FrameObservation(frame_index=500)],
        600,
        400,
    )
    assert combined.crop == CropBox()
    assert combined.text_detected is False
    assert combined.text_frame_indices == []


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
        app = create_app(SAMPLE_VIDEO, EngineName.tesseract, sample_count=3)
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
    assert len(data["analyzed_frame_indices"]) == 3
    assert data["analyzed_frame_indices"][0] == data["frame_index"]
    assert set(data["text_frame_indices"]) <= set(data["analyzed_frame_indices"])
    assert data["skipped_frame_indices"] == []
    samples = data["sample_frames"]
    assert [sample["frame_index"] for sample in samples] == data[
        "analyzed_frame_indices"
    ]
    for sample in samples:
        width, _ = _png_size(sample["png_base64"])
        assert width <= THUMBNAIL_WIDTH


def test_full_frame_endpoint_serves_each_sampled_frame(client: TestClient) -> None:
    preview = client.get("/api/preview").json()
    for frame_index in preview["analyzed_frame_indices"]:
        response = client.get(f"/api/frame/{frame_index}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        width, height = struct.unpack(">II", response.content[16:24])
        assert (width, height) == (preview["frame_width"], preview["frame_height"])


def test_full_frame_endpoint_rejects_unsampled_index(client: TestClient) -> None:
    response = client.get("/api/frame/999999")
    assert response.status_code == 404
    assert "was not sampled" in response.json()["detail"]


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
