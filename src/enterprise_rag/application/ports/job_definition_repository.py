from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.jobs import StoredDocumentJobDefinitionDto


class DocumentJobDefinitionRepositoryPort(Protocol):
    async def load(self, job_id: str) -> StoredDocumentJobDefinitionDto:
        raise NotImplementedError
