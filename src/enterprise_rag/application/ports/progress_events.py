from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.progress import ProgressEventDto


class ProgressEventPublisherPort(Protocol):
    async def publish(self, event: ProgressEventDto) -> None:
        raise NotImplementedError
