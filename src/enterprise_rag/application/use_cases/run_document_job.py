from __future__ import annotations

import logging
import time

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.ports.cancellation import CancellationTokenPort
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.job_stage import DocumentJobStagePort
from enterprise_rag.application.ports.progress_events import ProgressEventPublisherPort
from enterprise_rag.application.services.document_job_cancellation import (
    DocumentJobCancellationService,
)
from enterprise_rag.domain.errors import ApplicationError, ErrorCategory, revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState

LOGGER = logging.getLogger(__name__)

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
        cancellation: CancellationTokenPort | None = None,
    ) -> None:
        states = tuple(stage.state for stage in stages)
        if states != _ACTIVE_FLOW:
            raise ValueError("document job stages must match the fixed pipeline order")
        self._jobs = jobs
        self._events = events
        self._stages = stages
        self._cancellation = cancellation
        self._cancellations = DocumentJobCancellationService(jobs)

    async def execute(self, job_id: str) -> DocumentJobDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        LOGGER.info(
            "document_job_execution_started",
            extra={"job_id": job_id, "job_state": job.state.value},
        )
        if job.state.terminal:
            LOGGER.info(
                "document_job_already_terminal",
                extra={"job_id": job_id, "job_state": job.state.value},
            )
            return DocumentJobDto.from_domain(job)
        cancelled = await self._cancel_if_requested(job_id, job)
        if cancelled is not None:
            return cancelled
        if job.state is DocumentJobState.NEEDS_ATTENTION:
            job = await self._jobs.transition(
                job_id,
                DocumentJobState.NEEDS_ATTENTION,
                DocumentJobState.RUNNING_TASKS,
            )
        last_event = None
        if job.last_event_sequence:
            events = await self._events.list_after(job_id, job.last_event_sequence - 1)
            if events and events[-1].sequence == job.last_event_sequence:
                last_event = events[-1]
        start_index = self._start_index(job.state, None if last_event is None else last_event.stage)
        LOGGER.info(
            "document_job_pipeline_resolved",
            extra={
                "job_id": job_id,
                "job_state": job.state.value,
                "start_stage_index": start_index,
                "stage_count": len(self._stages),
            },
        )
        for index in range(start_index, len(self._stages)):
            stage = self._stages[index]
            current = await self._jobs.get(job_id)
            if current is None:
                raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
            cancelled = await self._cancel_if_requested(job_id, current)
            if cancelled is not None:
                return cancelled
            job = current
            if job.state is not stage.state:
                job = await self._jobs.transition(job_id, job.state, stage.state)
            stage_started_at = time.monotonic()
            LOGGER.info(
                "document_job_stage_started",
                extra={
                    "job_id": job_id,
                    "stage": stage.state.value,
                    "stage_index": index,
                    "stage_count": len(self._stages),
                },
            )
            try:
                result = await stage.execute(job_id)
            except ApplicationError as error:
                LOGGER.error(
                    "document_job_stage_failed",
                    extra={
                        "job_id": job_id,
                        "stage": stage.state.value,
                        "error_code": error.code,
                        "error_category": error.category.value,
                        "duration_ms": round((time.monotonic() - stage_started_at) * 1000),
                    },
                    exc_info=True,
                )
                if error.category is ErrorCategory.CANCELLED:
                    return await self._confirm_cancellation(job_id)
                await self._mark_failed(job_id, stage.state)
                raise
            except Exception as error:
                LOGGER.exception(
                    "document_job_stage_crashed",
                    extra={
                        "job_id": job_id,
                        "stage": stage.state.value,
                        "duration_ms": round((time.monotonic() - stage_started_at) * 1000),
                    },
                )
                await self._mark_failed(job_id, stage.state)
                raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
            current = await self._jobs.get(job_id)
            if current is None:
                raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
            cancelled = await self._cancel_if_requested(job_id, current)
            if cancelled is not None:
                return cancelled
            if current.state is not stage.state:
                raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id})
            job = current
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
            LOGGER.info(
                "document_job_stage_completed",
                extra={
                    "job_id": job_id,
                    "stage": stage.state.value,
                    "stage_index": index,
                    "stage_count": len(self._stages),
                    "percentage": event.percentage,
                    "completed": result.completed,
                    "total": result.total,
                    "counter_name": result.counter_name,
                    "duration_ms": round((time.monotonic() - stage_started_at) * 1000),
                },
            )
        completed = await self._jobs.transition(
            job_id,
            DocumentJobState.PUBLISHING,
            DocumentJobState.COMPLETED,
        )
        LOGGER.info(
            "document_job_completed",
            extra={
                "job_id": job_id,
                "last_event_sequence": completed.last_event_sequence,
                "last_percentage": completed.last_percentage,
            },
        )
        return DocumentJobDto.from_domain(completed)

    async def _cancel_if_requested(
        self,
        job_id: str,
        job: DocumentJob,
    ) -> DocumentJobDto | None:
        requested = job.state is DocumentJobState.CANCELLING or (
            self._cancellation is not None and self._cancellation.is_cancelled
        )
        if not requested:
            return None
        LOGGER.info(
            "document_job_cancellation_confirming",
            extra={"job_id": job_id, "job_state": job.state.value},
        )
        return await self._confirm_cancellation(job_id)

    async def _confirm_cancellation(self, job_id: str) -> DocumentJobDto:
        return await self._cancellations.confirm(job_id)

    @staticmethod
    def _start_index(state: DocumentJobState, last_event_stage: str | None) -> int:
        if state is DocumentJobState.CREATED:
            return 0
        try:
            index = _ACTIVE_FLOW.index(state)
            if last_event_stage == state.value:
                return index + 1
            return index
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
