# src/enterprise_rag/application/ports/document_workspace.py
from pathlib import Path
from typing import Protocol

from enterprise_rag.application.dto.revision import FolderComparisonDto, RevisionRunDto


class DocumentWorkspacePort(Protocol):
    async def prepare_run(self, run_id: str) -> RevisionRunDto:
        raise NotImplementedError

    async def compare_run(self, run_id: str) -> FolderComparisonDto:
        raise NotImplementedError

    async def finalize_run(self, run_id: str) -> RevisionRunDto:
        raise NotImplementedError


class DocumentComparatorPort(Protocol):
    def compare(
        self,
        before_root: Path,
        documents_root: Path,
        reports_root: Path,
        run_id: str,
        comparison_id: str,
        generated_at: str,
    ) -> FolderComparisonDto:
        raise NotImplementedError
