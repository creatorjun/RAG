# src/enterprise_rag/presentation/cli.py
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from enterprise_rag.application.dto.revision import FolderComparisonDto, RevisionRunDto
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


async def _execute(application: Application, args: argparse.Namespace) -> dict[str, object]:
    if args.command == "doctor":
        settings = application.configuration.settings
        return {
            "status": "ok",
            "schema_version": settings.schema_version,
            "environment": settings.environment,
            "web_enabled": settings.web.enabled,
            "before_root_readable": application.configuration.paths.before_root.is_dir(),
            "after_root_available": application.configuration.paths.after_root.is_dir(),
        }
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
