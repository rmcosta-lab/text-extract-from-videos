"""Score anchored reference spans without searching for favorable text matches."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from rapidfuzz.distance import Levenshtein

from video_ocr.review_report import load_existing_review
from video_ocr.review_storage import atomic_json, atomic_text, read_json


class ReviewReferenceLine(BaseModel):
    original_line: int = Field(ge=1)
    editor_line: int | None = None
    frames: list[int] = Field(min_length=1)
    text: str | None = None
    exclude_reason: str | None = None


class ReviewReference(BaseModel):
    schema_version: int = 1
    source_sha256: str
    method: str
    lines: list[ReviewReferenceLine]


def text_score(expected: str, actual: str) -> dict[str, Any]:
    expected_lines = expected.split("\n")
    actual_lines = actual.split("\n")
    return {
        "character_errors": Levenshtein.distance(expected, actual),
        "reference_characters": len(expected),
        "word_errors": Levenshtein.distance(expected.split(), actual.split()),
        "reference_words": len(expected.split()),
        "exact": expected == actual,
        "indentation_correct": len(expected_lines) == len(actual_lines)
        and all(
            a[: len(a) - len(a.lstrip(" \t"))] == b[: len(b) - len(b.lstrip(" \t"))]
            for a, b in zip(expected_lines, actual_lines, strict=False)
        ),
    }


def score_review(
    original: str,
    corrected: str,
    mapping: list[dict[str, Any]],
    reference: ReviewReference,
) -> dict[str, Any]:
    source, target = original.splitlines(), corrected.splitlines()
    entries = {item.original_line: item for item in reference.lines}
    if len(entries) != len(reference.lines):
        raise ValueError("Duplicate reference original lines")
    if any(not 1 <= line <= len(source) for line in entries):
        raise ValueError("Reference line outside original file")
    samples: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    done: set[int] = set()
    for line, item in sorted(entries.items()):
        if line in done:
            continue
        if item.exclude_reason or item.text is None:
            excluded.append(
                {
                    "original_line": line,
                    "reason": item.exclude_reason or "No certain transcription",
                }
            )
            continue
        mapped = mapping[line - 1]
        interval = mapped["revised"]
        group = {line}
        if mapped["kind"] == "replacement":
            group = {m["original"] for m in mapping if m["revised"] == interval}
            # Technical uncertainty comments are not source content in the video.
            group = {
                n for n in group if not source[n - 1].startswith("# [OCR_UNCERTAIN]")
            }
        if not group <= entries.keys() or any(
            entries[n].text is None or entries[n].exclude_reason for n in group
        ):
            excluded.append(
                {
                    "original_line": line,
                    "reason": "Replacement spans untranscribed/ambiguous lines",
                }
            )
            continue
        if interval and interval[1] - interval[0] + 1 != len(group):
            # A partial line reference cannot judge restored neighboring content.
            # Do not cherry-pick the best matching line from the expanded block.
            excluded.append(
                {
                    "original_line": line,
                    "reason": "Replacement changes line count; "
                    "needs full-span reference",
                }
            )
            continue
        done.update(group)
        expected = "\n".join(entries[n].text or "" for n in sorted(group))
        before = "\n".join(source[n - 1] for n in sorted(group))
        after = "\n".join(target[interval[0] - 1 : interval[1]]) if interval else ""
        samples.append(
            {
                "original_lines": sorted(group),
                "revised": interval,
                "frames": sorted({f for n in group for f in entries[n].frames}),
                "expected": expected,
                "original_text": before,
                "revised_text": after,
                "original": text_score(expected, before),
                "reviewed": text_score(expected, after),
            }
        )
    metrics: dict[str, Any] = {}
    for variant in ("original", "reviewed"):
        chars = sum(row[variant]["reference_characters"] for row in samples)
        words = sum(row[variant]["reference_words"] for row in samples)
        metrics[variant] = {
            "cer": sum(row[variant]["character_errors"] for row in samples) / chars
            if chars
            else None,
            "wer": sum(row[variant]["word_errors"] for row in samples) / words
            if words
            else None,
            "exact_spans": sum(row[variant]["exact"] for row in samples),
            "indentation_correct_spans": sum(
                row[variant]["indentation_correct"] for row in samples
            ),
        }
    metrics.update(
        corrected_lines=sum(
            len(row["original_lines"])
            for row in samples
            if row["reviewed"]["exact"] and not row["original"]["exact"]
        ),
        regressed_lines=sum(
            len(row["original_lines"])
            for row in samples
            if row["reviewed"]["character_errors"] > row["original"]["character_errors"]
        ),
        improved_lines=sum(
            len(row["original_lines"])
            for row in samples
            if row["reviewed"]["character_errors"] < row["original"]["character_errors"]
        ),
    )
    return {
        "reference_lines": len(entries),
        "scored_spans": len(samples),
        "scored_lines": sum(len(row["original_lines"]) for row in samples),
        "metrics": metrics,
        "samples": samples,
        "excluded": excluded,
        "limitations": "Referência visual parcial; não certifica o documento inteiro. "
        "Indentação usa espaços equivalentes; o vídeo não distingue tabs de espaços. "
        "WER ignora separadores; CER e texto exato preservam espaços internos.",
    }


def evaluate_review(
    extraction: Path, review_dir: Path, reference_path: Path, output: Path
) -> dict[str, Any]:
    original, corrected, _, audit, mapping = load_existing_review(
        extraction, review_dir
    )
    reference = ReviewReference.model_validate(read_json(reference_path))
    if (
        reference.schema_version != 1
        or reference.source_sha256 != audit["source_sha256"]
    ):
        raise ValueError("Reference version/hash does not match original OCR")
    manifest = read_json(extraction / "review_manifest.json")
    frame_ids = {int(f["frame_number"]) for f in manifest["frames"]}
    if any(not set(item.frames) <= frame_ids for item in reference.lines):
        raise ValueError("Reference cites a frame outside extraction")
    result = score_review(original, corrected, mapping, reference)
    result.update(
        source_sha256=reference.source_sha256,
        method=reference.method,
        usage=audit.get("usage"),
        configuration=audit.get("configuration"),
    )
    lines = [
        "# Avaliação da revisão",
        "",
        result["limitations"],
        "",
        f"Linhas: {result['scored_lines']}/{result['reference_lines']}; "
        f"intervalos avaliados: {result['scored_spans']}.",
        "",
        "| Métrica | OCR original | Revisado |",
        "|---|---:|---:|",
    ]
    for key in ("cer", "wer", "exact_spans", "indentation_correct_spans"):
        values = [result["metrics"][v][key] for v in ("original", "reviewed")]
        lines.append(f"| {key} | {values[0]} | {values[1]} |")
    lines += [
        "",
        f"Linhas corrigidas: {result['metrics']['corrected_lines']}; "
        f"regressões: {result['metrics']['regressed_lines']}.",
        "",
        "## Exclusões",
        "",
    ]
    lines += [
        f"- Linha {e['original_line']}: {e['reason']}" for e in result["excluded"]
    ]
    atomic_json(output / "avaliacao_revisao.json", result)
    atomic_text(output / "avaliacao_revisao.md", "\n".join(lines) + "\n")
    return result
