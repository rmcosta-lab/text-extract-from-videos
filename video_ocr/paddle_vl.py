"""Optional local PaddleOCR-VL-1.6 reader, without invented line geometry."""

import os
from collections.abc import Mapping
from typing import Any

from video_ocr.models import (
    MatLike,
    OCREngineUnavailableError,
    OCRLine,
    OCRResult,
    _warn,
)
from video_ocr.ocr import _paddle_input


def parse_vl_page(page: Any) -> list[OCRLine]:
    """Use raw block content in model reading order, preserving whitespace."""
    payload = page.json if hasattr(page, "json") else page
    if not isinstance(payload, Mapping):
        raise ValueError("Unexpected PaddleOCR-VL result: expected JSON mapping")
    payload = payload.get("res", payload)
    if not isinstance(payload, Mapping) or "parsing_res_list" not in payload:
        raise ValueError("PaddleOCR-VL result missing parsing_res_list")
    blocks = payload["parsing_res_list"]
    if not isinstance(blocks, list):
        raise ValueError("PaddleOCR-VL parsing_res_list must be a list")
    lines: list[OCRLine] = []
    for block in blocks:
        if not isinstance(block, Mapping) or not isinstance(
            block.get("block_content"), str
        ):
            raise ValueError("PaddleOCR-VL block missing text content")
        # Block boxes do not locate individual lines. Confidence is not provided.
        lines.extend(OCRLine(text=text) for text in block["block_content"].split("\n"))
    return lines


class PaddleVLEngine:
    """Direct GPU inference; no cloud service and no fallback to older models."""

    def __init__(self) -> None:
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        _warn(
            "PaddleOCR-VL-1.6 is experimental for code. Initial use downloads model "
            "weights if absent; subsequent cached runs are local. No line confidence "
            "or geometry is fabricated. Keep editor line numbers visible."
        )
        try:
            from paddleocr import PaddleOCRVL  # type: ignore[import-untyped] # noqa: PLC0415

            self._reader = PaddleOCRVL(
                pipeline_version="v1.6",
                vl_rec_model_name="PaddleOCR-VL-1.6-0.9B",
                device="gpu:0",
                use_layout_detection=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                format_block_content=False,
                use_queues=False,
            )
        except Exception as exc:
            raise OCREngineUnavailableError(
                "PaddleOCR-VL-1.6 initialization failed. Run "
                "uv sync --group paddle-vl; ensure CUDA and model weights "
                "are available. "
                f"Details: {exc}"
            ) from exc

    def recognize(self, image: MatLike) -> OCRResult:
        lines = [
            line
            for page in self._reader.predict(_paddle_input(image))
            for line in parse_vl_page(page)
        ]
        return OCRResult(text="\n".join(line.text for line in lines), lines=lines)
