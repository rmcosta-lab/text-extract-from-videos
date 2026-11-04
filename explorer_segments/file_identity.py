"""Read editor breadcrumbs without treating OCR text as filesystem paths."""

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from explorer_segments.automatic import TextBox, TextReader
from explorer_segments.media import VideoReader

FILE = re.compile(r"[\w@+.-]+\.[A-Za-z][A-Za-z0-9]{0,15}")
SEPARATOR = r"[>\u203a\u276f]"


def parse_header(boxes: list[TextBox]) -> dict[str, Any]:
    rows: list[list[TextBox]] = []
    for box in sorted((b for b in boxes if b.score >= 0.8), key=lambda b: b.y):
        row = next(
            (
                r
                for r in rows
                if abs(r[0].y - box.y) < min(r[0].height, box.height) * 0.6
            ),
            None,
        )
        if row is None:
            rows.append([box])
        else:
            row.append(box)
    candidates = []
    tabs = set()
    for row in rows:
        text = " ".join(b.text for b in sorted(row, key=lambda b: b.x))
        names = FILE.findall(text)
        if len(names) == 1 and re.fullmatch(
            r"\s*" + re.escape(names[0]) + r"\s*[xX\u00d7\u25cf]?\s*", text
        ):
            tabs.update(names)
        if not re.search(SEPARATOR, text):
            continue
        parts = [p.strip() for p in re.split(SEPARATOR, text)]
        for i, part in enumerate(parts):
            if not FILE.fullmatch(part) or i == 0:
                continue
            folders = parts[:i]
            complete = all(re.fullmatch(r"[\w@+ .-]+", p) for p in folders)
            complete = complete and not any("..." in p or "…" in p for p in folders)
            candidates.append(
                {
                    "filename": part,
                    "visible_path": "/".join([*folders, part]) if complete else None,
                    "folders": folders if complete else None,
                    "path_status": "visible_relative" if complete else "truncated",
                }
            )
    unique = {(c["filename"], c["visible_path"]): c for c in candidates}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if not unique and len(tabs) == 1:
        return {
            "filename": next(iter(tabs)),
            "visible_path": None,
            "folders": None,
            "path_status": "unavailable",
        }
    return {
        "filename": None,
        "visible_path": None,
        "folders": None,
        "path_status": "ambiguous" if tabs else "unavailable",
    }


def clip_filename(index: int, identity: dict[str, Any] | None = None) -> str:
    name = (identity or {}).get("filename")
    if not name:
        return f"clip_{index:03d}.mp4"
    # Always a basename, even when an edited JSON contains path separators.
    safe = re.sub(r"[^\w.+-]", "_", name).strip(" .")[:100] or "file"
    return f"{safe}__clip_{index:03d}.mp4"


def identify_clips(
    video: Path,
    clips: list[dict[str, Any]],
    ocr: TextReader,
    progress: Callable[[str], None] | None = None,
) -> None:
    reader = VideoReader(video)
    try:
        for index, clip in enumerate(clips, 1):
            if progress:
                progress(f"Reading editor filename {index}/{len(clips)}")
            evidence: list[dict[str, Any]] = []
            seen_frames = set()
            for fraction in (0.15, 0.5, 0.85):
                at = clip["start"] + (clip["end"] - clip["start"]) * fraction
                frame, seconds, image = reader.read_at(at)
                if frame in seen_frames:
                    continue
                seen_frames.add(frame)
                # Restrict OCR to the header rather than the full editor.
                header = image[: max(1, round(image.shape[0] * 0.12))]
                boxes = ocr.read(header)
                evidence.append(
                    {
                        "frame": frame,
                        "seconds": seconds,
                        "reading": parse_header(boxes),
                        "ocr": [b.model_dump() for b in boxes],
                    }
                )
            readings = [e["reading"] for e in evidence]
            names = Counter(r["filename"] for r in readings if r["filename"])
            identity: dict[str, Any] = {
                "filename": None,
                "visible_path": None,
                "folders": None,
                "status": "unreadable",
                "path_status": "unavailable",
                "evidence": evidence,
                "coverage": "three_samples_per_clip",
            }
            if len(names) > 1:
                identity["status"] = "conflicting_readings"
            elif names and next(iter(names.values())) >= 2:
                name = next(iter(names))
                paths = Counter(
                    r["visible_path"] for r in readings if r["visible_path"]
                )
                identity.update(filename=name, status="confirmed")
                if len(paths) == 1 and next(iter(paths.values())) >= 2:
                    match = next(r for r in readings if r["visible_path"])
                    identity.update(
                        {
                            k: match[k]
                            for k in ("visible_path", "folders", "path_status")
                        }
                    )
                elif paths:
                    identity["path_status"] = "unconfirmed"
            elif names:
                identity["status"] = "unconfirmed"
            clip["source_file"] = identity
            clip["file"] = clip_filename(index, identity)
    finally:
        reader.close()
