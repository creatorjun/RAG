from __future__ import annotations

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.ports.cancellation import RunnerCancellationPort
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.progress_events import ProgressEventPublisherPort
from enterprise_rag.application.services.document_job_cancellation import (
    DocumentJobCancellationService,
)
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.jobs import DocumentJobState


class GetDocumentJob:
    def __init__(self, jobs: DocumentJobRepositoryPort) -> None:
        self._jobs = jobs

    async def execute(self, job_id: str) -> DocumentJobDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        return DocumentJobDto.from_domain(job)


class ListDocumentJobs:
    def __init__(self, jobs: DocumentJobRepositoryPort) -> None:
        self._jobs = jobs

    async def execute(self, limit: int = 100) -> tuple[DocumentJobDto, ...]:
        if not 1 <= limit <= 1000:
            raise revision_error("INVALID_INPUT", {"field": "limit"})
        return tuple(
            DocumentJobDto.from_domain(job)
            for job in await self._jobs.list_recent(limit)
        )


class ListDocumentJobEvents:
    def __init__(self, events: ProgressEventPublisherPort) -> None:
        self._events = events

    async def execute(
        self,
        job_id: str,
        after_sequence: int = 0,
    ) -> tuple[ProgressEventDto, ...]:
        return await self._events.list_after(job_id, after_sequence)


class RequestDocumentJobCancellation:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        runners: RunnerCancellationPort | None = None,
    ) -> None:
        self._jobs = jobs
        self._runners = runners
        self._cancellations = DocumentJobCancellationService(jobs)

    async def execute(self, job_id: str) -> DocumentJobDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        if job.state.terminal:
            return DocumentJobDto.from_domain(job)
        cancelling = job
        if job.state is not DocumentJobState.CANCELLING:
            cancelling = await self._jobs.transition(
                job_id,
                job.state,
                DocumentJobState.CANCELLING,
            )
        if self._runners is None:
            return DocumentJobDto.from_domain(cancelling)
        if await self._runners.request(job_id):
            return DocumentJobDto.from_domain(cancelling)
        return await self._cancellations.confirm(job_id)


class ConfirmDocumentJobCancellation:
    def __init__(self, jobs: DocumentJobRepositoryPort) -> None:
        self._cancellations = DocumentJobCancellationService(jobs)

    async def execute(self, job_id: str) -> DocumentJobDto:
        return await self._cancellations.confirm(job_id)
