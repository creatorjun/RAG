from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskValidationReportDto,
)


class TaskResultRepositoryPort(Protocol):
    async def save_output(
        self,
        job_id: str,
        attempt: int,
        output: TaskOutputDto,
    ) -> str:
        raise NotImplementedError

    async def load_output(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskOutputDto:
        raise NotImplementedError

    async def save_validation(
        self,
        job_id: str,
        attempt: int,
        report: TaskValidationReportDto,
    ) -> str:
        raise NotImplementedError

    async def load_validation(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskValidationReportDto:
        raise NotImplementedError
