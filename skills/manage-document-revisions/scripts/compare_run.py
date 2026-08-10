# skills/manage-document-revisions/scripts/compare_run.py
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")
TEXT_EXTENSIONS = {".csv", ".html", ".ini", ".json", ".md", ".rst", ".toml", ".txt", ".xml", ".yaml", ".yml"}


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


def resolve_directory(path: str) -> Path:
    candidate = Path(path).expanduser()
    if is_link_or_reparse(candidate):
        raise ValueError(f"link or reparse root is not allowed: {path}")
    root = candidate.resolve(strict=True)
    if Path(os.path.abspath(candidate)) != root:
        raise ValueError(f"root path must not traverse a link or alias: {path}")
    if not root.is_dir():
        raise ValueError(f"not a real directory: {path}")
    return root


def validate_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if is_link_or_reparse(path):
            raise ValueError(f"symbolic link is not allowed: {path.relative_to(root).as_posix()}")
        resolved = path.resolve(strict=True)
        if not is_within(resolved, root):
            raise ValueError(f"resolved path escapes root: {path.relative_to(root).as_posix()}")
        if not path.is_dir() and not path.is_file():
            raise ValueError(f"special file is not allowed: {path.relative_to(root).as_posix()}")


def collect(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            result[relative] = {
                "path": path,
                "byte_count": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return result


def content_signature(root: Path) -> dict[str, tuple[int, str]]:
    return {
        relative: (entry["byte_count"], entry["sha256"])
        for relative, entry in collect(root).items()
    }


def verify_input_manifest(before_root: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        entry["relative_path"]: (entry["byte_count"], entry["sha256"])
        for entry in manifest.get("files", [])
    }
    if manifest.get("file_count") != len(expected):
        raise ValueError("input manifest file count mismatch")
    if content_signature(before_root) != expected:
        raise ValueError("before tree differs from input manifest")


def read_text(path: Path | None) -> list[str] | None:
    if path is None or path.suffix.lower() not in TEXT_EXTENSIONS:
        return [] if path is None else None
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def comparison(
    before_root: Path,
    documents_root: Path,
    reports_root: Path,
    comparison_id: str,
) -> dict[str, Any]:
    before = collect(before_root)
    after = collect(documents_root)
    records: list[dict[str, Any]] = []
    counts = {"added": 0, "modified": 0, "removed": 0, "unchanged": 0}
    diff_root = reports_root / "diffs" / comparison_id
    for relative in sorted(set(before) | set(after)):
        before_entry = before.get(relative)
        after_entry = after.get(relative)
        if before_entry is None:
            status = "added"
        elif after_entry is None:
            status = "removed"
        elif before_entry["sha256"] == after_entry["sha256"]:
            status = "unchanged"
        else:
            status = "modified"
        counts[status] += 1
        record = {
            "relative_path": relative,
            "status": status,
            "before_sha256": before_entry["sha256"] if before_entry else None,
            "after_sha256": after_entry["sha256"] if after_entry else None,
            "before_byte_count": before_entry["byte_count"] if before_entry else None,
            "after_byte_count": after_entry["byte_count"] if after_entry else None,
            "diff_path": None,
        }
        if status != "unchanged":
            before_path = before_entry["path"] if before_entry else None
            after_path = after_entry["path"] if after_entry else None
            before_lines = read_text(before_path)
            after_lines = read_text(after_path)
            if before_lines is not None and after_lines is not None:
                diff_text = "".join(
                    difflib.unified_diff(
                        before_lines,
                        after_lines,
                        fromfile=f"before/{relative}",
                        tofile=f"after/{relative}",
                    )
                )
                diff_path = diff_root / f"{relative}.diff"
                atomic_write_text(diff_path, diff_text)
                record["diff_path"] = diff_path.relative_to(reports_root).as_posix()
        records.append(record)
    return {
        "schema_version": 1,
        "comparison_id": comparison_id,
        "generated_at": utc_now(),
        "counts": counts,
        "files": records,
    }


def render_markdown(run_id: str, report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        f"<!-- data/after/runs/{run_id}/_reports/comparison.md -->",
        f"# 문서 리비전 비교 보고서: {run_id}",
        "",
        f"- 생성 시각: {report['generated_at']}",
        f"- 추가: {counts['added']}",
        f"- 수정: {counts['modified']}",
        f"- 삭제: {counts['removed']}",
        f"- 동일: {counts['unchanged']}",
        "",
        "| 상태 | 상대 경로 | 수정 전 SHA-256 | 수정 후 SHA-256 | Diff |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in report["files"]:
        diff_value = record["diff_path"] or "-"
        before_hash = record["before_sha256"] or "-"
        after_hash = record["after_sha256"] or "-"
        lines.append(
            f"| {record['status']} | `{record['relative_path']}` | `{before_hash}` | `{after_hash}` | `{diff_value}` |"
        )
    lines.append("")
    return "\n".join(lines)


def compare(before_root: Path, after_root: Path, run_id: str, finalize: bool) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run ID")
    if before_root == after_root or is_within(before_root, after_root) or is_within(after_root, before_root):
        raise ValueError("before and after roots must be distinct and non-overlapping")
    run_candidate = after_root / "runs" / run_id
    if is_link_or_reparse(run_candidate):
        raise ValueError("run path must not be a link or reparse point")
    run_root = run_candidate.resolve(strict=True)
    if not is_within(run_root, after_root):
        raise ValueError("run path escapes after root")
    documents_candidate = run_root / "documents"
    reports_candidate = run_root / "_reports"
    if is_link_or_reparse(documents_candidate) or is_link_or_reparse(reports_candidate):
        raise ValueError("run directories must not be links or reparse points")
    documents_root = documents_candidate.resolve(strict=True)
    reports_root = reports_candidate.resolve(strict=True)
    manifest_path = run_root / "run-manifest.json"
    input_manifest_path = reports_root / "input-manifest.json"
    validate_tree(run_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id:
        raise ValueError("run manifest ID mismatch")
    if manifest.get("state") == "finalized":
        raise ValueError("finalized run is immutable")
    validate_tree(before_root)
    verify_input_manifest(before_root, input_manifest_path)
    before_signature = content_signature(before_root)
    documents_signature = content_signature(documents_root)
    comparison_id = f"cmp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:12]}"
    report = comparison(before_root, documents_root, reports_root, comparison_id)
    if content_signature(before_root) != before_signature:
        raise ValueError("before tree changed during comparison")
    if content_signature(documents_root) != documents_signature:
        raise ValueError("documents tree changed during comparison")
    report["run_id"] = run_id
    atomic_write_json(reports_root / "comparison.json", report)
    atomic_write_text(reports_root / "comparison.md", render_markdown(run_id, report))
    if finalize:
        verify_input_manifest(before_root, input_manifest_path)
        manifest["state"] = "finalized"
        manifest["finalized_at"] = utc_now()
        manifest["comparison_counts"] = report["counts"]
        manifest["comparison_sha256"] = sha256_file(reports_root / "comparison.json")
        atomic_write_json(manifest_path, manifest)
    return report


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
            resolve_directory(args.before_root),
            resolve_directory(args.after_root),
            args.run_id,
            args.finalize,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"COMPARE_FAILED: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
