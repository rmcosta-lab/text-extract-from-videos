"""Ocr for local video OCR."""

import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from statistics import median
from typing import (
    Any,
)

from video_ocr.models import (
    EngineName,
    MatLike,
    OCREngine,
    OCREngineUnavailableError,
    OCRLine,
    OCRResult,
    OCRWord,
    _warn,
    require_cv2,
)


def _require_pytesseract() -> Any:
    """Import pytesseract only when the Tesseract engine is instantiated."""
    try:
        import pytesseract  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise OCREngineUnavailableError(
            "the pytesseract Python package is not installed. Install it with "
            "[bold]uv sync[/bold], then re-run."
        ) from exc
    return pytesseract


def _parse_tesseract_int(value: object) -> int:
    """Parse integer-ish Tesseract fields, defaulting invalid geometry to 0."""
    try:
        return max(0, int(float(str(value))))
    except ValueError:
        return 0


def _parse_tesseract_confidence(value: object) -> float | None:
    """Parse a Tesseract confidence value; `-1` means no confidence."""
    try:
        confidence = float(str(value))
    except ValueError:
        return None
    return confidence if confidence >= 0 else None


def _mean_confidence(values: Iterable[float | None]) -> float | None:
    """Mean of present confidence values, rounded for stable artifacts."""
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 2) if present else None


def _assemble_ocr_result(lines: list[OCRLine], confidence: float | None) -> OCRResult:
    """Order per-line reads top-to-bottom and assemble one engine result.

    Shared by both engines so the sort/aggregate contract cannot drift; each
    engine supplies its own mean confidence (Tesseract averages word scores,
    PaddleOCR line scores).
    """
    lines.sort(
        key=lambda line: (line.top if line.top is not None else 0, line.left or 0)
    )
    text = "\n".join(line.text for line in lines)
    return OCRResult(text=text, confidence=confidence, lines=lines)


def _word_right(word: OCRWord) -> int:
    """Right edge of one OCR word bounding box."""
    return word.left + word.width


def _line_right(line: OCRLine) -> int | None:
    """Right edge of one OCR line bounding box when geometry is available."""
    if line.left is None or line.width is None:
        return None
    return line.left + line.width


def _median_char_width(words: list[OCRWord]) -> float:
    """Estimate character width from OCR word boxes for spacing reconstruction."""
    widths = [
        word.width / len(word.text) for word in words if word.text and word.width > 0
    ]
    return max(1.0, float(median(widths))) if widths else 8.0


def _reconstruct_words(words: list[OCRWord], *, origin_left: int | None = None) -> str:
    """Rebuild a line from word boxes, preserving measured spaces only."""
    ordered = sorted(words, key=lambda word: word.left)
    if not ordered:
        return ""

    char_width = _median_char_width(ordered)
    origin = ordered[0].left if origin_left is None else origin_left
    pieces: list[str] = []
    first_gap = ordered[0].left - origin
    if first_gap > char_width * 0.75:
        pieces.append(" " * max(0, round(first_gap / char_width)))

    cursor = _word_right(ordered[0])
    pieces.append(ordered[0].text)
    for word in ordered[1:]:
        gap = word.left - cursor
        if gap > char_width * 0.5:
            pieces.append(" " * max(1, round(gap / char_width)))
        pieces.append(word.text)
        cursor = max(cursor, _word_right(word))
    return "".join(pieces)


def _build_ocr_line(words: list[OCRWord], *, origin_left: int | None) -> OCRLine:
    """Build one line model with geometry and evidence-preserving text."""
    left = min(word.left for word in words)
    top = min(word.top for word in words)
    right = max(_word_right(word) for word in words)
    bottom = max(word.top + word.height for word in words)
    return OCRLine(
        text=_reconstruct_words(words, origin_left=origin_left),
        confidence=_mean_confidence(word.confidence for word in words),
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
        words=sorted(words, key=lambda word: word.left),
    )


