# src/enterprise_rag/infrastructure/workspace/folder_tree_comparator.py
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from enterprise_rag.application.dto.revision import FileComparisonDto, FolderComparisonDto
from enterprise_rag.domain.revision import FileChangeStatus
from enterprise_rag.infrastructure.workspace.file_io import (
    atomic_write_json,
    atomic_write_text,
    sha256_file,
)
from enterprise_rag.infrastructure.workspace.path_security import validate_tree

_TEXT_EXTENSIONS = {
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".rst",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    path: Path
    byte_count: int
    sha256: str


class FolderTreeComparator:
    def compare(
        self,
        before_root: Path,
        documents_root: Path,
        reports_root: Path,
        run_id: str,
        comparison_id: str,
        generated_at: str,
    ) -> FolderComparisonDto:
        before_path = before_root
        documents_path = documents_root
        reports_path = reports_root
        validate_tree(before_path)
        validate_tree(documents_path)
        before = self._collect(before_path)
        after = self._collect(documents_path)
        files = tuple(
            self._compare_file(
                relative,
                before.get(relative),
                after.get(relative),
                reports_path,
                comparison_id,
            )
            for relative in sorted(set(before) | set(after))
        )
        counts = {status.value: 0 for status in FileChangeStatus}
        for file in files:
            counts[file.status.value] += 1
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "comparison_id": comparison_id,
            "generated_at": generated_at,
            "counts": counts,
            "files": [self._to_record(file) for file in files],
        }
        report_path = reports_path / "comparison.json"
        atomic_write_json(report_path, payload)
        atomic_write_text(
            reports_path / "comparison.md",
            self._render_markdown(run_id, generated_at, counts, files),
        )
        return FolderComparisonDto(
            run_id=run_id,
            comparison_id=comparison_id,
            generated_at=generated_at,
            files=files,
            report_sha256=sha256_file(report_path),
        )

    @staticmethod
    def _collect(root: Path) -> dict[str, _TreeEntry]:
        entries: dict[str, _TreeEntry] = {}
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                entries[relative] = _TreeEntry(path, path.stat().st_size, sha256_file(path))
        return entries

    def _compare_file(
        self,
        relative_path: str,
        before: _TreeEntry | None,
        after: _TreeEntry | None,
        reports_root: Path,
        comparison_id: str,
    ) -> FileComparisonDto:
        status = self._status(before, after)
        diff_relative_path = self._write_diff(
            relative_path,
            before.path if before else None,
            after.path if after else None,
            reports_root,
            comparison_id,
            status,
        )
        return FileComparisonDto(
            relative_path=relative_path,
            status=status,
            before_sha256=before.sha256 if before else None,
            after_sha256=after.sha256 if after else None,
            before_byte_count=before.byte_count if before else None,
            after_byte_count=after.byte_count if after else None,
            diff_relative_path=diff_relative_path,
        )

    @staticmethod
    def _status(
        before: _TreeEntry | None,
        after: _TreeEntry | None,
    ) -> FileChangeStatus:
        if before is None:
            return FileChangeStatus.ADDED
        if after is None:
            return FileChangeStatus.REMOVED
        if before.sha256 == after.sha256:
            return FileChangeStatus.UNCHANGED
        return FileChangeStatus.MODIFIED

    def _write_diff(
        self,
        relative_path: str,
        before: Path | None,
        after: Path | None,
        reports_root: Path,
        comparison_id: str,
        status: FileChangeStatus,
    ) -> str | None:
        if status is FileChangeStatus.UNCHANGED:
            return None
        before_lines = self._read_text(before)
        after_lines = self._read_text(after)
        if before_lines is None or after_lines is None:
            return None
        value = "".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"before/{relative_path}",
                tofile=f"after/{relative_path}",
            )
        )
        diff_path = reports_root / "diffs" / comparison_id / f"{relative_path}.diff"
        atomic_write_text(diff_path, value)
        return diff_path.relative_to(reports_root).as_posix()

    @staticmethod
    def _read_text(path: Path | None) -> list[str] | None:
        if path is None:
            return []
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            return None
        try:
            return path.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _to_record(file: FileComparisonDto) -> dict[str, object]:
        return {
            "relative_path": file.relative_path,
            "status": file.status.value,
            "before_sha256": file.before_sha256,
            "after_sha256": file.after_sha256,
            "before_byte_count": file.before_byte_count,
            "after_byte_count": file.after_byte_count,
            "diff_path": file.diff_relative_path,
        }

    @staticmethod
    def _render_markdown(
        run_id: str,
        generated_at: str,
        counts: dict[str, int],
        files: tuple[FileComparisonDto, ...],
    ) -> str:
        lines = [
            f"<!-- data/after/runs/{run_id}/_reports/comparison.md -->",
            f"# 문서 리비전 비교 보고서: {run_id}",
            "",
            f"- 생성 시각: {generated_at}",
            f"- 추가: {counts['added']}",
            f"- 수정: {counts['modified']}",
            f"- 삭제: {counts['removed']}",
            f"- 동일: {counts['unchanged']}",
            "",
            "| 상태 | 상대 경로 | 수정 전 SHA-256 | 수정 후 SHA-256 | Diff |",
            "| --- | --- | --- | --- | --- |",
        ]
        for file in files:
            lines.append(
                "| "
                f"{file.status.value} | `{file.relative_path}` | "
                f"`{file.before_sha256 or '-'}` | `{file.after_sha256 or '-'}` | "
                f"`{file.diff_relative_path or '-'}` |"
            )
        lines.append("")
        return "\n".join(lines)
