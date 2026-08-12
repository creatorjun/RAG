from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.evidence import EvidenceItemDto


class ClaimDraftGeneratorPort(Protocol):
    async def generate(
        self,
        evidence: EvidenceItemDto,
        instruction: str,
    ) -> tuple[ClaimDraftDto, ...]:
        raise NotImplementedError
