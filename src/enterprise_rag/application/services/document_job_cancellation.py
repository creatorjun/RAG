from __future__ import annotations

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJobState


class DocumentJobCancellationService:
    """Apply the idempotent two-step cancellation state transition."""

    def __init__(self, jobs: DocumentJobRepositoryPort) -> None:
        self._jobs = jobs

    async def confirm(self, job_id: str) -> DocumentJobDto:
        for _ in range(4):
            job = await self._jobs.get(job_id)
            if job is None:
                raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
            if job.state.terminal:
                return DocumentJobDto.from_domain(job)
            target = (
                DocumentJobState.CANCELLED
                if job.state is DocumentJobState.CANCELLING
                else DocumentJobState.CANCELLING
            )
            try:
                updated = await self._jobs.transition(job_id, job.state, target)
            except ApplicationError as error:
                if error.code == "JOB_STATE_CONFLICT":
                    continue
                raise
            if updated.state is DocumentJobState.CANCELLED:
                return DocumentJobDto.from_domain(updated)
        raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id})
