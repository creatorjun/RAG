from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimDraftDto


class ClaimDraftRepositoryPort(Protocol):
    async def save(
        self,
        job_id: str,
        evidence_id: str,
        drafts: tuple[ClaimDraftDto, ...],
    ) -> str:
        raise NotImplementedError

    async def load(
        self,
        job_id: str,
        evidence_id: str,
    ) -> tuple[ClaimDraftDto, ...] | None:
        raise NotImplementedError
