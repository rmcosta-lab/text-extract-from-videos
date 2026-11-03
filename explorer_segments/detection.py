"""Calibrated template detection with a separate application visibility guard."""

from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, Field, model_validator

State = Literal["present", "absent", "uncertain"]


class Region(BaseModel):
    """Normalized x,y,width,height in the correctly oriented reference image."""

    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def bounds(self) -> "Region":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Region extends outside reference image")
        return self

    def crop(self, image: Any, margin: float = 0) -> Any:
        h, w = image.shape[:2]
        x1, y1 = int(max(0, self.x - margin) * w), int(max(0, self.y - margin) * h)
        x2 = int(min(1, self.x + self.width + margin) * w)
        y2 = int(min(1, self.y + self.height + margin) * h)
        return image[y1:y2, x1:x2]


class Profile(BaseModel):
    version: int = 1
    reference_present: str
    reference_absent: str
    panel_region: Region
    anchor_region: Region
    title_region: Region | None = None
    title_threshold: float = Field(default=0.9, gt=0, le=1)
    analysis_width: int = Field(default=720, ge=320, le=1920)
    search_margin: float = Field(default=0.04, ge=0, le=0.3)
    scales: list[float] = Field(default_factory=lambda: [0.95, 1.0, 1.05])
    present_threshold: float = Field(default=0.88, gt=0, le=1)
    absent_threshold: float = Field(default=0.76, ge=0, lt=1)
    anchor_threshold: float = Field(default=0.72, gt=0, le=1)

    @model_validator(mode="after")
    def valid_thresholds(self) -> "Profile":
        if self.version != 1 or self.absent_threshold >= self.present_threshold:
            raise ValueError("Invalid profile version/threshold order")
        if not self.scales or any(not 0.5 <= s <= 2 for s in self.scales):
            raise ValueError("Template scales must be in 0.5..2")
        return self


class Observation(BaseModel):
    frame: int
    seconds: float
    state: State
    panel_score: float
    anchor_score: float
    title_score: float | None = None


class TemplateDetector:
    """Presence evidence plus a stable application anchor; low scores are unknown."""

    def __init__(self, profile: Profile, directory: Path) -> None:
        self.profile = profile
        reference = cv2.imread(str(directory / profile.reference_present))
        negative = cv2.imread(str(directory / profile.reference_absent))
        if reference is None or negative is None:
            raise ValueError("Missing/invalid profile reference images")
        self.aspect = reference.shape[1] / reference.shape[0]
        reference = self.gray(reference)
        self.panel = profile.panel_region.crop(reference)
        self.anchor = profile.anchor_region.crop(reference)
        self.title = (
            profile.title_region.crop(reference) if profile.title_region else None
        )
        for template in (self.panel, self.anchor):
            if min(template.shape) < 8 or np.std(template) < 8:
                raise ValueError("Reference region is too small or lacks visual detail")
        present = self.classify_image(
            cv2.imread(str(directory / profile.reference_present))
        )
        absent = self.classify_image(negative)
        if present[0] != "present" or absent[0] != "absent":
            raise ValueError(
                "References do not separate the states with this profile: "
                f"present={present}, absent={absent}. Adjust regions/thresholds."
            )

    def gray(self, image: Any) -> Any:
        width = self.profile.analysis_width
        height = round(image.shape[0] * width / image.shape[1])
        return cv2.cvtColor(cv2.resize(image, (width, height)), cv2.COLOR_BGR2GRAY)

    def similarity(self, image: Any, template: Any, region: Region) -> float:
        search = region.crop(image, self.profile.search_margin)
        best = -1.0
        for scale in self.profile.scales:
            w, h = round(template.shape[1] * scale), round(template.shape[0] * scale)
            if h > search.shape[0] or w > search.shape[1]:
                continue
            scaled = cv2.resize(template, (w, h))
            score = cv2.minMaxLoc(
                cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
            )[1]
            if np.isfinite(score):
                best = max(best, float(score))
        return best

    def _classify(self, image: Any) -> tuple[State, float, float, float | None]:
        if abs(image.shape[1] / image.shape[0] / self.aspect - 1) > 0.03:
            return "uncertain", 0.0, 0.0, None
        gray = self.gray(image)
        panel = self.similarity(gray, self.panel, self.profile.panel_region)
        anchor = self.similarity(gray, self.anchor, self.profile.anchor_region)
        title = (
            self.similarity(gray, self.title, self.profile.title_region)
            if (self.title is not None and self.profile.title_region is not None)
            else None
        )
        state = self.state_from_scores(panel, anchor, title)
        return state, panel, anchor, title

    def state_from_scores(
        self, panel: float, anchor: float, title: float | None
    ) -> State:
        if anchor < self.profile.anchor_threshold:
            state: State = "uncertain"
        elif panel >= self.profile.present_threshold:
            state = "present"
        elif panel <= self.profile.absent_threshold and (
            title is None or title < self.profile.title_threshold - 0.05
        ):
            state = "absent"
        else:
            state = "uncertain"
        return state

    def classify_image(self, image: Any) -> tuple[State, float, float]:
        state, panel, anchor, _ = self._classify(image)
        return state, panel, anchor

    def observe(self, frame: int, seconds: float, image: Any) -> Observation:
        state, panel, anchor, title = self._classify(image)
        return Observation(
            frame=frame,
            seconds=seconds,
            state=state,
            panel_score=panel,
            anchor_score=anchor,
            title_score=title,
        )
