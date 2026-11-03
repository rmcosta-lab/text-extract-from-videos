"""Image geometry and color fidelity across explicit preprocessing profiles."""

import numpy as np
import pytest

from video_ocr.imaging import apply_crop, preprocess_frame
from video_ocr.models import CropBox, PreprocessConfig, PreprocessProfile


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
