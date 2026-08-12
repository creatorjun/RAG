from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.tasks import TaskPlanDto


class TaskPlanRepositoryPort(Protocol):
    async def save(self, job_id: str, plan: TaskPlanDto) -> str:
        raise NotImplementedError

    async def load(self, job_id: str) -> TaskPlanDto:
        raise NotImplementedError
