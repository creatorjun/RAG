from __future__ import annotations

from collections.abc import Callable

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    TaskPlanDto,
    TaskPlanExecutionDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.use_cases.execute_task_attempt import ExecuteTaskAttempt

TaskCompletionCallback = Callable[[int, int, str, TaskValidationReportDto], None]


class ExecuteTaskPlan:
    def __init__(
        self,
        attempts: ExecuteTaskAttempt,
        maximum_attempts: int = 3,
    ) -> None:
        if not 1 <= maximum_attempts <= 3:
            raise ValueError("maximum task attempts must be between one and three")
        self._attempts = attempts
        self._maximum_attempts = maximum_attempts

    async def execute(
        self,
        job_id: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        progress: TaskCompletionCallback | None = None,
    ) -> TaskPlanExecutionDto:
        outputs = []
        validations = []
        total_attempt_count = 0
        task_total = len(plan.tasks)
        for task_index, packet in enumerate(plan.tasks, start=1):
            previous: TaskValidationReportDto | None = None
            latest = None
            for attempt in range(1, self._maximum_attempts + 1):
                latest = await self._attempts.execute(
                    job_id,
                    packet,
                    ledger,
                    evidence,
                    attempt,
                    previous,
                )
                total_attempt_count += 1
                if latest.validation.valid:
                    break
                previous = latest.validation
            if latest is None:
                raise RuntimeError("task attempt loop did not execute")
            outputs.append(latest.output)
            validations.append(latest.validation)
            if progress is not None:
                progress(task_index, task_total, packet.task_id, latest.validation)
            if not latest.validation.valid:
                return TaskPlanExecutionDto(
                    tuple(outputs),
                    tuple(validations),
                    total_attempt_count,
                    False,
                )
        return TaskPlanExecutionDto(
            tuple(outputs),
            tuple(validations),
            total_attempt_count,
            True,
        )
