from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.job_pipeline import JobStageResultDto
from enterprise_rag.domain.jobs import DocumentJobState


class DocumentJobStagePort(Protocol):
    @property
    def state(self) -> DocumentJobState:
        raise NotImplementedError

    async def execute(self, job_id: str) -> JobStageResultDto:
        raise NotImplementedError
