"""Automatic discovery uses semantic evidence without handwritten video coordinates."""

from pathlib import Path
from typing import Any

import cv2
import pytest

from explorer_segments.automatic import LocalOCR, TextBox, discover, locate_panel
from test_explorer_segments import synthetic_frame


def tree_boxes() -> list[TextBox]:
    title = TextBox(text="Explorer", score=0.99, x=35, y=75, width=90, height=15)
    return [
        title,
        *[
            TextBox(text=label, score=0.99, x=45, y=105 + i * 20, width=80, height=14)
            for i, label in enumerate(["project", "docs", "src", "utils", "tests"])
        ],
    ]


def test_heading_requires_tree_and_ignores_tooltip() -> None:
    assert locate_panel(tree_boxes(), 720, 480) is not None
    assert locate_panel(tree_boxes()[:1], 720, 480) is None
    tooltip = tree_boxes()
    tooltip[0] = tooltip[0].model_copy(update={"text": "Explorer (Ctrl+Shift+E)"})
    assert locate_panel(tooltip, 720, 480) is None
    code = tree_boxes()
    for box in code[1:]:
        box.text = "print(value)"
    assert locate_panel(code, 720, 480) is None


def test_no_model_download_when_cache_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="downloads are disabled"):
        LocalOCR(tmp_path)


def test_automatic_discovery_when_video_starts_without_explorer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positive = synthetic_frame(True)
    for i, label in enumerate(["project", "docs", "src", "utils", "tests"]):
        cv2.putText(
            positive,
            label,
            (45, 115 + i * 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (230, 230, 230),
            1,
        )
    negative = synthetic_frame(False)

    class Reader:
        count = 100
        fps = 10

        def __init__(self, path: Path) -> None:
            pass

        def read_at(self, seconds: float) -> tuple[int, float, Any]:
            return round(seconds * 10), seconds, negative if seconds == 0 else positive

        def close(self) -> None:
            pass

    class OCR:
        def read(self, image: Any) -> list[TextBox]:
            return [] if image is negative else tree_boxes()

    monkeypatch.setattr("explorer_segments.automatic.VideoReader", Reader)
    profile = discover(tmp_path / "unused.mov", tmp_path / "automatic", OCR())
    assert profile.exists()
    assert (profile.parent / "discovery.json").exists()


def test_title_guard_does_not_claim_absence_when_tree_changes(tmp_path: Path) -> None:
    from explorer_segments.detection import Profile, TemplateDetector  # noqa: PLC0415
    from test_explorer_segments import detector  # noqa: PLC0415

    original = detector(tmp_path)
    profile: Profile = original.profile.model_copy(
        update={
            "title_region": original.profile.panel_region,
        }
    )
    model = TemplateDetector(profile, tmp_path)
    model.panel = cv2.flip(model.panel, 1)
    assert model.classify_image(synthetic_frame(True))[0] == "uncertain"
