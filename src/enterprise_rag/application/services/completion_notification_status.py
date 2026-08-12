from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag.application.dto.job_result import (
    CompletionNotificationDto,
    CompletionNotificationState,
    DocumentJobResultDto,
    JobResultAvailability,
)
from enterprise_rag.application.ports.completion_notification import (
    CompletionNotificationReceiptPort,
)
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.job_result import DocumentJobResultReaderPort
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


@dataclass(frozen=True, slots=True)
class CompletionNotificationAssessment:
    status: CompletionNotificationDto
    job: DocumentJob | None = None
    result: DocumentJobResultDto | None = None


class CompletionNotificationStatusService:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        results: DocumentJobResultReaderPort,
        receipts: CompletionNotificationReceiptPort,
    ) -> None:
        self._jobs = jobs
        self._results = results
        self._receipts = receipts

    async def assess(self, job_id: str) -> CompletionNotificationAssessment:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        existing = await self._receipts.get(job_id)
        if existing is not None:
            return CompletionNotificationAssessment(existing)
        result = await self._results.inspect(job)
        if not result.notification_enabled:
            return CompletionNotificationAssessment(
                CompletionNotificationDto(job_id, CompletionNotificationState.DISABLED)
            )
        if (
            job.state is not DocumentJobState.COMPLETED
            or result.availability is not JobResultAvailability.PUBLISHED
        ):
            return CompletionNotificationAssessment(
                CompletionNotificationDto(job_id, CompletionNotificationState.NOT_READY)
            )
        return CompletionNotificationAssessment(
            CompletionNotificationDto(job_id, CompletionNotificationState.READY),
            job,
            result,
        )
