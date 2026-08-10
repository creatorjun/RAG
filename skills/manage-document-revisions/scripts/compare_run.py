# skills/manage-document-revisions/scripts/compare_run.py
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from enterprise_rag.application.dto.revision import FolderComparisonDto
from enterprise_rag.application.use_cases.compare_revision_run import CompareRevisionRun
from enterprise_rag.application.use_cases.finalize_revision_run import FinalizeRevisionRun
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.clock.system import SystemClock, UuidIdGenerator
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator
from enterprise_rag.infrastructure.workspace.path_security import resolve_existing_root

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024


def resolve_directory(path: str) -> Path:
    return resolve_existing_root(Path(path), before=False)


def _workspace(before_root: Path, after_root: Path) -> FolderRevisionWorkspace:
    return FolderRevisionWorkspace(
        before_root,
        after_root,
        FolderTreeComparator(),
        SystemClock(),
        UuidIdGenerator(),
        MAX_FILE_BYTES,
    )


def _to_report(value: FolderComparisonDto) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": value.run_id,
        "comparison_id": value.comparison_id,
        "generated_at": value.generated_at,
        "counts": value.counts,
        "files": [
            {
                "relative_path": file.relative_path,
                "status": file.status.value,
                "before_sha256": file.before_sha256,
                "after_sha256": file.after_sha256,
                "before_byte_count": file.before_byte_count,
                "after_byte_count": file.after_byte_count,
                "diff_path": file.diff_relative_path,
            }
            for file in value.files
        ],
    }


def compare(before_root: Path, after_root: Path, run_id: str, finalize: bool) -> dict[str, Any]:
    workspace = _workspace(before_root, after_root)
    if finalize:
        asyncio.run(FinalizeRevisionRun(workspace).execute(run_id))
        report_path = after_root / "runs" / run_id / "_reports" / "comparison.json"
        return json.loads(report_path.read_text(encoding="utf-8"))
    result = asyncio.run(CompareRevisionRun(workspace).execute(run_id))
    return _to_report(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-root", required=True)
    parser.add_argument("--after-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--finalize", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = compare(
            resolve_existing_root(Path(args.before_root), before=True),
            resolve_directory(args.after_root),
            args.run_id,
            args.finalize,
        )
    except ApplicationError as error:
        print(f"COMPARE_FAILED[{error.code}]: {error.safe_message}", file=sys.stderr)
        return 2
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
