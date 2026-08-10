# src/enterprise_rag/application/dto/revision.py
from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag.domain.revision import FileChangeStatus, RevisionRunState


@dataclass(frozen=True, slots=True)
class RevisionRunDto:
    run_id: str
    state: RevisionRunState
    input_manifest_sha256: str
    input_file_count: int
    documents_relative_root: str
    prepared_at: str
    finalized_at: str | None


@dataclass(frozen=True, slots=True)
class FileComparisonDto:
    relative_path: str
    status: FileChangeStatus
    before_sha256: str | None
    after_sha256: str | None
    before_byte_count: int | None
    after_byte_count: int | None
    diff_relative_path: str | None


@dataclass(frozen=True, slots=True)
class FolderComparisonDto:
    run_id: str
    comparison_id: str
    generated_at: str
    files: tuple[FileComparisonDto, ...]
    report_sha256: str

    @property
    def counts(self) -> dict[str, int]:
        result = {status.value: 0 for status in FileChangeStatus}
        for file in self.files:
            result[file.status.value] += 1
        return result