class TesseractEngine:
    """`OCREngine` implementation backed by pytesseract / Tesseract.

    The rest of the pipeline must depend only on :class:`OCREngine`;
    pytesseract is referenced exclusively inside this class.
    """

    def __init__(self) -> None:
        self._pytesseract = _require_pytesseract()
        try:
            self._pytesseract.get_tesseract_version()
        except self._pytesseract.TesseractNotFoundError as exc:
            raise OCREngineUnavailableError(
                "the tesseract binary is not installed. Install it with "
                "[bold]brew install tesseract[/bold] (macOS) or your system "
                "package manager, then re-run."
            ) from exc

    def recognize(self, image: MatLike) -> OCRResult:
        """OCR the whole image; per-line reads with mean word confidence each."""
        data = self._pytesseract.image_to_data(
            image,
            config="-c preserve_interword_spaces=1",
            output_type=self._pytesseract.Output.DICT,
        )
        words_by_line: dict[tuple[int, int, int], list[OCRWord]] = {}
        words = zip(
            data["text"],
            data["conf"],
            data["block_num"],
            data["par_num"],
            data["line_num"],
            data["left"],
            data["top"],
            data["width"],
            data["height"],
            strict=True,
        )
        for word, conf, block, paragraph, line, left, top, width, height in words:
            if not word.strip():
                continue
            key = (
                _parse_tesseract_int(block),
                _parse_tesseract_int(paragraph),
                _parse_tesseract_int(line),
            )
            words_by_line.setdefault(key, []).append(
                OCRWord(
                    text=str(word),
                    confidence=_parse_tesseract_confidence(conf),
                    left=_parse_tesseract_int(left),
                    top=_parse_tesseract_int(top),
                    width=_parse_tesseract_int(width),
                    height=_parse_tesseract_int(height),
                )
            )

        all_words = [
            word for words_in_line in words_by_line.values() for word in words_in_line
        ]
        if not all_words:
            return OCRResult(text="", confidence=None, lines=[])

        origin_left = min(word.left for word in all_words)
        lines = [
            _build_ocr_line(words_in_line, origin_left=origin_left)
            for words_in_line in words_by_line.values()
        ]
        return _assemble_ocr_result(
            lines, _mean_confidence(word.confidence for word in all_words)
        )


def _require_paddleocr() -> Any:
    """Import paddleocr only when the Paddle engine is instantiated."""
    try:
        from paddleocr import PaddleOCR  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise OCREngineUnavailableError(
            "the paddleocr Python package is not installed. Install it with "
            "[bold]uv sync --group paddle-gpu[/bold], then "
            "re-run."
        ) from exc
    return PaddleOCR


