from __future__ import annotations

from enterprise_rag.application.dto.jobs import (
    DocumentJobDto,
    DocumentJobLaunchDto,
)
from enterprise_rag.application.ports.job_launcher import DocumentJobLauncherPort
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.jobs import DocumentJobState


class StartDocumentJob:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        launcher: DocumentJobLauncherPort,
    ) -> None:
        self._jobs = jobs
        self._launcher = launcher

    async def execute(self, job_id: str) -> DocumentJobLaunchDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        if job.state is DocumentJobState.FAILED:
            job = await self._jobs.transition(
                job_id,
                DocumentJobState.FAILED,
                DocumentJobState.CREATED,
            )
        if job.state is DocumentJobState.NEEDS_ATTENTION:
            job = await self._jobs.transition(
                job_id,
                DocumentJobState.NEEDS_ATTENTION,
                DocumentJobState.RUNNING_TASKS,
            )
        if job.state.terminal or job.state is DocumentJobState.CANCELLING:
            raise revision_error("JOB_NOT_RUNNABLE", {"job_id": job_id})
        process_id = await self._launcher.launch(job_id)
        return DocumentJobLaunchDto(DocumentJobDto.from_domain(job), process_id)
