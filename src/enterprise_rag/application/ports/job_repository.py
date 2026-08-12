from __future__ import annotations

from typing import Protocol

from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class DocumentJobRepositoryPort(Protocol):
    async def create(self, job: DocumentJob) -> None:
        raise NotImplementedError

    async def get(self, job_id: str) -> DocumentJob | None:
        raise NotImplementedError

    async def transition(
        self,
        job_id: str,
        expected: DocumentJobState,
        target: DocumentJobState,
    ) -> DocumentJob:
        raise NotImplementedError
