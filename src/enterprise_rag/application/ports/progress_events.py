from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.progress import ProgressEventDto


class ProgressEventPublisherPort(Protocol):
    async def publish(self, event: ProgressEventDto) -> None:
        raise NotImplementedError

    async def list_after(
        self,
        job_id: str,
        after_sequence: int = 0,
    ) -> tuple[ProgressEventDto, ...]:
        raise NotImplementedError
