"""Human-readable review evidence and honest original/revised line mapping."""

import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from video_ocr.models import OutputExtension
from video_ocr.review import ReviewResult, apply_review, local_path
from video_ocr.review_storage import atomic_json, atomic_text, read_json


def line_mapping(original: str, review: ReviewResult) -> list[dict[str, Any]]:
    mapping: list[dict[str, Any]] = []
    cursor = 1
    revised = 1
    for edit in sorted(review.edits, key=lambda e: e.start_line):
        while cursor < edit.start_line:
            mapping.append(
                {"original": cursor, "revised": [revised, revised], "kind": "unchanged"}
            )
            cursor += 1
            revised += 1
        count = len(edit.after.split("\n")) if edit.after else 0
        for number in range(edit.start_line, edit.end_line + 1):
            mapping.append(
                {
                    "original": number,
                    "revised": [revised, revised + count - 1] if count else None,
                    "kind": "replacement" if count else "removed",
                }
            )
        revised += count
        cursor = edit.end_line + 1
    while cursor <= len(original.splitlines()):
        mapping.append(
            {"original": cursor, "revised": [revised, revised], "kind": "unchanged"}
        )
        cursor += 1
        revised += 1
    return mapping


def _code(text: str) -> str:
    # HTML escaping preserves literal code, whitespace and embedded backticks.
    return "<pre>" + html.escape(text) + "</pre>"


def _location(entry: dict[str, Any]) -> str:
    if entry["revised"] is None:
        return "removida"
    start, end = entry["revised"]
    suffix = (
        " (intervalo substituído; sem equivalência linha a linha)"
        if (entry["kind"] == "replacement")
        else ""
    )
    return f"{start}-{end}{suffix}"


def render_report(
    original: str,
    review: ReviewResult,
    audit: dict[str, Any],
    mapping: list[dict[str, Any]],
    output: Path,
    extraction: Path | None,
) -> str:
    frames: dict[int, str] = {}
    if extraction is not None:
        manifest = read_json(extraction / "review_manifest.json")
        for frame in manifest["frames"]:
            if frame["frame_number"] not in audit.get("frame_ids", []):
                continue
            relative = (
                frame["review_image"]
                if frame.get("review_image")
                and frame.get("review_crop") == manifest["parameters"]["crop"]
                else frame["original_image"]
            )
            path = local_path(extraction, relative)
            frames[int(frame["frame_number"])] = quote(
                Path(os.path.relpath(path, output)).as_posix(), safe="/"
            )

    def links(ids: list[int]) -> str:
        return (
            ", ".join(
                f"[Frame {i}]({frames[i]})" if i in frames else f"Frame {i}"
                for i in ids
            )
            or "Sem frame citado"
        )

    lines = [
        "# Relatório de revisão",
        "",
        "Sugestões do modelo, ainda não conferidas por uma pessoa.",
        "",
        f"- Alterações: {len(review.edits)}; pendências: {len(review.unresolved)}.",
        "- A numeração original identifica linhas físicas do arquivo OCR.",
        "- Substituições indicam intervalos, não correspondências individuais.",
        "",
        "## Resumo",
        "",
        html.escape(review.summary),
        "",
        "## Configuração e consumo",
        "",
        _code(
            json.dumps(
                {
                    k: audit[k]
                    for k in (
                        "model",
                        "reasoning_effort",
                        "max_output_tokens",
                        "configuration",
                        "usage",
                        "attempt_usage",
                        "image_bytes",
                        "frame_ids",
                    )
                    if k in audit
                },
                ensure_ascii=False,
                indent=2,
            )
        ),
        "",
        "## Alterações",
        "",
    ]
    for index, edit in enumerate(sorted(review.edits, key=lambda e: e.start_line), 1):
        lines.extend(
            [
                f"### {index}. Original {edit.start_line}-{edit.end_line}",
                "",
                f"Revisado: {_location(mapping[edit.start_line - 1])}. "
                f"Tipo: {edit.kind}.",
                "",
                html.escape(edit.reason),
                "",
                links(edit.frames),
                "",
                "Antes:",
                "",
                _code(edit.before),
                "",
                "Depois:",
                "",
                _code(edit.after),
                "",
            ]
        )
    lines.extend(["## Pendências", ""])
    source = original.splitlines()
    for issue in review.unresolved:
        lines.extend(
            [
                f"### Original {issue.line}; "
                f"revisado {_location(mapping[issue.line - 1])}",
                "",
                html.escape(issue.reason),
                "",
                links(issue.frames),
                "",
                "Contexto original:",
                "",
                _code(
                    "\n".join(
                        f"{i + 1}: {source[i]}"
                        for i in range(
                            max(0, issue.line - 2), min(len(source), issue.line + 1)
                        )
                    )
                ),
                "",
            ]
        )
    if not review.unresolved:
        lines.append(
            "Nenhuma pendência declarada pelo modelo; isso não certifica fidelidade."
        )
    return "\n".join(lines) + "\n"


def load_existing_review(
    extraction: Path, output: Path
) -> tuple[str, str, ReviewResult, dict[str, Any], list[dict[str, Any]]]:
    manifest = read_json(extraction / "review_manifest.json")
    saved = read_json(output / "revisao.json")
    audit = saved["audit"]
    original = local_path(extraction, manifest["ocr_original"]).read_text(
        encoding="utf-8"
    )
    if hashlib.sha256(original.encode()).hexdigest() != audit.get("source_sha256"):
        raise ValueError("Original OCR hash differs from saved review")
    if hashlib.sha256(
        (extraction / "review_manifest.json").read_bytes()
    ).hexdigest() != (audit.get("manifest_sha256")):
        raise ValueError("Manifest hash differs from saved review")
    review = ReviewResult.model_validate(saved["review"])
    corrected = apply_review(original, review, set(audit["frame_ids"]))
    extension = OutputExtension(audit["target_extension"])
    actual = (output / f"codigo_revisado.{extension.value}").read_text(encoding="utf-8")
    if corrected != actual:
        raise ValueError("Reviewed file differs from saved edits")
    return original, corrected, review, audit, line_mapping(original, review)


def report_only(extraction: Path, output: Path) -> None:
    original, _, review, audit, mapping = load_existing_review(extraction, output)
    report = render_report(original, review, audit, mapping, output, extraction)
    atomic_json(output / "line_mapping.json", mapping)
    atomic_text(output / "relatorio_revisao.md", report)
