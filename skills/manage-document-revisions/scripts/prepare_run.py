# skills/manage-document-revisions/scripts/prepare_run.py
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from enterprise_rag.application.use_cases.prepare_revision_run import PrepareRevisionRun
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.clock.system import SystemClock, UuidIdGenerator
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator
from enterprise_rag.infrastructure.workspace.path_security import resolve_existing_root

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024


def resolve_before(path: str) -> Path:
    return resolve_existing_root(Path(path), before=True)


def resolve_after(path: str) -> Path:
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


def prepare(before_root: Path, after_root: Path, run_id: str) -> Path:
    use_case = PrepareRevisionRun(_workspace(before_root, after_root))
    asyncio.run(use_case.execute(run_id))
    return after_root / "runs" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-root", required=True)
    parser.add_argument("--after-root", required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        target = prepare(
            resolve_before(args.before_root),
            resolve_after(args.after_root),
            args.run_id,
        )
    except ApplicationError as error:
        print(f"PREPARE_FAILED[{error.code}]: {error.safe_message}", file=sys.stderr)
        return 2
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
