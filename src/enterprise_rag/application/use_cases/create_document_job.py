from __future__ import annotations

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto, DocumentJobDto
from enterprise_rag.application.ports.clock import IdGeneratorPort
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class CreateDocumentJob:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        artifacts: JobArtifactRepositoryPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._jobs = jobs
        self._artifacts = artifacts
        self._id_generator = id_generator

    async def execute(self, request: CreateDocumentJobDto) -> DocumentJobDto:
        try:
            job = DocumentJob("job-" + self._id_generator.new_id().lower())
        except ValueError as error:
            raise revision_error("INVALID_JOB_ID") from error
        await self._jobs.create(job)
        try:
            await self._artifacts.initialize(job, request)
        except ApplicationError:
            await self._mark_failed(job)
            raise
        except Exception as error:
            await self._mark_failed(job)
            raise revision_error("IO_FAILURE", {"job_id": job.job_id}) from error
        return DocumentJobDto.from_domain(job)

    async def _mark_failed(self, job: DocumentJob) -> None:
        try:
            await self._jobs.transition(
                job.job_id,
                DocumentJobState.CREATED,
                DocumentJobState.FAILED,
            )
        except ApplicationError:
            return
