"""VL adapter contracts without downloading weights or importing Paddle."""

import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from video_ocr.models import EngineName, OCREngineUnavailableError
from video_ocr.ocr import create_ocr_engine
from video_ocr.paddle_vl import parse_vl_page


def test_paddle_pins_v6_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    from video_ocr.ocr import PaddleOCREngine  # noqa: PLC0415

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "video_ocr.ocr._require_paddleocr", lambda: lambda **kw: calls.append(kw)
    )
    monkeypatch.setattr("video_ocr.ocr._paddle_models_cached", lambda: True)
    PaddleOCREngine()
    assert calls[0]["ocr_version"] == "PP-OCRv6"
    assert calls[0]["text_recognition_model_name"] == "PP-OCRv6_medium_rec"


def test_vl_preserves_whitespace_without_fabricating_geometry() -> None:
    text = '12 def f():\n13     return "A  B"\n\n14 # end'
    result = parse_vl_page({"res": {"parsing_res_list": [{"block_content": text}]}})
    assert "\n".join(line.text for line in result) == text
    assert all(
        line.confidence is None and line.top is None and not line.words
        for line in result
    )


def test_vl_result_uses_json_view_of_dict_subclass() -> None:
    class Result(dict[str, Any]):
        @property
        def json(self) -> dict[str, Any]:
            return {"res": {"parsing_res_list": [{"block_content": "1 x = 2"}]}}

    assert parse_vl_page(Result(parsing_res_list=[object()]))[0].text == "1 x = 2"


@pytest.mark.parametrize(
    "payload", [{}, {"parsing_res_list": None}, {"parsing_res_list": [{}]}]
)
def test_vl_rejects_invalid_response(payload: Any) -> None:
    with pytest.raises(ValueError):
        parse_vl_page(payload)


def test_vl_factory_pins_pipeline_and_uses_local_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reader:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["pipeline_version"] == "v1.6"
            assert kwargs["device"] == "gpu:0"
            assert kwargs["use_layout_detection"] is False
            assert kwargs["format_block_content"] is False

        def predict(self, image: Any) -> list[Any]:
            assert image.shape == (10, 10, 3)
            return [{"parsing_res_list": [{"block_content": "1 x = 2"}]}]

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCRVL=Reader))
    result = create_ocr_engine(EngineName.paddle_vl).recognize(
        np.zeros((10, 10), dtype=np.uint8)
    )
    assert result.text == "1 x = 2" and result.confidence is None


def test_vl_old_runtime_does_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def old_runtime(**kwargs: Any) -> None:
        raise ValueError("Unsupported pipeline v1.6")

    monkeypatch.setitem(
        sys.modules, "paddleocr", SimpleNamespace(PaddleOCRVL=old_runtime)
    )
    with pytest.raises(OCREngineUnavailableError, match="uv sync --group paddle-vl"):
        create_ocr_engine(EngineName.paddle_vl)
