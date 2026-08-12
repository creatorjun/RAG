from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import (
    ClaimDraftDto,
    ClaimRelationDraftDto,
)
from enterprise_rag.application.dto.evidence import EvidenceBundleDto


class ClaimRelationGeneratorPort(Protocol):
    async def generate(
        self,
        drafts: tuple[ClaimDraftDto, ...],
        evidence: EvidenceBundleDto,
        instruction: str,
    ) -> tuple[ClaimRelationDraftDto, ...]:
        raise NotImplementedError
