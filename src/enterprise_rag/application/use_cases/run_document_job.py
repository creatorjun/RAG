from __future__ import annotations

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.job_stage import DocumentJobStagePort
from enterprise_rag.application.ports.progress_events import ProgressEventPublisherPort
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJobState

_ACTIVE_FLOW = (
    DocumentJobState.INSPECTING,
    DocumentJobState.SNAPSHOTTING,
    DocumentJobState.EXTRACTING_EVIDENCE,
    DocumentJobState.BUILDING_CLAIMS,
    DocumentJobState.PLANNING,
    DocumentJobState.RUNNING_TASKS,
    DocumentJobState.VALIDATING_TASKS,
    DocumentJobState.ASSEMBLING,
    DocumentJobState.VALIDATING_FINAL,
    DocumentJobState.PUBLISHING,
)


class RunDocumentJob:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        events: ProgressEventPublisherPort,
        stages: tuple[DocumentJobStagePort, ...],
    ) -> None:
        states = tuple(stage.state for stage in stages)
        if states != _ACTIVE_FLOW:
            raise ValueError("document job stages must match the fixed pipeline order")
        self._jobs = jobs
        self._events = events
        self._stages = stages

    async def execute(self, job_id: str) -> DocumentJobDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        if job.state.terminal:
            return DocumentJobDto.from_domain(job)
        if job.state is DocumentJobState.CANCELLING:
            cancelled = await self._jobs.transition(
                job_id,
                DocumentJobState.CANCELLING,
                DocumentJobState.CANCELLED,
            )
            return DocumentJobDto.from_domain(cancelled)
        if job.state is DocumentJobState.NEEDS_ATTENTION:
            return DocumentJobDto.from_domain(job)
        start_index = self._start_index(job.state)
        for index in range(start_index, len(self._stages)):
            stage = self._stages[index]
            if job.state is not stage.state:
                job = await self._jobs.transition(job_id, job.state, stage.state)
            try:
                result = await stage.execute(job_id)
            except ApplicationError:
                await self._mark_failed(job_id, stage.state)
                raise
            except Exception as error:
                await self._mark_failed(job_id, stage.state)
                raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
            percentage = min(99, round((index + 1) * 99 / len(self._stages)))
            sequence = job.last_event_sequence + 1
            event = ProgressEventDto(
                percentage=max(job.last_percentage, percentage),
                stage=stage.state.value,
                message=result.message.strip(),
                completed=result.completed,
                total=result.total,
                counter_name=result.counter_name,
                job_id=job_id,
                sequence=sequence,
            )
            await self._events.publish(event)
            job = job.record_progress(sequence, event.percentage)
            if result.needs_attention:
                if stage.state not in {
                    DocumentJobState.VALIDATING_TASKS,
                    DocumentJobState.VALIDATING_FINAL,
                }:
                    await self._mark_failed(job_id, stage.state)
                    raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id})
                attention = await self._jobs.transition(
                    job_id,
                    stage.state,
                    DocumentJobState.NEEDS_ATTENTION,
                )
                return DocumentJobDto.from_domain(attention)
        completed = await self._jobs.transition(
            job_id,
            DocumentJobState.PUBLISHING,
            DocumentJobState.COMPLETED,
        )
        return DocumentJobDto.from_domain(completed)

    @staticmethod
    def _start_index(state: DocumentJobState) -> int:
        if state is DocumentJobState.CREATED:
            return 0
        try:
            return _ACTIVE_FLOW.index(state)
        except ValueError as error:
            raise revision_error("JOB_STATE_CONFLICT") from error

    async def _mark_failed(
        self,
        job_id: str,
        expected: DocumentJobState,
    ) -> None:
        try:
            await self._jobs.transition(job_id, expected, DocumentJobState.FAILED)
        except ApplicationError:
            return
