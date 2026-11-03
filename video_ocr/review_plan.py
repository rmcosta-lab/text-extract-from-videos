"""Deterministic review blocks and conservative frame coverage."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_ocr.models import OCRRow, OutputExtension
from video_ocr.reconstruction import parse_code_lines
from video_ocr.review import INSTRUCTIONS, ReviewResult, local_path, prepare_request
from video_ocr.review_storage import fingerprint, read_json


@dataclass
class ReviewBlock:
    number: int
    start: int
    end: int
    context_start: int
    context_end: int
    frames: set[int]
    content: list[dict[str, Any]]
    audit: dict[str, Any]

    def record(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "start": self.start,
            "end": self.end,
            "context_start": self.context_start,
            "context_end": self.context_end,
            "audit": self.audit,
        }


def select_frames(
    manifest: dict[str, Any],
    source: list[str],
    first: int,
    last: int,
    selection: str,
    chunked: bool,
) -> tuple[set[int], dict[str, Any]]:
    all_ids = {int(frame["frame_number"]) for frame in manifest["frames"]}

    def fallback(reason: str) -> tuple[set[int], dict[str, Any]]:
        return all_ids, {
            "mode": selection,
            "fallback": reason,
            "selected": sorted(all_ids),
            "discarded": [],
            "coverage": "all_frames",
        }

    if selection == "all" and not chunked:
        return fallback("All frames requested")
    provenance = {int(item["output_line"]): item for item in manifest["lines"]}
    relevant: list[dict[str, Any]] = []
    for line in range(first, last + 1):
        item = provenance.get(line)
        if item is None and source[line - 1].startswith("# [OCR_UNCERTAIN]"):
            item = provenance.get(line + 1)
        if item is None or item["frame_number"] not in all_ids:
            return fallback(f"No reliable provenance for physical line {line}")
        if item["content"] != source[int(item["output_line"]) - 1]:
            return fallback(f"Provenance text mismatch at physical line {line}")
        if item.get("line_number") is None:
            return fallback(
                "No editor line numbering; cannot associate alternatives safely"
            )
        relevant.append(item)
    try:
        rows = [OCRRow.model_validate(frame["ocr"]) for frame in manifest["frames"]]
    except (KeyError, ValueError):
        return fallback("Missing OCR observations for alternative coverage")
    reads = parse_code_lines(rows)
    selected = {int(item["frame_number"]) for item in relevant}
    reasons = {str(i): ["Chosen reconstruction evidence"] for i in selected}
    for item in relevant:
        candidates = [r for r in reads if r.line_number == item["line_number"]]
        if not any(
            r.frame_number == item["frame_number"] and r.content == item["content"]
            for r in candidates
        ):
            return fallback("Chosen observation could not be reproduced from OCR")
        if selection == "all":
            alternatives = candidates
        else:
            groups: dict[str, Any] = {}
            for read in candidates:
                previous = groups.get(read.content)
                rank = (
                    read.sharpness,
                    read.confidence if read.confidence is not None else -1,
                    -read.frame_number,
                )
                if previous is None or rank > previous[0]:
                    groups[read.content] = (rank, read)
            alternatives = [pair[1] for pair in groups.values()]
        for read in alternatives:
            selected.add(read.frame_number)
            reason = (
                f"Editor line {item['line_number']}: alternative/supporting observation"
            )
            reasons.setdefault(str(read.frame_number), [])
            if reason not in reasons[str(read.frame_number)]:
                reasons[str(read.frame_number)].append(reason)
    return selected, {
        "mode": selection,
        "fallback": None,
        "selected": sorted(selected),
        "discarded": sorted(all_ids - selected),
        "coverage": [first, last],
        "reasons": reasons,
        "discard_reason": "No required evidence for this interval",
    }


def plan_review(
    manifest_path: Path, config: dict[str, Any]
) -> tuple[str, OutputExtension, list[ReviewBlock], dict[str, Any]]:
    if not manifest_path.is_file():
        # Keep the existing actionable missing-manifest diagnostic.
        prepare_request(manifest_path)
    manifest = read_json(manifest_path)
    original = local_path(manifest_path.parent, manifest["ocr_original"]).read_text(
        encoding="utf-8"
    )
    source = original.splitlines()
    if not original.strip():
        raise ValueError("Review expects non-empty OCR")
    size = config["chunk_lines"] or len(source)
    blocks: list[ReviewBlock] = []
    extension = OutputExtension(manifest["parameters"]["output_extension"])
    for start in range(1, len(source) + 1, size):
        end = min(len(source), start + size - 1)
        first = max(1, start - config["context_lines"])
        last = min(len(source), end + config["context_lines"])
        frames, coverage = select_frames(
            manifest,
            source,
            first,
            last,
            config["frame_selection"],
            config["chunk_lines"] is not None,
        )
        _, _, ids, content, audit = prepare_request(
            manifest_path,
            config["max_frames"],
            config["image_detail"],
            selected_frames=frames,
            window=(first, last),
            editable=(start, end),
        )
        audit["selection"] = coverage
        blocks.append(
            ReviewBlock(len(blocks) + 1, start, end, first, last, ids, content, audit)
        )
    record = {
        "schema_version": 1,
        "configuration": config,
        "configuration_sha256": fingerprint(config),
        "instructions_sha256": fingerprint(INSTRUCTIONS),
        "schema_sha256": fingerprint(ReviewResult.model_json_schema()),
        "blocks": [block.record() for block in blocks],
    }
    record["plan_sha256"] = fingerprint(record)
    return original, extension, blocks, record
