# skills/manage-document-revisions/scripts/prepare_run.py
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def resolve_before(path: str) -> Path:
    candidate = Path(path).expanduser()
    if is_link_or_reparse(candidate):
        raise ValueError("before root must not be a link or reparse point")
    root = candidate.resolve(strict=True)
    if Path(os.path.abspath(candidate)) != root:
        raise ValueError("before root path must not traverse a link or alias")
    if not root.is_dir():
        raise ValueError("before root must be a real directory")
    return root


def resolve_after(path: str) -> Path:
    candidate = Path(path).expanduser()
    if is_link_or_reparse(candidate):
        raise ValueError("after root must not be a link or reparse point")
    root = candidate.resolve(strict=True)
    if Path(os.path.abspath(candidate)) != root:
        raise ValueError("after root path must not traverse a link or alias")
    if not root.is_dir():
        raise ValueError("after root must be a real directory")
    return root


def validate_layout(before_root: Path, after_root: Path) -> None:
    if before_root == after_root:
        raise ValueError("before and after roots must differ")
    if is_within(before_root, after_root) or is_within(after_root, before_root):
        raise ValueError("before and after roots must not overlap")


def inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if is_link_or_reparse(path):
            raise ValueError(f"symbolic link is not allowed: {path.relative_to(root).as_posix()}")
        resolved = path.resolve(strict=True)
        if not is_within(resolved, root):
            raise ValueError(f"resolved path escapes before root: {path.relative_to(root).as_posix()}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"special file is not allowed: {path.relative_to(root).as_posix()}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"file exceeds size limit: {path.relative_to(root).as_posix()}")
        entries.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "byte_count": size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def copy_inventory(before_root: Path, documents_root: Path, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        source = before_root / entry["relative_path"]
        destination = documents_root / entry["relative_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256_file(destination) != entry["sha256"]:
            raise RuntimeError(f"copied file hash mismatch: {entry['relative_path']}")


def prepare(before_root: Path, after_root: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run ID must be 3-64 lowercase safe characters")
    validate_layout(before_root, after_root)
    entries = inventory(before_root)
    runs_root = after_root / "runs"
    staging_root = after_root / ".staging"
    runs_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    target = runs_root / run_id
    if target.exists():
        raise FileExistsError(f"run already exists: {run_id}")
    temporary = staging_root / f"{run_id}-{uuid.uuid4().hex}"
    documents_root = temporary / "documents"
    reports_root = temporary / "_reports"
    documents_root.mkdir(parents=True)
    reports_root.mkdir(parents=True)
    try:
        copy_inventory(before_root, documents_root, entries)
        if inventory(before_root) != entries:
            raise RuntimeError("before tree changed during preparation")
        prepared_at = utc_now()
        input_manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "captured_at": prepared_at,
            "file_count": len(entries),
            "files": entries,
        }
        run_manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "state": "prepared",
            "prepared_at": prepared_at,
            "finalized_at": None,
            "input_file_count": len(entries),
        }
        write_json(reports_root / "input-manifest.json", input_manifest)
        write_json(temporary / "run-manifest.json", run_manifest)
        os.replace(temporary, target)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-root", required=True)
    parser.add_argument("--after-root", required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        target = prepare(resolve_before(args.before_root), resolve_after(args.after_root), args.run_id)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"PREPARE_FAILED: {error}", file=sys.stderr)
        return 2
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
