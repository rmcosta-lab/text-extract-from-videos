"""Durable sequential review execution and offline reapplication."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from video_ocr.models import OutputExtension
from video_ocr.review import (
    ReviewResult,
    apply_review,
    parse_response_record,
    request_review,
    save_review,
)
from video_ocr.review_plan import ReviewBlock
from video_ocr.review_progress import phase
from video_ocr.review_storage import atomic_json, read_json


def validate_block(original: str, review: ReviewResult, block: ReviewBlock) -> None:
    if any(
        not block.start <= edit.start_line <= edit.end_line <= block.end
        for edit in review.edits
    ):
        raise ValueError(
            f"Block {block.number}: edit crosses editable boundary "
            f"{block.start}..{block.end}"
        )
    if any(not block.start <= issue.line <= block.end for issue in review.unresolved):
        raise ValueError(f"Block {block.number}: issue lies outside editable boundary")
    apply_review(original, review, block.frames)


def check_destination(output: Path, extension: OutputExtension) -> None:
    if any(
        (output / name).exists()
        for name in (
            f"codigo_revisado.{extension.value}",
            "comparativo.diff",
            "revisao.json",
            "line_mapping.json",
            "relatorio_revisao.md",
        )
    ):
        raise ValueError("Review output exists; select a new --output directory")


def usage_total(audits: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        key: 0
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cached_tokens",
        )
    }
    for audit in audits:
        usage = audit.get("usage") or {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            totals[key] += usage.get(key, 0)
        totals["reasoning_tokens"] += (usage.get("output_tokens_details") or {}).get(
            "reasoning_tokens", 0
        )
        totals["cached_tokens"] += (usage.get("input_tokens_details") or {}).get(
            "cached_tokens", 0
        )
    return totals


def run_review(
    extraction: Path,
    output: Path,
    original: str,
    extension: OutputExtension,
    blocks: list[ReviewBlock],
    plan: dict[str, Any],
    client_factory: Callable[[], Any] | None = None,
    *,
    resume: bool = False,
    reapply: bool = False,
) -> ReviewResult:
    phase("Validando destino e execução", block="")
    check_destination(output, extension)
    state_path = output / "review_run.json"
    if resume or reapply:
        state = read_json(state_path)
        if state["plan"] != plan:
            raise ValueError(
                "Review configuration or input hashes changed; use a new output"
            )
    else:
        if state_path.exists() or (output / "responses").exists():
            raise ValueError("Saved execution exists; use --resume or --reapply")
        state = {"schema_version": 1, "status": "planned", "plan": plan, "blocks": {}}
        atomic_json(state_path, state)
    config = plan["configuration"]
    results: list[ReviewResult] = []
    audits: list[dict[str, Any]] = []
    attempts_audits: list[dict[str, Any]] = []
    for block in blocks:
        phase("Preparando solicitação", block=f"{block.number}/{len(blocks)}")
        directory = output / "responses" / f"block_{block.number:04d}"
        attempts = sorted(directory.glob("attempt_*.json"))
        review = None
        response_audit: dict[str, Any] = {}
        last_error = "No saved response"
        chosen = None
        for attempt in attempts:
            record = read_json(attempt)
            if record.get("plan_sha256") != plan["plan_sha256"] or (
                record.get("block_number") != block.number
            ):
                raise ValueError("Saved response is bound to a different plan/block")
            attempts_audits.append(record["audit"])
            try:
                candidate, candidate_audit = parse_response_record(record)
                validate_block(original, candidate, block)
            except ValueError as exc:
                last_error = str(exc)
            else:
                review, response_audit, chosen = candidate, candidate_audit, attempt
        if review is None:
            if reapply:
                raise ValueError(
                    f"Block {block.number} cannot be reapplied: {last_error}"
                )
            if client_factory is None:
                raise ValueError("No API client available for pending block")
            attempt_path = directory / f"attempt_{len(attempts) + 1:04d}.json"

            def persist(
                record: dict[str, Any],
                target: Path = attempt_path,
                number: int = block.number,
            ) -> None:
                record.update(plan_sha256=plan["plan_sha256"], block_number=number)
                atomic_json(target, record)
                attempts_audits.append(record["audit"])

            state["status"] = "running"
            state["blocks"][str(block.number)] = {"status": "requesting"}
            atomic_json(state_path, state)
            try:
                phase("Inicializando cliente e envio")
                with client_factory() as client:
                    review, response_audit = request_review(
                        client,
                        config["model"],
                        block.content,
                        config["max_output_tokens"],
                        config["reasoning_effort"],
                        persist,
                    )
                validate_block(original, review, block)
                chosen = attempt_path
            except Exception as exc:
                state["status"] = "failed"
                state["blocks"][str(block.number)] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "response": str(attempt_path.relative_to(output))
                    if attempt_path.exists()
                    else None,
                }
                atomic_json(state_path, state)
                raise
        results.append(review)
        audits.append(response_audit)
        state["blocks"][str(block.number)] = {
            "status": "validated",
            "response": str(chosen.relative_to(output)) if chosen else None,
        }
        atomic_json(state_path, state)
    phase("Consolidando e validando alterações", block="")
    combined = ReviewResult(
        summary="\n".join(result.summary for result in results),
        edits=[edit for result in results for edit in result.edits],
        unresolved=[issue for result in results for issue in result.unresolved],
    )
    frames = set().union(*(block.frames for block in blocks))
    corrected = apply_review(original, combined, frames)
    audit = dict(blocks[0].audit)
    audit.update(
        configuration=config,
        model=config["model"],
        reasoning_effort=config["reasoning_effort"],
        max_output_tokens=config["max_output_tokens"],
        frame_ids=sorted(frames),
        blocks=[block.record() for block in blocks],
        responses=audits,
        usage=usage_total(audits),
        attempt_usage=usage_total(attempts_audits),
        image_bytes=sum(b.audit["image_bytes"] for b in blocks),
        image_sha256={k: v for b in blocks for k, v in b.audit["image_sha256"].items()},
        plan_sha256=plan["plan_sha256"],
        instructions_sha256=plan["instructions_sha256"],
        configuration_sha256=plan["configuration_sha256"],
    )
    phase("Salvando código, diff e relatório", block="")
    save_review(output, original, corrected, extension, combined, audit, extraction)
    state["status"] = "completed"
    atomic_json(state_path, state)
    return combined
