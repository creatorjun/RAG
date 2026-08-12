from __future__ import annotations

from datetime import datetime
from typing import Protocol

from enterprise_rag.application.dto.job_result import (
    CompletionNotificationClaimDto,
    CompletionNotificationDto,
)


class SystemNotificationPort(Protocol):
    async def send(self, title: str, message: str) -> None:
        raise NotImplementedError


class CompletionNotificationReceiptPort(Protocol):
    async def get(self, job_id: str) -> CompletionNotificationDto | None:
        raise NotImplementedError

    async def claim(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
    ) -> CompletionNotificationClaimDto:
        raise NotImplementedError

    async def finish(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
        error_code: str | None = None,
    ) -> CompletionNotificationDto:
        raise NotImplementedError
