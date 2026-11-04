"""Conservative intervals and timestamped transition evidence."""

import itertools
from collections.abc import Callable
from typing import Any, Literal

from explorer_segments.detection import Observation, TemplateDetector
from explorer_segments.media import VideoReader


def scan(
    reader: VideoReader,
    detector: TemplateDetector,
    duration: float,
    scan_fps: float = 4,
    progress: Callable[[float], None] | None = None,
    refinement_progress: Callable[[float], None] | None = None,
) -> list[Observation]:
    observations: dict[int, Observation] = {}
    if scan_fps == 0:
        frame, seconds, image = reader.read_at(0)
        for index in range(reader.count):
            if index:
                frame, seconds, image = reader.read()
            observations[frame] = detector.observe(frame, seconds, image)
            if progress and frame % max(1, round(reader.fps * 10)) == 0:
                progress(seconds)
    else:
        step = max(1 / reader.fps, 1 / scan_fps)
        requested = 0.0
        while requested < duration - 1 / reader.fps:
            frame, seconds, image = reader.read_at(requested)
            if requested > 1 and seconds <= 0:
                raise ValueError("Decoder does not provide usable frame timestamps")
            observations[frame] = detector.observe(frame, seconds, image)
            if progress and round(requested / step) % max(1, round(10 / step)) == 0:
                progress(seconds)
            requested += step
        # Include a tail observation without seeking beyond the last decodable frame.
        frame, seconds, image = reader.read_at(max(0, duration - 2 / reader.fps))
        observations[frame] = detector.observe(frame, seconds, image)
    return refine_observations(
        reader,
        detector,
        list(observations.values()),
        refinement_progress if refinement_progress is not None else progress,
    )


def refine_observations(
    reader: VideoReader,
    detector: TemplateDetector,
    samples: list[Observation],
    progress: Callable[[float], None] | None = None,
) -> list[Observation]:
    """Refine sparse boundaries; cached scores can be reclassified without decoding."""
    observations = {
        o.frame: o.model_copy(
            update={
                "state": detector.state_from_scores(
                    o.panel_score, o.anchor_score, o.title_score
                )
            }
        )
        for o in samples
    }
    coarse = sorted(observations.values(), key=lambda o: o.frame)
    for left, right in itertools.pairwise(coarse):
        if right.frame - left.frame <= 1 or (
            left.state == right.state and left.state != "uncertain"
        ):
            continue
        frame, seconds, image = reader.read_frame(left.frame)
        if progress:
            progress(seconds)
        while frame <= right.frame:
            observations[frame] = detector.observe(frame, seconds, image)
            if frame == right.frame:
                break
            frame, seconds, image = reader.read()
    ordered = sorted(observations.values(), key=lambda o: o.frame)
    if any(b.seconds <= a.seconds for a, b in itertools.pairwise(ordered)):
        raise ValueError("Non-monotonic decoder timestamps; cannot cut reliably")
    return ordered


def summarize(
    observations: list[Observation],
    min_duration: float = 1,
    max_clip_seconds: float = 60,
    margin_seconds: float = 0,
    confirm_seconds: float = 0.15,
    interval_mode: Literal["continuous", "strict"] = "strict",
) -> dict[str, Any]:
    if interval_mode not in ("continuous", "strict"):
        raise ValueError("Unknown interval mode")
    runs: list[list[Observation]] = []
    for observation in observations:
        if not runs or runs[-1][-1].state != observation.state:
            runs.append([])
        runs[-1].append(observation)
    filtered: list[Observation] = []
    for run in runs:
        short = run[-1].seconds - run[0].seconds < confirm_seconds
        filtered.extend(
            o.model_copy(update={"state": "uncertain"}) if short else o for o in run
        )
    runs = []
    for observation in filtered:
        if not runs or runs[-1][-1].state != observation.state:
            runs.append([])
        runs[-1].append(observation)
    intervals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    last_known: Observation | None = None
    for run in runs:
        first, last = run[0], run[-1]
        if first.state != "uncertain":
            if last_known is not None and last_known.state != first.state:
                transitions.append(
                    {
                        "event": "hidden" if first.state == "absent" else "shown",
                        "previous_state": last_known.state,
                        "new_state": first.state,
                        "last_previous_frame": last_known.frame,
                        "last_previous_seconds": last_known.seconds,
                        "first_confirmed_frame": first.frame,
                        "first_confirmed_seconds": first.seconds,
                        "uncertainty_seconds": first.seconds - last_known.seconds,
                    }
                )
            last_known = last
        if first.state != "absent":
            continue
        start, end = first.seconds + margin_seconds, last.seconds - margin_seconds
        if end - start < min_duration:
            continue
        # End at the last observed absent frame, conservatively excluding its duration.
        while end - start >= min_duration:
            stop = min(end, start + max_clip_seconds) if max_clip_seconds else end
            intervals.append(
                {
                    "start": start,
                    "end": stop,
                    "duration": stop - start,
                    "source_run_first_frame": first.frame,
                    "source_run_last_frame": last.frame,
                }
            )
            start = stop
    if interval_mode == "continuous":
        # Keep the full interval after confirmed absence, including uncertainty.
        # A confirmed reappearance ends it; an open interval ends at video tail.
        intervals = []
        active: Observation | None = None
        spans: list[tuple[Observation, Observation]] = []
        for run in runs:
            first = run[0]
            if active is None and first.state == "absent":
                active = first
            elif active is not None and first.state == "present":
                spans.append((active, first))
                active = None
        if active is not None:
            spans.append((active, filtered[-1]))
        for first, last in spans:
            start, end = first.seconds + margin_seconds, last.seconds - margin_seconds
            while end - start >= min_duration:
                stop = min(end, start + max_clip_seconds) if max_clip_seconds else end
                intervals.append(
                    {
                        "start": start,
                        "end": stop,
                        "duration": stop - start,
                        "source_run_first_frame": first.frame,
                        "source_run_last_frame": last.frame,
                    }
                )
                start = stop
    return {
        "transitions": transitions,
        "clips": intervals,
        "uncertain_ranges": [
            {"start": r[0].seconds, "end": r[-1].seconds}
            for r in runs
            if r[0].state == "uncertain"
        ],
    }
