from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.job_result import DocumentJobResultDto
from enterprise_rag.domain.jobs import DocumentJob


class DocumentJobResultReaderPort(Protocol):
    async def inspect(self, job: DocumentJob) -> DocumentJobResultDto:
        raise NotImplementedError
