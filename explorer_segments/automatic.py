"""Offline OCR-assisted discovery of Explorer and automatic visual calibration."""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from pydantic import BaseModel

from explorer_segments.detection import Profile, Region, TemplateDetector
from explorer_segments.media import VideoReader


class TextBox(BaseModel):
    text: str
    score: float
    x: float
    y: float
    width: float
    height: float


class TextReader(Protocol):
    def read(self, image: Any) -> list[TextBox]: ...


class LocalOCR:
    """Use only explicit cached models. No import from the code OCR pipeline."""

    def __init__(self, model_root: Path | None = None, device: str = "gpu:0") -> None:
        root = (
            model_root
            or Path(
                os.environ.get("PADDLE_PDX_CACHE_HOME", str(Path.home() / ".paddlex"))
            )
            / "official_models"
        )
        detection = root / "PP-OCRv6_medium_det"
        recognition = root / "PP-OCRv6_medium_rec"
        for folder in (detection, recognition):
            if not all(
                (folder / file).is_file()
                for file in ("inference.json", "inference.pdiparams", "inference.yml")
            ):
                raise ValueError(
                    f"Local model incomplete: {folder}. "
                    "Provide --model-root with preinstalled PaddleOCR models; "
                    "automatic downloads are disabled."
                )
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped] # noqa: PLC0415
        except ImportError as exc:
            raise ValueError(
                "Install local OCR dependencies: uv sync --group paddle-gpu"
            ) from exc
        self.reader = PaddleOCR(
            text_detection_model_name="PP-OCRv6_medium_det",
            text_detection_model_dir=str(detection),
            text_recognition_model_name="PP-OCRv6_medium_rec",
            text_recognition_model_dir=str(recognition),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=device,
            text_det_limit_side_len=1920,
            text_det_limit_type="max",
        )

    def read(self, image: Any) -> list[TextBox]:
        boxes: list[TextBox] = []
        for page in self.reader.predict(image):
            for text, score, poly in zip(
                page["rec_texts"], page["rec_scores"], page["rec_polys"], strict=True
            ):
                xy = np.asarray(poly)
                x, y = xy.min(axis=0)
                right, bottom = xy.max(axis=0)
                boxes.append(
                    TextBox(
                        text=text,
                        score=float(score),
                        x=float(x),
                        y=float(y),
                        width=float(right - x),
                        height=float(bottom - y),
                    )
                )
        return boxes


def rectangle(
    x: float, y: float, width: float, height: float, image_width: int, image_height: int
) -> Region:
    left, top = max(0, x), max(0, y)
    right, bottom = min(image_width, x + width), min(image_height, y + height)
    return Region(
        x=left / image_width,
        y=top / image_height,
        width=(right - left) / image_width,
        height=(bottom - top) / image_height,
    )


def locate_panel(
    boxes: list[TextBox], width: int, height: int
) -> tuple[Region, Region, list[dict[str, Any]]] | None:
    """Require a real heading and a nearby vertical tree, not an Explorer tooltip."""
    for title in sorted(boxes, key=lambda box: -box.score):
        label = title.text.strip(" <>|:[]").casefold()
        if label not in {"explorer", "explorador"} or title.score < 0.8:
            continue
        if title.y > height * 0.4 or title.height < 4:
            continue
        candidates = sorted(
            [
                b
                for b in boxes
                if b.score >= 0.7
                and title.y + title.height < b.y < title.y + 22 * title.height
                and title.x - 2 * title.height <= b.x <= title.x + 7 * title.height
                and b.width < width * 0.35
                and re.fullmatch(r"[\w.\-]+(?: [\w.\-]+){0,2}", b.text.strip())
                and not b.text.strip().isdigit()
            ],
            key=lambda box: box.y,
        )
        # Require at least four separate, vertically stacked tree entries.
        rows: list[TextBox] = []
        for box in candidates:
            if not rows or box.y - rows[-1].y >= title.height * 0.7:
                rows.append(box)
        if len(rows) < 4:
            continue
        rows = rows[:7]
        right = max(b.x + b.width for b in rows)
        bottom = rows[-1].y + rows[-1].height
        panel = rectangle(
            title.x - title.height,
            title.y - title.height * 0.5,
            right - title.x + title.height * 3,
            bottom - title.y + title.height * 1.5,
            width,
            height,
        )
        heading = rectangle(
            title.x - title.height * 0.35,
            title.y - title.height * 0.35,
            title.width + title.height * 0.7,
            title.height * 1.7,
            width,
            height,
        )
        return panel, heading, [b.model_dump() for b in [title, *rows]]
    return None


