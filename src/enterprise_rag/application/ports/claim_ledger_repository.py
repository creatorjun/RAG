from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimLedgerDto


class ClaimLedgerRepositoryPort(Protocol):
    async def save(self, job_id: str, ledger: ClaimLedgerDto) -> str:
        raise NotImplementedError

    async def load(self, job_id: str) -> ClaimLedgerDto:
        raise NotImplementedError
