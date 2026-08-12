from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.tasks import FinalDocumentCandidateDto


class FinalDocumentRepositoryPort(Protocol):
    async def save(
        self,
        job_id: str,
        candidate: FinalDocumentCandidateDto,
    ) -> tuple[str, str]:
        raise NotImplementedError

    async def load(self, job_id: str) -> FinalDocumentCandidateDto:
        raise NotImplementedError
