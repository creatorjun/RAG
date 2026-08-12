from __future__ import annotations

from enterprise_rag.application.dto.job_result import DocumentJobResultDto
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.job_result import DocumentJobResultReaderPort
from enterprise_rag.domain.errors import revision_error


class GetDocumentJobResult:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        results: DocumentJobResultReaderPort,
    ) -> None:
        self._jobs = jobs
        self._results = results

    async def execute(self, job_id: str) -> DocumentJobResultDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        return await self._results.inspect(job)
