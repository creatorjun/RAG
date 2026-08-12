from datetime import datetime
from typing import Protocol

from enterprise_rag.application.dto.runner import RunnerLeaseDto, RunnerLifecycle


class RunnerLeaseRepositoryPort(Protocol):
    async def begin_launch(
        self,
        job_id: str,
        runner_token: str,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        raise NotImplementedError

    async def claim(
        self,
        job_id: str,
        runner_token: str,
        process_id: int,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        raise NotImplementedError

    async def heartbeat(
        self,
        job_id: str,
        runner_token: str,
        process_id: int,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        raise NotImplementedError

    async def finish(
        self,
        job_id: str,
        runner_token: str,
        process_id: int | None,
        lifecycle: RunnerLifecycle,
        occurred_at: datetime,
        error_code: str | None = None,
    ) -> RunnerLeaseDto:
        raise NotImplementedError

    async def load(self, job_id: str) -> RunnerLeaseDto | None:
        raise NotImplementedError
