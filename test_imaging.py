"""Image geometry and color fidelity across explicit preprocessing profiles."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_ocr.imaging import apply_crop, preprocess_frame
from video_ocr.models import CropBox, OCRResult, PreprocessConfig, PreprocessProfile
from video_ocr.pipeline import run_ocr


def test_native_preserves_color_and_crop_pixels() -> None:
    image = np.arange(60 * 80 * 3, dtype=np.uint8).reshape(60, 80, 3)
    crop = CropBox(left=5, top=10, right=7, bottom=2)
    result = preprocess_frame(
        image, crop, PreprocessConfig(profile=PreprocessProfile.native)
    )
    np.testing.assert_array_equal(result, image[10:58, 5:73])


@pytest.mark.parametrize("height,width", [(400, 200), (200, 400)])
def test_bounded_respects_limit_and_aspect_ratio(height: int, width: int) -> None:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    result = preprocess_frame(
        image,
        CropBox(),
        PreprocessConfig(profile=PreprocessProfile.bounded, scale=2, max_side=300),
    )
    assert max(result.shape[:2]) == 300
    assert result.shape[1] / result.shape[0] == width / height


def test_legacy_remains_binary_double_resolution() -> None:
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    crop = CropBox(left=10, right=10)
    result = preprocess_frame(image, crop)
    assert result.shape == (160, 160)
    assert set(np.unique(result)) <= {0, 255}
    assert apply_crop(image, crop).shape == (80, 80, 3)


def test_extraction_prepares_color_webp_with_crop(tmp_path: Path) -> None:
    class Engine:
        def recognize(self, image: object) -> OCRResult:
            return OCRResult(text="test", lines=[])

    image = np.random.default_rng(7).integers(0, 256, (100, 160, 3), dtype=np.uint8)
    image[30:70, 50:100] = [0, 0, 255]  # BGR red; catch RGB/BGR reversal.
    crop = CropBox(left=10, top=20, right=30, bottom=10)
    rows, _, _ = run_ocr(
        [(1320, 22.0, image)], Engine(), tmp_path, 1, crop, prepare_review=True
    )
    assert len(rows) == 1
    with Image.open(tmp_path / "frame_1320_review.webp") as prepared:
        assert prepared.size == (120, 70)
        pixel = prepared.getpixel((60, 30))
        assert isinstance(pixel, tuple)
        red, green, blue = pixel
        assert red > 240 and green < 15 and blue < 15
    with Image.open(tmp_path / "frame_1320_original.png") as original:
        assert original.size == (160, 100)
