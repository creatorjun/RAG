from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.model_stream import (
    ModelStreamEventDto,
    ModelStreamSnapshotDto,
)


class ModelStreamRepositoryPort(Protocol):
    def next_sequence(self, job_id: str) -> int:
        raise NotImplementedError

    def append(self, event: ModelStreamEventDto) -> None:
        raise NotImplementedError

    async def snapshot(
        self,
        job_id: str,
        limit: int = 1_000,
    ) -> ModelStreamSnapshotDto:
        raise NotImplementedError