def common_anchor(present: Any, absent: Any, panel: Region) -> Region | None:
    """Find stable application chrome outside the panel without coordinates."""
    h, w = present.shape[:2]
    gray_a = cv2.cvtColor(present, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(absent, cv2.COLOR_BGR2GRAY)
    patch_w, patch_h = round(w * 0.22), max(16, round(h * 0.025))
    best: tuple[float, Region] | None = None
    for y in range(0, max(1, round(h * 0.35) - patch_h), max(8, patch_h // 2)):
        for x in range(0, w - patch_w, max(16, patch_w // 2)):
            candidate = rectangle(x, y, patch_w, patch_h, w, h)
            if not (
                candidate.x + candidate.width <= panel.x
                or candidate.x >= panel.x + panel.width
                or candidate.y + candidate.height <= panel.y
                or candidate.y >= panel.y + panel.height
            ):
                continue
            template = candidate.crop(gray_a)
            if np.std(template) < 12:
                continue
            search = candidate.crop(gray_b, 0.04)
            score = cv2.minMaxLoc(
                cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            )[1]
            rank = float(score) * min(float(np.std(template)), 50)
            if score >= 0.85 and (best is None or rank > best[0]):
                best = rank, candidate
    return best[1] if best else None


def discover(
    video: Path,
    output: Path,
    ocr: TextReader,
    progress: Callable[[str], None] | None = None,
    discovery_samples: int = 32,
) -> Path:
    """Find positive/negative examples automatically, or fail without guessing."""
    if output.exists():
        raise ValueError("Automatic calibration output already exists")
    reader = VideoReader(video)
    try:
        duration = reader.count / reader.fps
        times = sorted(
            set(
                [
                    0.0,
                    *[float(t) for t in (1, 2, 4, 8, 16) if t < duration],
                    *[
                        duration * i / discovery_samples
                        for i in range(discovery_samples)
                    ],
                ]
            )
        )
        present = None
        panel = None
        heading = None
        evidence: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        prior_negative: tuple[int, float, Any] | None = None
        positive_location: dict[str, Any] = {}
        for seconds in times:
            if progress:
                progress(f"Local AI discovery: {seconds:.2f}s")
            index, timestamp, image = reader.read_at(seconds)
            boxes = ocr.read(image)
            found = locate_panel(boxes, image.shape[1], image.shape[0])
            attempts.append(
                {"frame": index, "seconds": timestamp, "panel_found": found is not None}
            )
            if found and present is None:
                present = image
                panel, heading, evidence = found
                positive_location = {"frame": index, "seconds": timestamp}
                if prior_negative is None:
                    continue
                index, timestamp, image = prior_negative
                found = None
            if present is None:
                prior_negative = index, timestamp, image
                continue
            if panel is None or heading is None or found:
                continue
            if image.shape != present.shape:
                continue
            # Absence requires panel loss plus stable application chrome.
            template = cv2.cvtColor(panel.crop(present), cv2.COLOR_BGR2GRAY)
            search = cv2.cvtColor(panel.crop(image, 0.04), cv2.COLOR_BGR2GRAY)
            panel_score = cv2.minMaxLoc(
                cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            )[1]
            if panel_score > 0.25:
                continue
            anchor = common_anchor(present, image, panel)
            if anchor is None:
                continue
            output.mkdir(parents=True)
            for name, frame in (("present.png", present), ("absent.png", image)):
                if not cv2.imwrite(str(output / name), frame):
                    raise OSError("Cannot save automatic calibration evidence")
            profile = Profile(
                reference_present="present.png",
                reference_absent="absent.png",
                panel_region=panel,
                anchor_region=anchor,
                title_region=heading,
                present_threshold=0.8,
                absent_threshold=0.40,
            )
            TemplateDetector(profile, output)
            path = output / "profile.json"
            path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
            (output / "discovery.json").write_text(
                json.dumps(
                    {
                        "mode": "automatic_local_ocr",
                        "attempts": attempts,
                        "positive_evidence": evidence,
                        "positive_location": positive_location,
                        "negative_location": {"frame": index, "seconds": timestamp},
                        "negative_panel_score": panel_score,
                        "models": ["PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return path
        raise ValueError(
            "Automatic discovery could not confirm both Explorer states "
            "and a stable application anchor. No clips were exported. "
            "Increase --discovery-samples or inspect the recording."
        )
    finally:
        reader.close()
