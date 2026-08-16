from __future__ import annotations

import logging
from collections.abc import Callable

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPlanDto,
    TaskPlanExecutionDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.ports.task_result_repository import (
    TaskResultRepositoryPort,
)
from enterprise_rag.application.use_cases.execute_task_attempt import ExecuteTaskAttempt
from enterprise_rag.domain.errors import ApplicationError, revision_error

TaskResumeCallback = Callable[[int, int, str, TaskValidationReportDto], None]
LOGGER = logging.getLogger(__name__)


class ExecuteResumableTaskPlan:
    def __init__(
        self,
        attempts: ExecuteTaskAttempt,
        results: TaskResultRepositoryPort,
        maximum_attempts: int,
    ) -> None:
        if not 1 <= maximum_attempts <= 3:
            raise ValueError("maximum task attempts must be between one and three")
        self._attempts = attempts
        self._results = results
        self._maximum_attempts = maximum_attempts

    async def execute(
        self,
        job_id: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        progress: TaskResumeCallback | None = None,
    ) -> TaskPlanExecutionDto:
        outputs: list[TaskOutputDto] = []
        validations: list[TaskValidationReportDto] = []
        total_attempts = 0
        for task_index, packet in enumerate(plan.tasks, start=1):
            existing = await self._existing_attempts(job_id, packet.task_id)
            total_attempts += len(existing)
            latest_output = existing[-1][0] if existing else None
            latest_validation = (
                self._accepted(existing[-1][1]) if existing else None
            )
            if existing and not existing[-1][1].valid:
                LOGGER.info(
                    "document_task_legacy_quality_gate_ignored",
                    extra={
                        "job_id": job_id,
                        "task_id": packet.task_id,
                        "legacy_error_codes": list(existing[-1][1].error_codes),
                    },
                )
            next_attempt = len(existing) + 1
            while (
                (latest_validation is None or not latest_validation.valid)
                and next_attempt <= self._maximum_attempts
            ):
                result = await self._attempts.execute(
                    job_id,
                    packet,
                    ledger,
                    evidence,
                    next_attempt,
                    latest_validation,
                )
                latest_output = result.output
                latest_validation = self._accepted(result.validation)
                total_attempts += 1
                LOGGER.info(
                    "document_task_output_generated",
                    extra={
                        "job_id": job_id,
                        "task_id": packet.task_id,
                        "task_index": task_index,
                        "task_count": len(plan.tasks),
                        "attempt": next_attempt,
                    },
                )
                next_attempt += 1
            if latest_output is None or latest_validation is None:
                raise revision_error("TASK_OUTPUT_INVALID", {"task_id": packet.task_id})
            outputs.append(latest_output)
            validations.append(latest_validation)
            if progress is not None:
                progress(
                    task_index,
                    len(plan.tasks),
                    packet.task_id,
                    latest_validation,
                )
        complete = len(outputs) == len(plan.tasks) and all(
            report.valid for report in validations
        )
        return TaskPlanExecutionDto(
            tuple(outputs),
            tuple(validations),
            total_attempts,
            complete,
        )

    async def load(self, job_id: str, plan: TaskPlanDto) -> TaskPlanExecutionDto:
        outputs: list[TaskOutputDto] = []
        validations: list[TaskValidationReportDto] = []
        total_attempts = 0
        for packet in plan.tasks:
            existing = await self._existing_attempts(job_id, packet.task_id)
            total_attempts += len(existing)
            if not existing:
                break
            output, validation = existing[-1]
            outputs.append(output)
            validations.append(self._accepted(validation))
        complete = len(outputs) == len(plan.tasks) and all(
            report.valid for report in validations
        )
        return TaskPlanExecutionDto(
            tuple(outputs),
            tuple(validations),
            total_attempts,
            complete,
        )

    async def _existing_attempts(
        self,
        job_id: str,
        task_id: str,
    ) -> tuple[tuple[TaskOutputDto, TaskValidationReportDto], ...]:
        found: list[tuple[TaskOutputDto, TaskValidationReportDto]] = []
        gap_seen = False
        for attempt in range(1, self._maximum_attempts + 1):
            output = await self._load_output(job_id, task_id, attempt)
            validation = await self._load_validation(job_id, task_id, attempt)
            if (output is None) != (validation is None):
                raise revision_error("TASK_OUTPUT_INVALID", {"task_id": task_id})
            if output is None or validation is None:
                gap_seen = True
                continue
            if gap_seen or validation.task_id != task_id or output.task_id != task_id:
                raise revision_error("TASK_OUTPUT_INVALID", {"task_id": task_id})
            found.append((output, validation))
        return tuple(found)

    @staticmethod
    def _accepted(report: TaskValidationReportDto) -> TaskValidationReportDto:
        if report.valid:
            return report
        return TaskValidationReportDto(report.task_id, True, ())

    async def _load_output(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskOutputDto | None:
        try:
            return await self._results.load_output(job_id, task_id, attempt)
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                return None
            raise

    async def _load_validation(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskValidationReportDto | None:
        try:
            return await self._results.load_validation(job_id, task_id, attempt)
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                return None
            raise