def _paddle_confidence(score: Any) -> float | None:
    """Normalize PaddleOCR's 0..1 recognition score onto the 0..100 scale."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    return round(value * 100.0, 2) if value >= 0 else None


def _paddle_box(points: Any) -> tuple[int, int, int, int]:
    """Axis-aligned left/top/width/height of one PaddleOCR polygon."""
    coordinates = (
        [(float(x), float(y)) for x, y in points] if points is not None else []
    )
    if not coordinates:
        return 0, 0, 0, 0
    xs = [x for x, _ in coordinates]
    ys = [y for _, y in coordinates]
    left = max(0, round(min(xs)))
    top = max(0, round(min(ys)))
    width = max(0, round(max(xs)) - left)
    height = max(0, round(max(ys)) - top)
    return left, top, width, height


def _paddle_detections(page: Any) -> Iterator[tuple[str, Any, Any]]:
    """Yield (text, score, polygon) from one PaddleOCR page result.

    Handles both the 3.x dict-like results (``rec_texts`` / ``rec_scores`` /
    ``rec_polys``) and the legacy 2.x ``[polygon, (text, score)]`` lists.
    """
    if page is None:
        return
    getter = getattr(page, "get", None)
    if callable(getter):
        texts = getter("rec_texts")
        scores = getter("rec_scores")
        polys = getter("rec_polys")
        if polys is None:
            polys = getter("dt_polys")
        texts = [] if texts is None else list(texts)
        scores = [] if scores is None else list(scores)
        polys = [] if polys is None else list(polys)
        for index, text in enumerate(texts):
            score = scores[index] if index < len(scores) else None
            poly = polys[index] if index < len(polys) else None
            yield str(text), score, poly
        return
    for detection in page:
        if not detection:
            continue
        poly, recognition = detection[0], detection[1]
        yield str(recognition[0]), recognition[1], poly


def _paddle_models_cached() -> bool:
    """Best-effort check that PaddleX model files are already on disk."""
    cache_home = os.environ.get("PADDLE_PDX_CACHE_HOME")
    models_dir = (
        Path(cache_home) if cache_home else Path.home() / ".paddlex"
    ) / "official_models"
    try:
        return models_dir.is_dir() and any(models_dir.iterdir())
    except OSError:
        return False


def _paddle_input(image: MatLike) -> MatLike:
    """PaddleOCR expects 3-channel input; expand preprocessed grayscale frames."""
    if getattr(image, "ndim", 3) == 2:
        cv2 = require_cv2()
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image


class PaddleOCREngine:
    """`OCREngine` implementation backed by PaddleOCR.

    Mirrors :class:`TesseractEngine`: paddleocr is imported and referenced
    exclusively inside this class, and unavailability surfaces as
    :class:`OCREngineUnavailableError` with an actionable install hint.
    PaddleOCR reads whole lines, so each detection becomes one
    :class:`OCRLine` carrying a single line-spanning :class:`OCRWord` —
    per-word boxes are never fabricated.
    """

    def __init__(self) -> None:
        # Keep cached-model runs offline: skip PaddleX's model-hoster
        # connectivity probe unless the user explicitly re-enables it.
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        if not _paddle_models_cached():
            _warn(
                "no cached PaddleOCR models were found — the first PaddleOCR "
                "run downloads them from the network, breaking the offline "
                "guarantee for this run. Run it once on a connected machine "
                "(models land in ~/.paddlex/official_models), then re-run."
            )
        paddle_ocr = _require_paddleocr()
        try:
            try:
                self._reader = paddle_ocr(
                    lang="en",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except TypeError:
                self._reader = paddle_ocr(lang="en")
        except Exception as exc:
            raise OCREngineUnavailableError(
                f"PaddleOCR failed to initialize ({exc}). Ensure paddlepaddle "
                "is installed ([bold]uv sync --group paddle-gpu[/bold]) "
                "and its models are available locally, "
                "then re-run."
            ) from exc

    def recognize(self, image: MatLike) -> OCRResult:
        """OCR the whole image; per-line Paddle reads mapped onto the seam models."""
        prepared = _paddle_input(image)
        if hasattr(self._reader, "predict"):
            pages = self._reader.predict(prepared)
        else:
            pages = self._reader.ocr(prepared)

        lines: list[OCRLine] = []
        for page in pages if pages is not None else []:
            for text, score, poly in _paddle_detections(page):
                if not text.strip():
                    continue
                confidence = _paddle_confidence(score)
                left, top, width, height = _paddle_box(poly)
                word = OCRWord(
                    text=text,
                    confidence=confidence,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                )
                lines.append(
                    OCRLine(
                        text=text,
                        confidence=confidence,
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                        words=[word],
                    )
                )

        if not lines:
            return OCRResult(text="", confidence=None, lines=[])
        return _assemble_ocr_result(
            lines, _mean_confidence(line.confidence for line in lines)
        )


def create_ocr_engine(name: EngineName) -> OCREngine:
    """Instantiate the engine selected by ``--engine`` behind the seam."""
    if name is EngineName.paddle:
        return PaddleOCREngine()
    return TesseractEngine()
