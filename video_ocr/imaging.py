"""Imaging for local video OCR."""

from video_ocr.models import (
    BLUR_THRESHOLD,
    DENOISE_KERNEL_SIZE,
    SSIM_COMPARE_WIDTH,
    UPSCALE_FACTOR,
    CropBox,
    MatLike,
    PreprocessConfig,
    PreprocessProfile,
    require_cv2,
)


def apply_crop(image: MatLike, crop: CropBox) -> MatLike:
    """Slice the frame to the crop box; an all-zero crop is the identity."""
    height, width = image.shape[:2]
    return image[crop.top : height - crop.bottom, crop.left : width - crop.right]


def _cropped_grayscale(image: MatLike, crop: CropBox) -> MatLike:
    """Crop then convert to grayscale — the input to selection and preprocessing."""
    cv2 = require_cv2()
    return cv2.cvtColor(apply_crop(image, crop), cv2.COLOR_BGR2GRAY)


def preprocess_frame(
    image: MatLike, crop: CropBox, config: PreprocessConfig | None = None
) -> MatLike:
    """Prepare a frame for OCR: crop → grayscale → upscale → threshold → denoise."""
    cv2 = require_cv2()
    config = config or PreprocessConfig()
    if config.profile != PreprocessProfile.legacy:
        cropped = apply_crop(image, crop)
        if config.profile == PreprocessProfile.native:
            return cropped
        height, width = cropped.shape[:2]
        scale = min(config.scale, config.max_side / max(height, width))
        if scale == 1:
            return cropped
        return cv2.resize(
            cropped,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )
    gray = _cropped_grayscale(image, crop)
    upscaled = cv2.resize(
        gray, None, fx=UPSCALE_FACTOR, fy=UPSCALE_FACTOR, interpolation=cv2.INTER_CUBIC
    )
    _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if float(binary.mean()) < 127:
        # Dark editor theme: Tesseract reads dark-on-light best, so invert.
        binary = cv2.bitwise_not(binary)
    return cv2.medianBlur(binary, DENOISE_KERNEL_SIZE)


def frame_sharpness(gray_image: MatLike) -> float:
    """Laplacian variance — the sharpness score for the blur gate and merging."""
    cv2 = require_cv2()
    return float(cv2.Laplacian(gray_image, cv2.CV_64F).var())


def is_frame_blurry(sharpness: float) -> bool:
    """Sharpness gate: True when the score is below ``BLUR_THRESHOLD``."""
    return sharpness < BLUR_THRESHOLD


def _ssim_thumbnail(gray_image: MatLike) -> MatLike:
    """Shrink a grayscale frame for fast SSIM (min 7 px, skimage's window size)."""
    cv2 = require_cv2()
    height, width = gray_image.shape[:2]
    thumb_height = max(7, round(height * SSIM_COMPARE_WIDTH / width))
    return cv2.resize(
        gray_image, (SSIM_COMPARE_WIDTH, thumb_height), interpolation=cv2.INTER_AREA
    )
