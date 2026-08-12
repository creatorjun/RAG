from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.job_dashboard import JobCheckpointDto


class JobCheckpointInspectorPort(Protocol):
    async def inspect(self, job_id: str) -> tuple[JobCheckpointDto, ...]:
        raise NotImplementedError
