# src/enterprise_rag/presentation/cli.py
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from enterprise_rag.application.dto.long_document import LongDocumentPlanDto
from enterprise_rag.application.dto.revision import (
    DocumentIntegrationDto,
    FolderComparisonDto,
    RevisionRunDto,
)
from enterprise_rag.application.use_cases.integrate_documents import IntegrationProgress
from enterprise_rag.bootstrap import Application, build_application
from enterprise_rag.domain.errors import ApplicationError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--environment", choices=("development", "test", "production"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    revision = commands.add_parser("revision")
    revision_commands = revision.add_subparsers(dest="revision_command", required=True)
    for name in ("prepare", "compare", "finalize"):
        command = revision_commands.add_parser(name)
        command.add_argument("--run-id", required=True)
    document = commands.add_parser("document")
    document_commands = document.add_subparsers(dest="document_command", required=True)
    plan = document_commands.add_parser("plan")
    plan.add_argument("--relative-path", required=True)
    integrate = document_commands.add_parser("integrate")
    integrate.add_argument("--run-id")
    integrate.add_argument("--output", default="integrated-technical-guide.md")
    return parser


def _serialize_run(value: RevisionRunDto) -> dict[str, object]:
    result = asdict(value)
    result["state"] = value.state.value
    return result


def _serialize_comparison(value: FolderComparisonDto) -> dict[str, object]:
    return {
        "run_id": value.run_id,
        "comparison_id": value.comparison_id,
        "generated_at": value.generated_at,
        "counts": value.counts,
        "report_sha256": value.report_sha256,
        "files": [
            {
                **asdict(file),
                "status": file.status.value,
            }
            for file in value.files
        ],
    }


def _serialize_long_document_plan(value: LongDocumentPlanDto) -> dict[str, object]:
    chunk_set = value.chunks
    plan = value.context_plan
    all_batches = list(plan.map_batches)
    for reduce_round in plan.reduce_rounds:
        all_batches.extend(reduce_round)
    return {
        "revision_id": chunk_set.revision_id,
        "relative_path": chunk_set.relative_path,
        "source_sha256": chunk_set.source_sha256,
        "normalized_sha256": chunk_set.normalized_sha256,
        "normalized_character_count": chunk_set.coverage.normalized_character_count,
        "chunk_count": len(chunk_set.chunks),
        "max_chunk_model_tokens": max(
            (chunk.model_token_count for chunk in chunk_set.chunks),
            default=0,
        ),
        "coverage": asdict(chunk_set.coverage),
        "map_batch_count": len(plan.map_batches),
        "reduce_round_batch_counts": [len(round_batches) for round_batches in plan.reduce_rounds],
        "max_planned_context_tokens": max(
            (batch.total_planned_tokens for batch in all_batches),
            default=0,
        ),
        "maximum_context_tokens": max(
            (batch.maximum_context_tokens for batch in all_batches),
            default=0,
        ),
        "root_result_id": plan.root_result_id,
        "plan_complete": plan.complete,
    }


def _serialize_integration(value: DocumentIntegrationDto) -> dict[str, object]:
    return {
        "run_id": value.run.run_id,
        "state": value.run.state.value,
        "output_relative_path": (
            f"{value.run.documents_relative_root}/{value.output_relative_path}"
        ),
        "model_id": value.model_id,
        "model_revision": value.model_revision,
        "source_document_count": value.source_document_count,
        "source_chunk_count": value.source_chunk_count,
        "generation_count": value.generation_count,
        "comparison": _serialize_comparison(value.comparison),
    }


def _print_integration_progress(value: IntegrationProgress) -> None:
    counter = ""
    if value.completed is not None and value.total is not None:
        counter = f" ({value.completed}/{value.total})"
    print(
        f"[{value.percentage:3d}%] {value.message}{counter}",
        file=sys.stderr,
        flush=True,
    )


async def _execute(application: Application, args: argparse.Namespace) -> dict[str, object]:
    if args.command == "doctor":
        settings = application.configuration.settings
        return {
            "status": "ok",
            "schema_version": settings.schema_version,
            "environment": settings.environment,
            "web_enabled": settings.web.enabled,
            "operating_context_tokens": settings.models.llm.context_tokens,
            "chunk_max_tokens": settings.chunking.max_tokens,
            "token_counter": settings.chunking.tokenizer_id,
            "model_id": settings.models.llm.model_id,
            "model_revision": settings.models.llm.revision,
            "mlx_lm_available": importlib.util.find_spec("mlx_lm") is not None,
            "before_root_readable": application.configuration.paths.before_root.is_dir(),
            "after_root_available": application.configuration.paths.after_root.is_dir(),
        }
    if args.command == "document":
        if args.document_command == "plan":
            plan_result = await application.plan_long_document.execute(args.relative_path)
            return _serialize_long_document_plan(plan_result)
        integration_result = await application.integrate_documents.execute(
            args.run_id,
            args.output,
            progress=_print_integration_progress,
        )
        return _serialize_integration(integration_result)
    if args.revision_command == "prepare":
        return _serialize_run(await application.prepare_revision_run.execute(args.run_id))
    if args.revision_command == "compare":
        return _serialize_comparison(await application.compare_revision_run.execute(args.run_id))
    return _serialize_run(await application.finalize_revision_run.execute(args.run_id))


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        with build_application(args.project_root, args.environment) as application:
            result = asyncio.run(_execute(application, args))
    except ApplicationError as error:
        payload = {
            "code": error.code,
            "category": error.category.value,
            "message": error.safe_message,
            "retryable": error.retryable,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        payload = {
            "code": "INTERNAL",
            "category": "INTERNAL",
            "message": "처리되지 않은 내부 오류가 발생했습니다.",
            "retryable": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
